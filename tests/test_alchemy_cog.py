"""炼丹命令（cogs/alchemy.py）。炼丹本身与面板见 test_alchemy.py。

B45 —— 『今日剩余次数 / 今日次数』直接读 `alchemy_daily_count`，不看 `alchemy_daily_reset` 是不是今天：
  昨天炼满 6 次的人，今天打开炼丹台仍显示『剩余 0/6』，其实配额早已重置（`claim_daily_quota` 跨日归零）。
B46 —— 提示里写『请先使用 `开始` 创建角色』，真正的命令叫 `创建角色`。
B47 —— `调试炼丹` 会改玩家的炼丹品级，却没像 `重置炼丹次数` 那样写审计日志。
B48 —— `add_alchemy_exp`（utils/alchemy.py）是读 → 改 → 写回：并发炼丹丢经验（与 B42 同类）。
"""

import asyncio
import re
import time
from pathlib import Path

import pytest

from cogs.alchemy import AlchemyCog
from tests.conftest import make_player
from tests.discord_fakes import FakeContext
from utils import alchemy as al
from utils.alchemy import ALCHEMY_EXP_THRESHOLDS, DAILY_LIMIT, RECIPES, add_alchemy_exp
from utils.views.alchemy import AlchemyMainView

U = "1001"
MASTER = "304758476448595970"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cog():
    return AlchemyCog(bot=None)


async def _add(db, uid=U, stones=0, **kw):
    D = db["db_async"]
    p = make_player(D, uid, stones=stones)
    p.name = f"道友{uid}"
    for k, v in kw.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def row(db, uid=U):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


def ctx(uid=U):
    return FakeContext(user_id=uid)


async def run(cog, name, c, *args):
    return await getattr(cog, name).callback(cog, c, *args)


# --- 炼丹台 -------------------------------------------------------------------

async def test_炼丹_没有角色_已坐化_未入门(db, cog):
    c = ctx()
    await run(cog, "alchemy", c)
    assert c.said("你还没有角色")
    await _add(db, is_dead=1, alchemy_level=2)
    c = ctx()
    await run(cog, "alchemy", c)
    assert c.said("已坐化")
    await _add(db, "1002", alchemy_level=0)
    c = ctx("1002")
    await run(cog, "alchemy", c)
    assert c.said("尚未入门炼丹") and c.said("学炼丹")


async def test_炼丹_没有可用丹方(db, cog, monkeypatch):
    await _add(db, alchemy_level=1)
    monkeypatch.setattr("cogs.alchemy.list_available_recipes", lambda lvl: [])
    c = ctx()
    await run(cog, "alchemy", c)
    assert c.said("没有可用丹方")


async def test_炼丹_打开炼丹台(db, cog):
    await _add(db, alchemy_level=3, alchemy_daily_count=2, alchemy_daily_reset=time.time())
    c = ctx()
    await run(cog, "alchemy", c)
    assert isinstance(c.last.view, AlchemyMainView)
    assert "3 品" in c.last.content and f"{DAILY_LIMIT - 2}/{DAILY_LIMIT}" in c.last.content


async def test_B45_昨天的次数不算今天(db, cog):
    await _add(db, alchemy_level=3, alchemy_daily_count=DAILY_LIMIT, alchemy_daily_reset=time.time() - 2 * 86400)
    c = ctx()
    await run(cog, "alchemy", c)
    assert f"{DAILY_LIMIT}/{DAILY_LIMIT}" in c.last.content and f"0/{DAILY_LIMIT}" not in c.last.content


async def test_炼丹_次数用尽显示0(db, cog):
    await _add(db, alchemy_level=3, alchemy_daily_count=DAILY_LIMIT, alchemy_daily_reset=time.time())
    c = ctx()
    await run(cog, "alchemy", c)
    assert f"0/{DAILY_LIMIT}" in c.last.content


# --- 学炼丹 / 信息 ------------------------------------------------------------

async def test_学炼丹(db, cog):
    c = ctx()
    await run(cog, "learn_alchemy", c)
    assert c.said("你还没有角色")
    await _add(db, alchemy_level=0)
    c = ctx()
    await run(cog, "learn_alchemy", c)
    assert c.said("丹阁") and c.said("500 灵石") and c.said("3 次机会")
    await _add(db, "1002", alchemy_level=4)
    c = ctx("1002")
    await run(cog, "learn_alchemy", c)
    assert c.said("已经是 4 品炼丹师")


async def test_炼丹信息(db, cog):
    c = ctx()
    await run(cog, "alchemy_info", c)
    assert c.said("你还没有角色")
    await _add(db, alchemy_level=0)
    c = ctx()
    await run(cog, "alchemy_info", c)
    assert c.said("尚未入门炼丹")

    await _add(db, "1002", alchemy_level=2, alchemy_exp=60, alchemy_daily_count=3, alchemy_daily_reset=time.time())
    c = ctx("1002")
    await run(cog, "alchemy_info", c)
    f = {x.name: x.value for x in c.last.embed.fields}
    assert f["炼丹师品级"] == "2 品" and f["炼丹经验"] == f"60 / {ALCHEMY_EXP_THRESHOLDS[3]}" and f["今日次数"] == f"3/{DAILY_LIMIT}"
    assert any(k.startswith("可炼丹药（") for k in f)


async def test_炼丹信息_满级显示已满级(db, cog):
    await _add(db, alchemy_level=9, alchemy_exp=9999)
    c = ctx()
    await run(cog, "alchemy_info", c)
    assert "（已满级）" in next(f.value for f in c.last.embed.fields if f.name == "炼丹经验")


async def test_B45_炼丹信息_昨天的次数不算今天(db, cog):
    await _add(db, alchemy_level=2, alchemy_daily_count=5, alchemy_daily_reset=time.time() - 3 * 86400)
    c = ctx()
    await run(cog, "alchemy_info", c)
    assert next(f.value for f in c.last.embed.fields if f.name == "今日次数") == f"0/{DAILY_LIMIT}"


# --- 熟练度 / 丹方 ------------------------------------------------------------

async def test_熟练度(db, cog):
    c = ctx()
    await run(cog, "alchemy_mastery", c)
    assert c.said("尚未入门炼丹")
    await _add(db, alchemy_level=1)
    c = ctx()
    await run(cog, "alchemy_mastery", c)
    assert c.said("还没有炼制过")
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add_all([D.AlchemyMastery(discord_id=U, pill_name="聚气丸", count=3),
                   D.AlchemyMastery(discord_id=U, pill_name="筑基丹", count=40)])
        await s.commit()
    c = ctx()
    await run(cog, "alchemy_mastery", c)
    lines = c.last.embed.description.splitlines()
    assert lines[0].startswith("• 筑基丹") and "40 次" in lines[0] and lines[1].startswith("• 聚气丸")


async def test_丹方查询(db, cog):
    c = ctx()
    await run(cog, "recipe_lookup", c)
    assert c.said("尚未入门炼丹")
    await _add(db, alchemy_level=1)
    c = ctx()
    await run(cog, "recipe_lookup", c)
    assert c.said("还没有掌握任何丹方")

    rid = RECIPES[0]["recipe_id"]
    await al.unlock_recipe(U, rid, [0])
    c = ctx()
    await run(cog, "recipe_lookup", c)
    e = c.last.embed
    assert "已掌握 1 个丹方" in e.description and e.fields[0].name == RECIPES[0]["name"]
    assert "主药：灵芝草×2" in e.fields[0].value and "调和辅药" in e.fields[0].value


async def test_丹方查询_跳过已不存在的丹方(db, cog):
    await _add(db, alchemy_level=1)
    await al.unlock_recipe(U, "已删除的丹方")
    await al.unlock_recipe(U, RECIPES[0]["recipe_id"])
    c = ctx()
    await run(cog, "recipe_lookup", c)
    assert len(c.last.embed.fields) == 1


# --- 管理员 -------------------------------------------------------------------

async def test_非管理员命令什么都不做(db, cog):
    await _add(db, alchemy_level=2, alchemy_daily_count=4)
    for name, args in (("debug_alchemy", (7,)), ("reset_alchemy_count", ()), ("reset_alchemy", ())):
        c = ctx(U)
        await run(cog, name, c, *args)
        assert c.messages == []
    p = await row(db)
    assert p.alchemy_level == 2 and p.alchemy_daily_count == 4


async def test_调试炼丹_设置品级并留审计(db, cog, caplog):
    await _add(db, MASTER, alchemy_level=0, alchemy_exp=99, alchemy_daily_count=5)
    c = ctx(MASTER)
    with caplog.at_level("WARNING", logger="mischicat.audit"):
        await run(cog, "debug_alchemy", c, 7)
    p = await row(db, MASTER)
    assert (p.alchemy_level, p.alchemy_exp, p.alchemy_daily_count) == (7, 0, 0) and c.said("7 品")
    assert any("debug_alchemy" in r.getMessage() for r in caplog.records)           # B47


async def test_调试炼丹_默认5品(db, cog):
    await _add(db, MASTER)
    await run(cog, "debug_alchemy", ctx(MASTER))
    assert (await row(db, MASTER)).alchemy_level == 5


async def test_重置炼丹次数(db, cog, caplog):
    await _add(db, MASTER, alchemy_daily_count=5)
    c = ctx(MASTER)
    with caplog.at_level("WARNING", logger="mischicat.audit"):
        await run(cog, "reset_alchemy_count", c)
    assert (await row(db, MASTER)).alchemy_daily_count == 0 and c.said("已重置")
    assert any("reset_alchemy_count" in r.getMessage() for r in caplog.records)


async def test_重置炼丹_清空全部炼丹数据_只动目标(db, cog, caplog):
    await _add(db, MASTER)
    await _add(db, U, alchemy_level=4, alchemy_exp=200, alchemy_daily_count=3, exam_attempts_left=2)
    await _add(db, "1002", alchemy_level=4)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add_all([D.KnownRecipe(discord_id=U, recipe_id="r1", aux_choices="[]"),
                   D.KnownRecipe(discord_id="1002", recipe_id="r1", aux_choices="[]"),
                   D.AlchemyMastery(discord_id=U, pill_name="聚气丸", count=3),
                   D.AlchemyMastery(discord_id="1002", pill_name="聚气丸", count=3)])
        await s.commit()
    c = ctx(MASTER)
    with caplog.at_level("WARNING", logger="mischicat.audit"):
        await run(cog, "reset_alchemy", c, U)
    p = await row(db)
    assert (p.alchemy_level, p.alchemy_exp, p.alchemy_daily_count, p.exam_attempts_left) == (0, 0, 0, 0)
    assert await al.get_known_recipes(U) == set() and await al.get_mastery_count(U, "聚气丸") == 0
    assert (await row(db, "1002")).alchemy_level == 4
    assert await al.get_known_recipes("1002") == {"r1"} and await al.get_mastery_count("1002", "聚气丸") == 3
    assert any("reset_alchemy" in r.getMessage() for r in caplog.records) and c.said(U)


async def test_重置炼丹_默认重置自己_找不到玩家(db, cog):
    await _add(db, MASTER, alchemy_level=3)
    await run(cog, "reset_alchemy", ctx(MASTER))
    assert (await row(db, MASTER)).alchemy_level == 0
    c = ctx(MASTER)
    await run(cog, "reset_alchemy", c, "999999")
    assert c.said("找不到该玩家")


# --- 文案对账 -----------------------------------------------------------------

def _real_command_names() -> set[str]:
    names = set()
    for path in (ROOT / "cogs").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        for deco in re.findall(r"@commands\.(?:hybrid_)?command\((.*?)\)\s*\n", src):
            names.update(re.findall(r'name="([^"]+)"', deco))
            for al_ in re.findall(r"aliases=\[(.*?)\]", deco):
                names.update(re.findall(r'"([^"]+)"', al_))
    return names


def test_B46_炼丹提示里引用的命令都真实存在():
    """提示文字是手写的，命令改名后不会自己更新 —— 玩家照着输会得到『找不到命令』。"""
    src = (ROOT / "cogs" / "alchemy.py").read_text(encoding="utf-8")
    real = _real_command_names()
    assert len(real) > 50
    from utils.config import COMMAND_PREFIX
    mentioned = set(re.findall(r"`\{COMMAND_PREFIX\}([^`\s]+)`", src))
    assert mentioned, "扫描不到提示里的命令，守卫失效了"
    assert not (mentioned - real), f"提示里引用了不存在的命令：{mentioned - real}（前缀 {COMMAND_PREFIX}）"


# --- 炼丹经验 -----------------------------------------------------------------

async def test_炼丹经验_升级与封顶(db):
    await _add(db, alchemy_level=1, alchemy_exp=0)
    assert await add_alchemy_exp(U, ALCHEMY_EXP_THRESHOLDS[2] - 1) == (1, ALCHEMY_EXP_THRESHOLDS[2] - 1, False)
    assert await add_alchemy_exp(U, 1) == (2, ALCHEMY_EXP_THRESHOLDS[2], True)
    await _add(db, "1002", alchemy_level=9, alchemy_exp=2500)
    assert await add_alchemy_exp("1002", 9999) == (9, 12_499, False)
    assert await add_alchemy_exp("nope", 5) == (0, 0, False)


async def test_B48_并发加炼丹经验不丢更新(db):
    await _add(db, alchemy_level=1, alchemy_exp=0)
    await asyncio.gather(*[add_alchemy_exp(U, 3) for _ in range(12)])
    assert (await row(db)).alchemy_exp == 36


async def test_熟练度_与丹方查询_未入门的玩家都被拒(db, cog):
    await _add(db, alchemy_level=0)
    for name in ("alchemy_mastery", "recipe_lookup"):
        c = ctx()
        await run(cog, name, c)
        assert c.said("尚未入门炼丹"), name
