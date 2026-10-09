"""音乐 cog 的进程内状态（cogs/music.py）与后台任务工具（utils/tasks.py）。

B25：`skip` 连按两次就把该歌单加进 `_cancelled_playlists`，之后 `_enqueue_playlist_rest` 一开头
  `if query in self._cancelled_playlists: return` —— 而这个集合从不清除，`_playlist_skip_counts` 也跨天累计。
  结果：一个歌单被跳过两次之后，之后**任何人**再点播它都只会加载第一首，直到 bot 重启。
B26：`create_task(...)` 发了就不管，异常只会在任务被回收时打一条 "Task exception was never retrieved"，
  而且事件循环只持有任务的弱引用，没人保存引用的话任务可能在执行中途被回收。

音乐本身要 yt-dlp / ffmpeg / 语音连接，这里全部换成替身，只验证状态的生命周期。
"""

import asyncio
import gc
import logging

import pytest

from cogs import music as music_mod
from cogs.music import MusicCog
from tests.discord_fakes import FakeContext
from utils import tasks as tasks_mod

PLAYLIST = "https://www.youtube.com/playlist?list=PLabcdef"
OTHER = "https://www.youtube.com/playlist?list=PLother"
DATA = {"title": "歌单", "entries": [{"title": f"歌{i}", "url": f"u{i}"} for i in range(1, 4)]}


class FakeVoice:
    def __init__(self, playing=True):
        self.playing, self.stopped = playing, 0

    def is_connected(self):
        return True

    def is_playing(self):
        return self.playing

    def is_paused(self):
        return False

    def stop(self):
        self.stopped += 1
        self.playing = False

    async def disconnect(self):
        pass


class FakeYtdl:
    def __init__(self, data):
        self.params, self.data = {}, data

    def extract_info(self, query, download=False):
        return self.data


@pytest.fixture
def cog(monkeypatch):
    c = MusicCog(bot=type("Bot", (), {"loop": None})())
    monkeypatch.setattr(c, "_play_next", lambda ctx: None)                       # 不真的起 ffmpeg
    monkeypatch.setattr(music_mod, "get_ytdl", lambda with_cookies=True: FakeYtdl(DATA))
    return c


def ctx(playing=True):
    c = FakeContext(user_id=1)
    c.voice_client = FakeVoice(playing)
    return c


def now_playing(cog, query=PLAYLIST):
    cog.current = {"title": "歌1", "playlist_query": query}


# --- B25：歌单取消状态的生命周期 ----------------------------------------------

async def test_跳过一次不取消歌单_两次才取消(db, cog):
    now_playing(cog)
    await cog.skip.callback(cog, ctx())
    assert cog._playlist_skip_counts[PLAYLIST] == 1 and PLAYLIST not in cog._cancelled_playlists

    cog.current = {"title": "歌2", "playlist_query": PLAYLIST}
    await cog.skip.callback(cog, ctx())
    assert PLAYLIST in cog._cancelled_playlists


async def test_没在播放时跳过_不改任何状态(db, cog):
    now_playing(cog)
    c = ctx(playing=False)
    await cog.skip.callback(cog, c)
    assert c.said("无正在播放") and not cog._playlist_skip_counts


async def test_不是歌单里的曲目被跳过_不记录(db, cog):
    cog.current = {"title": "单曲"}
    await cog.skip.callback(cog, ctx())
    assert not cog._playlist_skip_counts and not cog._cancelled_playlists


async def test_歌单被取消后_后台不再加载剩余歌曲(db, cog):
    cog._cancelled_playlists.add(PLAYLIST)
    await cog._enqueue_playlist_rest(ctx(), PLAYLIST)
    assert len(cog.queue) == 0


async def test_重新点播被取消过的歌单_状态重置_剩余歌曲照常加载(db, cog):
    """B25：以前取消一次就永久生效 —— 之后任何人点播这个歌单都只剩第一首，直到 bot 重启。"""
    cog._cancelled_playlists.add(PLAYLIST)
    cog._playlist_skip_counts[PLAYLIST] = 2

    await cog.play.callback(cog, ctx(playing=True), query=PLAYLIST)
    assert PLAYLIST not in cog._cancelled_playlists and PLAYLIST not in cog._playlist_skip_counts

    await cog._enqueue_playlist_rest(ctx(), PLAYLIST)
    assert len(cog.queue) == 1 + 2                                             # 第一首 + 剩下两首


async def test_跳过计数不会跨次点播累计(db, cog):
    """今天跳过一次、改天重新点播后再跳过一次，不应该被当成『连续跳过两次』而取消。"""
    now_playing(cog)
    await cog.skip.callback(cog, ctx())
    await cog.play.callback(cog, ctx(), query=PLAYLIST)                         # 重新点播 → 计数清零
    now_playing(cog)
    await cog.skip.callback(cog, ctx())
    assert PLAYLIST not in cog._cancelled_playlists and cog._playlist_skip_counts[PLAYLIST] == 1


async def test_不同歌单互不影响(db, cog):
    cog._cancelled_playlists.add(OTHER)
    await cog.play.callback(cog, ctx(), query=PLAYLIST)
    assert OTHER in cog._cancelled_playlists                                    # 点播 A 不会重置 B


async def test_停止与离开会清掉歌单状态(db, cog):
    for name in ("stop", "leave"):
        cog._cancelled_playlists.add(PLAYLIST)
        cog._playlist_skip_counts[PLAYLIST] = 2
        await getattr(cog, name).callback(cog, ctx())
        assert not cog._cancelled_playlists and not cog._playlist_skip_counts, name


# --- B26：后台任务 ------------------------------------------------------------

async def test_spawn_出错会记ERROR日志(db, caplog):
    log = logging.getLogger("test.spawn")

    async def _boom():
        raise RuntimeError("后台任务炸了")
    with caplog.at_level(logging.DEBUG, logger="test.spawn"):
        task = tasks_mod.spawn(_boom(), log=log, name="炸弹")
        await asyncio.sleep(0.05)

    assert task.done()
    errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errs and "炸弹" in errs[0].getMessage()


async def test_spawn_正常完成不报错_并释放引用(db, caplog):
    log = logging.getLogger("test.spawn")
    done = []

    async def _ok():
        done.append(1)
    with caplog.at_level(logging.DEBUG, logger="test.spawn"):
        task = tasks_mod.spawn(_ok(), log=log, name="好任务")
        await asyncio.sleep(0.05)

    assert done == [1] and task.done() and task not in tasks_mod._background_tasks
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_spawn_被取消不算出错(db, caplog):
    log = logging.getLogger("test.spawn")

    async def _forever():
        await asyncio.sleep(3600)
    with caplog.at_level(logging.DEBUG, logger="test.spawn"):
        task = tasks_mod.spawn(_forever(), log=log, name="长任务")
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0.05)
    assert task.cancelled() and not [r for r in caplog.records if r.levelno >= logging.ERROR]


async def test_spawn_持有引用_垃圾回收不会让任务中途消失(db):
    """事件循环对任务只有弱引用：没人保存引用的话，任务可能在执行中途被回收。"""
    log = logging.getLogger("test.spawn")
    finished = []

    async def _slow():
        await asyncio.sleep(0.1)
        finished.append(1)
    task = tasks_mod.spawn(_slow(), log=log, name="慢任务")
    assert task in tasks_mod._background_tasks                                  # 引用由模块持有
    del task                                                                    # 调用方不保存也不要紧
    gc.collect()
    await asyncio.sleep(0.25)
    assert finished == [1]


async def test_播放歌单第一首时_后台加载剩余歌曲出错也会被记录(db, cog, monkeypatch, caplog):
    """B26：music._play_next 用 bot.loop.create_task 发了就不管，后台加载失败没有任何日志。"""
    loop = asyncio.get_running_loop()
    cog.bot.loop = loop
    real_play_next = MusicCog._play_next
    monkeypatch.setattr(music_mod.discord, "FFmpegPCMAudio", lambda *a, **k: object())
    monkeypatch.setattr(music_mod, "build_ffmpeg_options", lambda headers: {})

    async def _boom(self, c, q):
        raise RuntimeError("加载剩余歌曲失败")
    monkeypatch.setattr(MusicCog, "_enqueue_playlist_rest", _boom)
    cog.queue.append({"title": "歌1", "url": "u1", "playlist_query": PLAYLIST, "is_first_from_playlist": True})
    c = ctx()
    c.voice_client.play = lambda audio, after=None: None

    with caplog.at_level(logging.DEBUG):
        real_play_next(cog, c)
        await asyncio.sleep(0.1)

    assert [r for r in caplog.records
            if r.levelno >= logging.ERROR and r.name == "cogs.music" and "加载歌单剩余歌曲" in r.getMessage()]
