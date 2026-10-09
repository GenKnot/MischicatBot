"""主菜单与角色面板（utils/views/menu.py）：文案、按钮组成、每个按钮的分派。

按钮大多只是把请求转给某个 cog，所以用一个假 cog 记录『谁被调用了、作者是不是点击的人』；
需要读库的分支（城市、装备、采集、丹阁、返回主菜单、队伍）用真实数据库跑。
"""

import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest
from sqlalchemy import text

from tests.conftest import make_player
from tests.discord_fakes import FakeContext, FakeInteraction
from utils.views import menu as menu_mod
from utils.views.menu import (MainMenuView, MenuButton, ProfileView, _build_gameplay_description,
                              _build_menu_embed, _get_event_hint, _get_joinable_sects)

UID = "1001"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _fresh_hint_cache():
    menu_mod._event_hint_cache = None
    yield
    menu_mod._event_hint_cache = None


async def _add(db, uid=UID, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=1000)
    p.name = f"道友{uid}"
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _sql(db, sql, **params):
    async with db["db_async"].AsyncSessionLocal() as s:
        await s.execute(text(sql), params)
        await s.commit()


async def _event(db, status="active", title="灵雨", ends_in=600):
    await _sql(db, "INSERT INTO public_events (event_id, event_type, title, started_at, ends_at, status, data) "
                   "VALUES (:i, 'spirit_rain', :t, :s, :e, :st, '{}')",
               i=f"E{time.time_ns()}", t=title, s=time.time(), e=time.time() + ends_in, st=status)


# --- 公共事件提示 -------------------------------------------------------------

async def test_事件提示_没有事件用默认文案(db):
    assert _get_event_hint() == menu_mod._DEFAULT_EVENT_HINT


async def test_事件提示_进行中显示剩余分钟(db):
    await _event(db, "active", "灵雨", ends_in=600)
    hint = _get_event_hint()
    assert "「灵雨」进行中" in hint and re.search(r"还剩 (9|10) 分钟", hint)


async def test_事件提示_已过期但状态仍active_剩余为0(db):
    await _event(db, "active", "灵雨", ends_in=-100)
    assert "还剩 0 分钟" in _get_event_hint()


async def test_事件提示_即将开始(db):
    await _event(db, "pending", "万宝楼拍卖会")
    assert "「万宝楼拍卖会」即将开始" in _get_event_hint()


async def test_事件提示_已结束的不显示(db):
    await _event(db, "settled", "旧事件")
    assert _get_event_hint() == menu_mod._DEFAULT_EVENT_HINT


async def test_事件提示_取最新开始的一个(db):
    await _sql(db, "INSERT INTO public_events (event_id, event_type, title, started_at, ends_at, status, data) "
                   "VALUES ('old', 'x', '旧的', 1, 9e12, 'active', '{}'), ('new', 'x', '新的', 2, 9e12, 'active', '{}')")
    assert "「新的」" in _get_event_hint()


async def test_事件提示_有缓存_20秒内不重复查库(db):
    await _event(db, "active", "灵雨")
    first = _get_event_hint()
    await _sql(db, "DELETE FROM public_events")
    assert _get_event_hint() == first                                           # 命中缓存


async def test_事件提示_缓存过期后重新查库(db):
    await _event(db, "active", "灵雨")
    _get_event_hint()
    await _sql(db, "DELETE FROM public_events")
    ts, hint = menu_mod._event_hint_cache
    menu_mod._event_hint_cache = (ts - menu_mod._EVENT_HINT_TTL - 1, hint)
    assert _get_event_hint() == menu_mod._DEFAULT_EVENT_HINT


async def test_事件提示_读库失败回默认_且不缓存(db, monkeypatch):
    import sqlite3
    real = sqlite3.connect

    def boom(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(sqlite3, "connect", boom)
    assert _get_event_hint() == menu_mod._DEFAULT_EVENT_HINT
    assert menu_mod._event_hint_cache is None                                   # 出错这次不能把默认文案缓存 20 秒
    monkeypatch.setattr(sqlite3, "connect", real)
    await _event(db, "active", "灵雨")
    assert "灵雨" in _get_event_hint()


async def test_事件提示_连接用很短的超时_不会冻住事件循环(db, monkeypatch):
    import sqlite3
    seen = {}
    real = sqlite3.connect

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)
    monkeypatch.setattr(sqlite3, "connect", spy)
    _get_event_hint()
    assert seen.get("timeout", 5) <= 1


# --- 文案 ---------------------------------------------------------------------

def test_玩法说明_双修段落只在有双修功法时出现():
    assert "双修系统" not in _build_gameplay_description(False, "x")
    assert "双修系统" in _build_gameplay_description(True, "x")


def test_玩法说明_事件提示原样带入_不传则自己查(db):
    assert "自定义提示" in _build_gameplay_description(False, "自定义提示")
    assert menu_mod._DEFAULT_EVENT_HINT in _build_gameplay_description(False)


def test_菜单embed_仅玩法时没有指令速查(db):
    e = _build_menu_embed(gameplay_only=True, event_hint="x")
    assert not e.fields and e.footer.text


def test_菜单embed_完整版带指令速查(db):
    e = _build_menu_embed(event_hint="x")
    assert [f.name for f in e.fields] == ["指令速查（前缀缩写）", "基础 / 修炼", "出行 / 探险 / 任务",
                                           "背包 / 装备 / 物品", "居所 / 宗门 / 功法", "公共事件 / 其他"]
    assert all(len(f.value) <= 1024 for f in e.fields) and len(e.description) <= 4096


def _real_command_names() -> set[str]:
    """从 cogs/*.py 里扫出所有真实的命令名与别名。"""
    names = set()
    for path in (ROOT / "cogs").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        for deco in re.findall(r"@commands\.(?:hybrid_)?command\((.*?)\)\s*\n", src):
            names.update(re.findall(r'name="([^"]+)"', deco))
            for al in re.findall(r"aliases=\[(.*?)\]", deco):
                names.update(re.findall(r'"([^"]+)"', al))
    return names


def test_指令速查里的命令都真实存在(db):
    """速查是手写的，命令改名 / 删除后文案不会自己更新 —— 玩家照着输会得到『找不到命令』。"""
    from utils.config import COMMAND_PREFIX
    real = _real_command_names()
    assert len(real) > 50, "扫描不到命令，守卫失效了"
    listed = set()
    for f in _build_menu_embed(event_hint="x").fields[1:]:
        for line in f.value.splitlines():
            for token in re.findall(r"`" + re.escape(COMMAND_PREFIX) + r"([^`/]+)`", line):
                listed.add(token)
    missing = sorted(listed - real)
    assert not missing, f"速查里列出了不存在的命令：{missing}"


# --- 可加入的宗门 -------------------------------------------------------------

def _p(**kw):
    base = dict(current_city="凌霄城", sect=None, realm="炼气期1层", spirit_root="金", spirit_root_type="单灵根",
                comprehension=8, physique=5, fortune=5, bone=5, soul=5, rebirth_count=0, discovered_sects="[]")
    base.update(kw)
    return base


def test_可加入宗门_没有玩家或已有宗门为空():
    assert _get_joinable_sects(None) == [] and _get_joinable_sects({}) == []
    assert _get_joinable_sects(_p(sect="御剑阁")) == []


def test_可加入宗门_所在城市且满足条件():
    assert _get_joinable_sects(_p()) == ["御剑阁"]


def test_可加入宗门_条件不满足或城市不对不出现():
    assert _get_joinable_sects(_p(comprehension=7)) == []
    assert _get_joinable_sects(_p(current_city="天京城")) == []


def test_可加入宗门_隐世宗门从不出现在按钮里():
    assert _get_joinable_sects(_p(current_city="古战场遗迹", discovered_sects='["无极道"]')) == []


# --- 主菜单按钮组成 -----------------------------------------------------------

def actions(view):
    return [b.action for b in view.children]


def menu(has_player=True, can_bt=False, player=None, city_players=None):
    return MainMenuView(FakeContext().author, has_player, can_bt, SimpleNamespace(), player, city_players)


def test_主菜单_没有角色时给创建按钮_且没有角色相关按钮():
    a = actions(menu(has_player=False))
    assert a[0] == "create"
    for x in ("city", "backpack", "techniques", "equipment", "crafting"):
        assert x not in a


def test_主菜单_有角色时没有创建按钮():
    a = actions(menu())
    assert "create" not in a
    for x in ("profile", "cultivate", "world", "travel", "explore", "city", "backpack", "techniques",
              "equipment", "crafting", "public_event"):
        assert x in a


def test_主菜单_突破按钮只在能突破时出现():
    assert "breakthrough" not in actions(menu(can_bt=False))
    assert "breakthrough" in actions(menu(can_bt=True))


def test_主菜单_同城有人才出现玩家按钮():
    assert "city_players" not in actions(menu())
    assert "city_players" in actions(menu(city_players=[{"discord_id": "2"}]))


def test_主菜单_队伍按钮要有队伍():
    assert "party_info" not in actions(menu(player=_p()))
    a = actions(menu(player=_p(party_id="P1")))
    assert "party_info" in a and "party_leave" in a


def test_主菜单_秘地显示对应采集按钮():
    a = actions(menu(player=_p(current_city="百草谷")))
    assert "gather:采药" in a
    assert not [x for x in actions(menu(player=_p())) if x.startswith("gather:")]


def test_主菜单_秘地类型没有表情映射时不出采集按钮():
    """昆仑秘境是『秘境』、天雷谷是『修炼』，不是采集类。"""
    assert not [x for x in actions(menu(player=_p(current_city="昆仑秘境"))) if x.startswith("gather:")]


def test_主菜单_可加入宗门按钮():
    assert "join_sect:御剑阁" in actions(menu(player=_p()))


def test_主菜单_万宝楼与丹阁入口():
    assert "wanbao" in actions(menu(player=_p(current_city="万宝楼")))
    assert "wanbao" not in actions(menu(player=_p()))
    assert "dange_exam" in actions(menu(player=_p(current_city="丹阁", alchemy_level=0)))
    assert "dange_exam" not in actions(menu(player=_p(current_city="丹阁", alchemy_level=1)))


def test_角色面板_按钮随状态变化():
    v = ProfileView(FakeContext().author, can_breakthrough=False, is_cultivating=False, cog=None)
    assert actions(v) == ["cultivate", "back_to_menu"]
    v = ProfileView(FakeContext().author, can_breakthrough=True, is_cultivating=True, cog=None)
    assert actions(v) == ["cultivate", "stop", "breakthrough", "back_to_menu"]


def test_按钮数量不超过Discord上限(db):
    """一个面板最多 25 个按钮 —— 所有条件同时满足的最坏情况也不能超。"""
    v = menu(can_bt=True, player=_p(current_city="百草谷", party_id="P1"), city_players=[{"discord_id": "2"}])
    assert len(v.children) <= 25


# --- 按钮回调 -----------------------------------------------------------------

class FakeCog:
    """记录被调用的命令；`bot.cogs` 里按名字放别的假 cog。"""

    def __init__(self, **others):
        self.calls = []
        self.contexts = []
        self.bot = SimpleNamespace(cogs=others, get_context=self._get_context)

    async def _get_context(self, message):
        ctx = FakeContext(user_id=0)
        self.contexts.append(ctx)
        return ctx

    def __getattr__(self, name):
        if name.startswith("send_") or name in ("create_character",):
            async def rec(*a, **k):
                self.calls.append((name, a, k))
            return rec
        raise AttributeError(name)


class Recorder:
    """别的 cog 的命令替身：`await cog.explore(ctx)`。"""

    def __init__(self, *names):
        self.calls = []
        for n in names:
            setattr(self, n, self._make(n))

    def _make(self, name):
        async def rec(ctx, *a, **k):
            self.calls.append((name, ctx.author.id, a, k))
        return rec


def click_target(action, cog, uid=UID, **view_kw):
    view = SimpleNamespace(cog=cog, **view_kw)
    btn = MenuButton("x", discord.ButtonStyle.primary, action)
    btn._view = view
    i = FakeInteraction(uid)
    i.message = SimpleNamespace(id=555)
    i.client = object()
    return btn, i


async def click(action, cog=None, uid=UID, **view_kw):
    cog = cog or FakeCog()
    btn, i = click_target(action, cog, uid, **view_kw)
    await btn.callback(i)
    return i, cog


async def test_世界按钮_编辑原消息为世界总览():
    i, _ = await click("world")
    assert i.last.embed is not None and i.last.view is not None


async def test_移动按钮_编辑原消息为选择地区():
    i, _ = await click("travel")
    assert "选择地区" in i.last.embed.title


async def test_玩家按钮_同城没人时提示():
    i, _ = await click("city_players", _city_players=[], _player=None)
    assert "暂无其他修士" in i.last and i.last.ephemeral and i.last.view is None


async def test_玩家按钮_同城有人时展示列表():
    others = [{"discord_id": "2", "name": "乙", "realm": "炼气期1层", "cultivation": 0}]
    viewer = {"discord_id": UID, "realm": "炼气期1层", "cultivation": 0}
    i, _ = await click("city_players", _city_players=others, _player=viewer)
    assert i.last.ephemeral and i.last.view is not None and "同城修士" in i.last.embed.title


async def test_退出队伍按钮(db):
    await _add(db, party_id="P1")
    await _sql(db, "INSERT INTO parties (party_id, leader_id, city, created_at) VALUES ('P1', :u, '灵虚城', 0)", u=UID)
    i, _ = await click("party_leave")
    assert i.last.ephemeral and i.last.content


async def test_查看队伍_列出成员与队长(db):
    await _add(db, party_id="P1")
    await _add(db, "1002", party_id="P1")
    await _sql(db, "INSERT INTO parties (party_id, leader_id, city, created_at) VALUES ('P1', :u, '灵虚城', 0)", u=UID)
    i, _ = await click("party_info")
    e = i.last.embed
    assert i.last.ephemeral and "👑" in e.description and "道友1001" in e.description and "道友1002" in e.description


async def test_查看队伍_不在队伍中(db):
    await _add(db)
    i, _ = await click("party_info")
    assert "不在任何队伍" in i.last


async def test_查看队伍_队伍记录已不存在时不崩(db):
    """队伍被解散而玩家的 party_id 残留（或并发解散）：以前 fetchone() 为 None 直接 TypeError，点击显示『交互失败』。"""
    await _add(db, party_id="GHOST")
    i, _ = await click("party_info")
    assert i.last is not None and i.last.embed is not None                      # 有回应，不是静默失败
    assert "道友1001" in i.last.embed.description


@pytest.mark.parametrize("action,call", [
    ("profile", "send_profile"), ("breakthrough", "send_breakthrough"), ("stop", "send_stop"),
])
async def test_直接转给cog的按钮(db, action, call):
    i, cog = await click(action)
    assert i.response.deferred and [c[0] for c in cog.calls] == [call] and cog.calls[0][1] == (i,)


async def test_修炼按钮_拍卖进行中的万宝楼内被拒(db, monkeypatch):
    async def locked(uid):
        return True
    monkeypatch.setattr("utils.events.public.wanbao.is_auction_locked", locked)
    i, cog = await click("cultivate")
    assert "拍卖会进行中" in i.last and not cog.calls


async def test_修炼按钮_正常转给cog(db, monkeypatch):
    async def free(uid):
        return False
    monkeypatch.setattr("utils.events.public.wanbao.is_auction_locked", free)
    i, cog = await click("cultivate")
    assert [c[0] for c in cog.calls] == ["send_cultivate"]


async def test_创建角色按钮_用点击者作为作者(db):
    char = Recorder("create_character")
    cog = FakeCog(Character=char)
    i, _ = await click("create", cog, uid="777")
    assert char.calls == [("create_character", 777, (), {})]


@pytest.mark.parametrize("action,cog_name,method,unavailable", [
    ("explore", "Explore", "explore", "探险系统暂时不可用"),
    ("tavern", "Tavern", "tavern", "茶馆暂时不可用"),
    ("backpack", "Equipment", "backpack", "背包系统暂时不可用"),
    ("public_event", "PublicEvents", "show_active_event", "公共事件系统暂时不可用"),
    ("wanbao", "PublicEvents", "wanbao", "万宝楼系统暂时不可用"),
])
async def test_转给其他cog的按钮_以点击者身份调用_缺失时提示(db, action, cog_name, method, unavailable):
    rec = Recorder(method)
    i, _ = await click(action, FakeCog(**{cog_name: rec}), uid="777")
    assert rec.calls == [(method, 777, (), {})]

    i, _ = await click(action, FakeCog())
    assert unavailable in i.last and i.last.ephemeral


async def test_加入宗门按钮_带上宗门名(db):
    rec = Recorder("join_sect")
    await click("join_sect:御剑阁", FakeCog(Sect=rec), uid="777")
    assert rec.calls == [("join_sect", 777, (), {"name": "御剑阁"})]

    i, _ = await click("join_sect:御剑阁", FakeCog())
    assert "宗门系统暂时不可用" in i.last


async def test_回调出错时回复出错了而不是静默(db):
    class Boom(FakeCog):
        async def send_profile(self, interaction):
            raise RuntimeError("炸了")
    i, _ = await click("profile", Boom())
    assert "出错了：炸了" in i.last and i.last.ephemeral


async def test_城市按钮_编辑原消息为城市菜单(db):
    await _add(db)
    i, _ = await click("city")
    assert i.edited and i.edited[-1].view is not None


async def test_功法按钮(db):
    await _add(db)
    i, _ = await click("techniques")
    assert i.last.embed is not None and i.last.view is not None

    i, _ = await click("techniques", uid="999")
    assert "尚未踏入修仙之路" in i.last


async def test_装备按钮_编辑原消息(db):
    await _add(db)
    i, _ = await click("equipment")
    assert i.edited and i.edited[-1].view is not None


async def test_技艺按钮_编辑原消息(db):
    i, _ = await click("crafting")
    assert i.edited and i.edited[-1].view is not None


# --- 采集按钮 -----------------------------------------------------------------

async def test_采集按钮_空闲时给出时长选择(db):
    await _add(db, current_city="百草谷")
    i, _ = await click("gather:采药")
    assert "采药" in i.last.embed.title and "百草谷" in i.last.embed.title
    assert i.last.view is not None and not i.last.ephemeral


@pytest.mark.parametrize("fields,text_", [
    (dict(cultivating_until=time.time() + 3600), "正在闭关"),
    (dict(gathering_until=time.time() + 3600), "正在采集"),
])
async def test_采集按钮_闭关或采集中被拒(db, fields, text_):
    await _add(db, current_city="百草谷", **fields)
    i, _ = await click("gather:采药")
    assert text_ in i.last and i.last.ephemeral and i.last.view is None


async def test_采集按钮_闭关已结束不算占用(db):
    await _add(db, current_city="百草谷", cultivating_until=time.time() - 10, gathering_until=time.time() - 10)
    i, _ = await click("gather:采药")
    assert i.last.view is not None


async def test_采集按钮_守城期间被拒(db):
    await _add(db, current_city="百草谷")
    await _event(db, "active")
    await _sql(db, "INSERT INTO public_event_participants (event_id, discord_id, activity, joined_at) "
                   "SELECT event_id, :u, 'defense', 0 FROM public_events", u=UID)
    i, _ = await click("gather:采药")
    assert "守城期间" in i.last and i.last.ephemeral


async def test_采集按钮_拍卖进行中被拒(db, monkeypatch):
    await _add(db, current_city="百草谷")

    async def locked(uid):
        return True
    monkeypatch.setattr("utils.events.public.wanbao.is_auction_locked", locked)
    i, _ = await click("gather:采药")
    assert "拍卖会进行中" in i.last


async def test_采集按钮_没有角色时给出明确提示而不是出错了(db):
    """没有角色的人点（比如菜单是别人发的 / 角色已被删）：以前 player 为 None → TypeError → 『出错了：'NoneType'…』。"""
    i, _ = await click("gather:采药", uid="999")
    assert "尚未踏入修仙之路" in i.last and i.last.ephemeral


@pytest.mark.parametrize("action", ["city", "equipment", "party_info"])
async def test_没有角色时点城市_装备_队伍_给出明确提示(db, action):
    i, _ = await click(action, uid="999")
    assert i.last is not None and "出错了" not in (i.last.content or "")
    assert i.last.ephemeral


# --- 丹阁考核 -----------------------------------------------------------------

async def test_丹阁考核_已是炼丹师(db):
    await _add(db, alchemy_level=1, fortune=5, soul=5)
    i, _ = await click("dange_exam")
    assert "已经是炼丹师" in i.last


async def test_丹阁考核_机缘神识不足(db):
    await _add(db, fortune=2, soul=5)
    i, _ = await click("dange_exam")
    assert "各需达到" in i.last and "机缘 2 / 神识 5" in i.last


async def test_丹阁考核_未缴费时展示规则(db):
    await _add(db, fortune=5, soul=5)
    i, _ = await click("dange_exam")
    e = i.edited[-1].embed
    assert "炼丹师考核" in e.title and any(f.name == "考核规则" for f in e.fields)


async def test_丹阁考核_已缴费不再展示收费规则(db):
    await _add(db, fortune=5, soul=5, exam_attempts_left=1)
    i, _ = await click("dange_exam")
    assert not any(f.name == "考核规则" for f in i.edited[-1].embed.fields)


# --- 返回主菜单 ---------------------------------------------------------------

async def test_返回主菜单_有角色(db):
    await _add(db)
    await _add(db, "1002")
    i, _ = await click("back_to_menu")
    msg = i.last
    assert isinstance(msg.view, MainMenuView) and msg.embed.title == "✦ 修仙长生路 ✦"
    assert "city_players" in actions(msg.view)                                  # 同城的 1002


async def test_返回主菜单_同城只有自己和死人时没有玩家按钮(db):
    await _add(db)
    await _add(db, "1002", is_dead=1)
    i, _ = await click("back_to_menu")
    assert "city_players" not in actions(i.last.view)


async def test_返回主菜单_没有角色给创建按钮(db):
    i, _ = await click("back_to_menu", uid="999")
    assert actions(i.last.view)[0] == "create"


async def test_返回主菜单_已坐化视为没有角色(db):
    await _add(db, is_dead=1)
    i, _ = await click("back_to_menu")
    assert actions(i.last.view)[0] == "create"


async def test_返回主菜单_识别双修功法(db):
    await _add(db, techniques=json.dumps(["双修功法"], ensure_ascii=False))
    i, _ = await click("back_to_menu")
    assert "双修系统" in i.last.embed.description

    await _add(db, "1002", techniques=json.dumps([{"name": "双修功法"}], ensure_ascii=False))
    i, _ = await click("back_to_menu", uid="1002")
    assert "双修系统" in i.last.embed.description


async def test_返回主菜单_先结算流逝的寿元(db):
    await _add(db, last_active=time.time() - 3600 * 20)                         # 现实 20 小时 = 10 游戏年
    before = 100
    await click("back_to_menu")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        row = await s.get(D.Player, UID)
    assert row.lifespan < before


async def test_返回主菜单_不结算已坐化玩家的时间(db):
    old = time.time() - 3600 * 20
    await _add(db, is_dead=1, last_active=old)
    await click("back_to_menu")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, UID)).last_active == pytest.approx(old)


async def test_事件提示_读库成功后写入缓存(db):
    await _event(db, "active", "灵雨")
    hint = _get_event_hint()
    assert menu_mod._event_hint_cache[1] == hint
