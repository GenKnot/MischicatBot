"""机器人修士（U1「江湖百态」）的前置护栏。

机器人是 `players` 里 `is_bot = 1` 的普通行，`discord_id` 以 `bot_` 开头。要保证：
· 迁移给老库补上 `is_bot`（默认 0，老玩家都是真人）；
· 私信一律走 `send_dm`：机器人没有 Discord 账号，不 fetch_user；
· 组队 / 双修（会复制奖励、给修为捷径）对机器人拒绝；转账给机器人允许（`BOT_CAPABILITIES`）；
· 只该给真人的查询（天降灵雨的『袖手旁观者』寿元惩罚）排除机器人；
· 静态棘轮：每个『遍历全体玩家』的查询点都登记了类别，新增一处会红（见 TRAVERSALS）。
"""

import os
import re
import sqlite3
import subprocess
import sys
import time
import types
from pathlib import Path

import discord
import pytest

from cogs.cultivation import CultivationCog
from tests.conftest import make_player
from utils import bank, bots, dual_cultivation_logic as dual, party
from utils.bots import BOT_CAPABILITIES, bot_refusal, is_bot_id, send_dm
from utils.events.public import spirit_rain

ROOT = Path(__file__).resolve().parent.parent
HUMAN, BOT = "123456", "bot_00001"


class _User:
    def __init__(self):
        self.sent = []

    async def send(self, *a, **k):
        self.sent.append((a, k))


class _Client:
    def __init__(self, exc=None):
        self.fetched, self.users, self.exc = [], {}, exc

    async def fetch_user(self, uid):
        self.fetched.append(uid)
        if self.exc:
            raise self.exc
        return self.users.setdefault(uid, _User())


def _http(cls):
    return cls(types.SimpleNamespace(status=403, reason="x"), "x")


async def _add(db, uid, city="灵虚城", **kw):
    D = db["db_async"]
    p = make_player(D, uid)
    p.name, p.current_city = f"道友{uid}", city
    p.is_bot = uid.startswith("bot_")
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


# ---- 迁移 -------------------------------------------------------------------

def test_迁移给老库补_is_bot_默认零(tmp_path):
    """老库没有这一列：upgrade 之后补上，已有玩家都是真人（0）。"""
    path = tmp_path / "old.db"
    env = dict(os.environ, DB_PATH=str(path))

    def alembic(*a):
        return subprocess.run([sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *a],
                              cwd=ROOT, env=env, capture_output=True, text=True)

    assert alembic("upgrade", "2bc9369e4fc7").returncode == 0
    conn = sqlite3.connect(path)
    # 基线按当前 ORM 建表，已经带 is_bot：模拟真正的老库，把它拿掉
    conn.execute("ALTER TABLE players DROP COLUMN is_bot")
    conn.execute("INSERT INTO players (discord_id, name, gender, spirit_root, spirit_root_type, comprehension, "
                 "physique, fortune, bone, soul, lifespan, lifespan_max, created_at, last_active) "
                 "VALUES ('1','甲','男','金','单灵根',5,5,5,5,5,100,100,0,0)")
    conn.commit()
    conn.close()

    assert alembic("upgrade", "head").returncode == 0

    conn = sqlite3.connect(path)
    assert conn.execute("SELECT is_bot FROM players WHERE discord_id='1'").fetchone() == (0,)
    conn.close()
    assert alembic("upgrade", "head").returncode == 0     # 幂等


# ---- 识别 / 私信 ------------------------------------------------------------

def test_机器人ID识别():
    assert is_bot_id("bot_00001") and is_bot_id("bot_x")
    assert not is_bot_id("123456") and not is_bot_id("") and not is_bot_id("abot_1")


async def test_send_dm_给真人发_给机器人不发():
    c = _Client()
    assert await send_dm(c, HUMAN, "hi", embed=1) is True
    assert c.users[int(HUMAN)].sent == [(("hi",), {"embed": 1})]
    c2 = _Client()
    assert await send_dm(c2, BOT, "hi") is False
    assert c2.fetched == [], "机器人没有 Discord 账号，不该去 fetch_user"


@pytest.mark.parametrize("exc", [_http(discord.Forbidden), _http(discord.NotFound)])
async def test_send_dm_对方关了私信是常态_返回False(exc):
    assert await send_dm(_Client(exc), HUMAN, "hi") is False


async def test_send_dm_其余异常不吞():
    """B5：自己代码的 bug 不能被私信旁路吞成 debug。"""
    with pytest.raises(RuntimeError):
        await send_dm(_Client(RuntimeError("boom")), HUMAN, "hi")


# ---- 互动边界 ---------------------------------------------------------------

def test_互动总开关默认全开():
    """组队 / 双修能不能约由好感度决定（见 test_bot_social.py），总开关只是应急用。"""
    assert BOT_CAPABILITIES == {"party": True, "dual": True, "receive_transfer": True}


def test_bot_refusal_只看总开关(monkeypatch):
    assert bot_refusal("party", HUMAN, BOT) is None
    monkeypatch.setitem(BOT_CAPABILITIES, "party", False)
    monkeypatch.setitem(BOT_CAPABILITIES, "dual", False)
    assert bot_refusal("party", HUMAN, "1") is None, "没有机器人参与就不受开关影响"
    assert "组队" in bot_refusal("party", HUMAN, BOT)
    assert "双修" in bot_refusal("dual", BOT, HUMAN)
    assert bot_refusal("receive_transfer", HUMAN, BOT) is None


async def test_组队_机器人好感不够被拒_且不建队(db):
    await _add(db, HUMAN)
    await _add(db, BOT)
    for a, b in [(HUMAN, BOT), (BOT, HUMAN)]:
        res = await party.accept_invite(a, b)
        assert res["ok"] is False and "组队" in res["reason"]
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, HUMAN)).party_id is None
        assert (await s.get(D.Player, BOT)).party_id is None


async def test_add_to_party_机器人好感不够被拒(db):
    await _add(db, HUMAN)
    await _add(db, BOT)
    pid = await party.create_party(HUMAN, "灵虚城")
    assert await party.add_to_party(pid, BOT) is False


async def test_双修_机器人好感不够被拒(db):
    await _add(db, HUMAN)
    await _add(db, BOT)
    assert (await dual.check_dual_requirements(HUMAN, BOT))["success"] is False
    res = await dual.start_dual_cultivation(HUMAN, BOT)
    assert res["success"] is False and "双修" in res["message"]
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, HUMAN)).dual_partner_id is None


async def test_转账给机器人允许(db):
    await _add(db, HUMAN, spirit_stones=100_000)
    await _add(db, BOT, spirit_stones=0)
    res = await bank.transfer(HUMAN, BOT, 1000)
    assert res["ok"] is True
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.Player, BOT)).spirit_stones == 1000


# ---- 通知 -------------------------------------------------------------------

async def test_闭关结算_机器人入账但不私信(db):
    await _add(db, BOT, cultivating_years=4, cultivating_until=time.time() - 1, cultivation=0)
    client = _Client()
    cog = CultivationCog(bot=types.SimpleNamespace(fetch_user=client.fetch_user))

    await cog._cultivation_notifier.coro(cog)

    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, BOT)
        assert p.cultivating_until is None and p.cultivation > 0
    assert client.fetched == []


async def test_解散队伍_不给机器人发私信(db):
    from utils.views.party import disband_party_func
    await _add(db, HUMAN)
    await _add(db, BOT)
    D = db["db_async"]
    pid = await party.create_party(HUMAN, "灵虚城")
    async with D.AsyncSessionLocal() as s:                  # 机器人入队走开关打开的路径
        (await s.get(D.Player, BOT)).party_id = pid
        await s.commit()
    client = _Client()
    await disband_party_func(HUMAN, client)
    assert client.fetched == []


# ---- 只给真人的查询 ---------------------------------------------------------

async def test_天降灵雨_袖手旁观者不含机器人(db):
    await _add(db, HUMAN)
    await _add(db, BOT)
    ids = {p["discord_id"] for p in await spirit_rain._get_idle_in_city("灵虚城", set())}
    assert ids == {HUMAN}


# ---- 静态棘轮 ---------------------------------------------------------------

REAL_ONLY, INCLUDE_BOTS = "REAL_ONLY", "INCLUDE_BOTS"

# 文件 -> {类别: 个数}，数的是『FROM players』/『select(Player)』且不是按主键取单行的查询点。
# 类别按查询语句里有没有 `is_bot = 0` 自动判定：
#   REAL_ONLY    —— 查询自己排除了机器人（灵雨的寿元惩罚、Web 总览的真人统计……）
#   INCLUDE_BOTS —— 没排除：机器人本来就该参与（同城列表、队伍、结算、排行榜带标记、Web 人口统计……）
#                   以及由参数 / 变量决定的动态过滤（Web 修士列表 / 属性榜的「含机器人」开关）
# 新增 / 删除一处遍历点会让数字对不上：看一眼它该是哪一类，再改这张表；
# 把 REAL_ONLY 的过滤删掉，它会变成 INCLUDE_BOTS，同样会红。
TRAVERSALS = {
    "utils/events/public/spirit_rain.py": {REAL_ONLY: 1},
    "utils/bot_events.py": {INCLUDE_BOTS: 1},
    "utils/bot_chatter.py": {INCLUDE_BOTS: 1},          # 道贺：按熟人 ID 列表取在世的机器人，不是全表遍历
    "utils/bot_ambush.py": {INCLUDE_BOTS: 2},           # 拦路：按 ID 取玩家 / 同伴的名字；组团时取拦路者亲友和同城路人，不是全表遍历
    "utils/bot_grudges.py": {INCLUDE_BOTS: 1},          # on_offense 里按 ID 列表取关系网上的人（受害者的朋友们），不是全表遍历
    "cogs/cultivation.py": {INCLUDE_BOTS: 4},
    "cogs/tavern.py": {INCLUDE_BOTS: 1},
    "cogs/explore.py": {INCLUDE_BOTS: 1},
    "utils/quest_logic.py": {INCLUDE_BOTS: 5},
    "utils/party.py": {INCLUDE_BOTS: 3},
    "utils/views/cultivation.py": {INCLUDE_BOTS: 1},
    "utils/views/world.py": {INCLUDE_BOTS: 1},
    "utils/views/city.py": {INCLUDE_BOTS: 1},
    "utils/views/menu.py": {INCLUDE_BOTS: 1},
    "utils/views/techniques.py": {INCLUDE_BOTS: 1},
    "utils/views/spirit_rain.py": {INCLUDE_BOTS: 1},
    "utils/views/leaderboard.py": {INCLUDE_BOTS: 6},
    "web/main.py": {REAL_ONLY: 12, INCLUDE_BOTS: 8},      # /players、/stats 的「含机器人」开关写成参数化的 (? OR is_bot = 0)，城市下拉按开关各一条常量 SQL
}
_PATTERN = re.compile(r"FROM players\b|select\(Player\)", re.I)
# 按主键取单行（WHERE discord_id = …）不算遍历
_BY_KEY = re.compile(r"WHERE\s+(?:p\.)?discord_id\s*=|Player\.discord_id\s*==|discord_id\s+IN\b", re.I)
_REAL_FILTER = re.compile(r"is_bot\s*=\s*0|real_player\(\)")


def _scan():
    found = {}
    for sub in ("cogs", "utils", "web"):
        for f in sorted((ROOT / sub).rglob("*.py")):
            if f.name == "bots.py":
                continue
            src, kinds = f.read_text(), {}
            for m in _PATTERN.finditer(src):
                window = re.split(r'"""|"\s*(?:[),]|\n)', src[m.start():m.start() + 400])[0]     # 到这条语句的字符串结束为止
                if _BY_KEY.search(window):
                    continue
                kind = REAL_ONLY if _REAL_FILTER.search(window) else INCLUDE_BOTS
                kinds[kind] = kinds.get(kind, 0) + 1
            if kinds:
                found[str(f.relative_to(ROOT))] = kinds
    return found


def test_遍历全体玩家的查询点都登记了类别():
    found = _scan()
    assert found == TRAVERSALS, (
        "遍历 players 的查询点变了：请决定它属于 REAL_ONLY / INCLUDE_BOTS，并更新 TRAVERSALS。\n"
        f"多出/变化：{ {k: v for k, v in found.items() if TRAVERSALS.get(k) != v} }\n"
        f"少了：{ [k for k in TRAVERSALS if k not in found] }")


def test_REAL_ONLY_的查询确实排除了机器人():
    """自动判定的类别要和登记的一致：登记了 REAL_ONLY 的文件，每一处都带着 `is_bot = 0`。"""
    found = _scan()
    for path, kinds in TRAVERSALS.items():
        assert found[path].get(REAL_ONLY, 0) == kinds.get(REAL_ONLY, 0), path


# 唯一允许直接 fetch_user 的地方：双修邀请要的是 User 对象（用来 @ 对方、做按钮归属），不是发私信；
# 它前面有 bot_refusal("dual")，机器人到不了这里。
FETCH_USER_ALLOWED = {"utils/views/combat.py"}


def test_不再直接_fetch_user():
    """私信统一走 send_dm（机器人没有 Discord 账号）。"""
    bad = [str(f.relative_to(ROOT)) for sub in ("cogs", "utils") for f in (ROOT / sub).rglob("*.py")
           if f.name != "bots.py" and ".fetch_user(" in f.read_text()
           and str(f.relative_to(ROOT)) not in FETCH_USER_ALLOWED]
    assert bad == [], f"这些文件还在直接 fetch_user：{bad}"

