"""统一设置（utils/settings_hub.py、cogs/tuning.py）：管理员在游戏里调数字，文件里的是默认值；调不坏、重启不丢、能恢复。"""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from cogs import tuning
from tests.discord_fakes import FakeContext
from utils import bot_feuds, rumors, world_settings
from utils import settings_hub as hub


@pytest.fixture(autouse=True)
async def clean_hub():
    hub._overrides.clear()
    for n in hub.REGISTRY:
        hub.reload_module(n)
    yield
    hub._overrides.clear()
    for n in hub.REGISTRY:
        hub.reload_module(n)


# ---- 纯函数 -----------------------------------------------------------------

def test_叶子只含数字和开关_跳过说明和文字():
    cfg = {"_说明": "x", "a": 1, "b": {"c": 0.5, "d": [1, 2], "e": "文字", "f": True, "g": None}}
    assert dict(hub.leaves(cfg)) == {"a": 1, "b.c": 0.5, "b.d.0": 1, "b.d.1": 2, "b.f": True}


def test_叠加覆盖值_路径对不上的忽略_文字不能被覆盖():
    cfg = {"a": 1, "b": {"c": 2, "d": [5, 6]}, "t": "文"}
    hub.apply(cfg, {"a": 9, "b.c": 3, "b.d.1": 7, "nope.x": 1, "t": 5, "b.d.9": 1})
    assert cfg == {"a": 9, "b": {"c": 3, "d": [5, 7]}, "t": "文"}


@pytest.mark.parametrize("raw,default,expect", [
    ("5", 1, 5), ("0.25", 0.5, 0.25), ("3", 0.5, 3.0), ("2.5", 1, 2.5), ("开", False, True), ("关", True, False), (" true ", False, True),
])
def test_解析输入(raw, default, expect):
    v, err = hub.parse(raw, default)
    assert err is None and v == expect and type(v) is type(expect)


@pytest.mark.parametrize("raw,default", [("abc", 1), ("", 1), ("nan", 1), ("1e99", 1), ("也许", False), ("2", True)])
def test_解析输入_坏值(raw, default):
    assert hub.parse(raw, default)[1]


def test_文件名简写():
    assert hub.resolve("bot_feuds.json") == "bot_feuds.json" and hub.resolve("bot_feuds") == "bot_feuds.json"
    assert hub.resolve("feuds") == "bot_feuds.json"
    assert hub.resolve("bot") is None, "多个都含 bot，不猜"
    assert hub.resolve("") is None and hub.resolve("不存在") is None


def test_所有注册的文件默认值都通过自己的校验_且至少有可调项():
    for name in hub.REGISTRY:
        cfg = hub.defaults(name)
        assert hub.validate(name, cfg) == [], name
        assert sum(1 for _ in hub.leaves(cfg)) > 0, name


def test_每个模块都走统一入口读配置():
    """静态棘轮：data/ 下登记的配置，模块必须用 settings_hub.read 读，否则调参不生效。"""
    import importlib
    import re
    from pathlib import Path
    for name, (mod, _fn) in hub.REGISTRY.items():
        src = Path(importlib.import_module(mod).__file__).read_text(encoding="utf-8")
        assert re.search(r"settings_hub\.read\(", src), f"{mod} 没有走 settings_hub.read"


# ---- 设置 / 恢复 -------------------------------------------------------------

async def test_设置_立即生效_并带校验(db):
    default = bot_feuds.load()["kill"]["cap"]
    ok, msg = await hub.set_value("bot_feuds.json", "kill.cap", "999")
    assert ok and "→ 999" in msg
    assert bot_feuds.load()["kill"]["cap"] == 999 != default
    assert hub.entries("bot_feuds.json", "kill.cap")[0] == {"path": "kill.cap", "default": default, "value": 999, "changed": True}


async def test_设置_开关和小数(db):
    assert (await hub.set_value("bot_feuds.json", "kill_enabled", "关"))[0] and bot_feuds.load()["kill_enabled"] is False
    assert (await hub.set_value("bot_feuds.json", "tie_chance", "0.5"))[0] and bot_feuds.load()["tie_chance"] == 0.5
    assert (await hub.set_value("bot_feuds.json", "outcomes.by_archetype.豪爽.击杀", "99"))[0]
    assert bot_feuds.load()["outcomes"]["by_archetype"]["豪爽"]["击杀"] == 99
    assert (await hub.set_value("rumors.json", "broadcast.slots_per_day", "20"))[0] and rumors.load_config()["broadcast"]["slots_per_day"] == 20


async def test_设置_校验不过就拒绝_不落库(db):
    ok, msg = await hub.set_value("bot_feuds.json", "tie_chance", "5")
    assert not ok and "校验没通过" in msg and "tie_chance" in msg
    assert bot_feuds.load()["tie_chance"] == hub.defaults("bot_feuds.json")["tie_chance"]
    assert hub.overrides_of("bot_feuds.json") == {}
    assert await rows(db) == []


@pytest.mark.parametrize("name,path,raw,expect", [
    ("不存在.json", "a", "1", "没有这个配置文件"),
    ("bot_feuds.json", "nope", "1", "没有可调"),
    ("bot_feuds.json", "_说明", "1", "没有可调"),
    ("bot_feuds.json", "outcomes.default.击杀.x", "1", "没有可调"),
    ("bot_feuds.json", "kill_enabled", "7", "开关"),
    ("bot_feuds.json", "kill.cap", "abc", "数字"),
    ("llm_polish.json", "scenes", "1", "没有可调"),
])
async def test_设置_拒绝坏输入(db, name, path, raw, expect):
    ok, msg = await hub.set_value(name, path, raw)
    assert not ok and expect in msg


async def rows(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return list((await s.execute(select(D.BotWorldState).where(D.BotWorldState.key.like("cfg.%")))).scalars())


async def test_设置_写库_改回默认就删掉那一项(db):
    await hub.set_value("bot_feuds.json", "kill.cap", "999")
    (r,) = await rows(db)
    assert r.key == "cfg.bot_feuds.json" and json.loads(r.value) == {"kill.cap": 999}
    ok, msg = await hub.set_value("bot_feuds.json", "kill.cap", str(hub.defaults("bot_feuds.json")["kill"]["cap"]))
    assert ok and "已是默认值" in msg and hub.overrides_of("bot_feuds.json") == {}
    assert await rows(db) == []


async def test_重启后从库里恢复(db):
    await hub.set_value("bot_feuds.json", "kill.cap", "999")
    await hub.set_value("rumors.json", "broadcast.slots_per_day", "20")
    hub._overrides.clear()
    hub.reload_module("bot_feuds.json")
    assert bot_feuds.load()["kill"]["cap"] != 999
    assert await hub.refresh() == 2
    assert bot_feuds.load()["kill"]["cap"] == 999 and rumors.load_config()["broadcast"]["slots_per_day"] == 20


async def test_重启_库里的坏数据被忽略_路径过期也不崩(db):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add_all([D.BotWorldState(key="cfg.bot_feuds.json", value=json.dumps({"kill.cap": 7, "已删除的.路径": 1, "scenes": "文字"})),
                   D.BotWorldState(key="cfg.rumors.json", value="不是json"),
                   D.BotWorldState(key="cfg.不存在.json", value="{}")])
        await s.commit()
    assert await hub.refresh() == 2                                   # 文字值被丢掉，过期路径保留但不生效
    assert bot_feuds.load()["kill"]["cap"] == 7 and "已删除的" not in bot_feuds.load()


async def test_读库出错_用默认值_只记警告(db, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("库坏了")
    monkeypatch.setattr(hub, "AsyncSessionLocal", boom)
    assert await hub.refresh() == 0 and "读取设置覆盖值失败" in caplog.text
    ok, msg = await hub.set_value("bot_feuds.json", "kill.cap", "5")
    assert not ok and "保存失败" in msg and hub.overrides_of("bot_feuds.json") == {}


async def test_恢复_一项_或整个文件(db):
    await hub.set_value("bot_feuds.json", "kill.cap", "999")
    await hub.set_value("bot_feuds.json", "rob.cap", "888")
    ok, msg = await hub.reset("bot_feuds.json", "kill.cap")
    assert ok and "已恢复默认" in msg and hub.overrides_of("bot_feuds.json") == {"rob.cap": 888}
    assert bot_feuds.load()["kill"]["cap"] == hub.defaults("bot_feuds.json")["kill"]["cap"]
    ok, msg = await hub.reset("bot_feuds.json")
    assert ok and "1 项" in msg and await rows(db) == [] and bot_feuds.load()["rob"]["cap"] == hub.defaults("bot_feuds.json")["rob"]["cap"]


async def test_恢复_没改过或没有这个文件(db):
    assert not (await hub.reset("bot_feuds.json"))[0]
    assert "本来就是默认" in (await hub.reset("bot_feuds.json", "kill.cap"))[1]
    assert "没有这个配置文件" in (await hub.reset("不存在.json"))[1]


async def test_恢复_保存失败不改内存(db, monkeypatch):
    await hub.set_value("bot_feuds.json", "kill.cap", "999")

    async def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(hub, "_save", boom)
    ok, msg = await hub.reset("bot_feuds.json")
    assert not ok and "保存失败" in msg and bot_feuds.load()["kill"]["cap"] == 999


# ---- 查询 -------------------------------------------------------------------

async def test_总览_搜索_列表(db):
    await hub.set_value("bot_feuds.json", "kill.cap", "999")
    ov = {o["file"]: o for o in hub.overview()}
    assert set(ov) == set(hub.REGISTRY) and ov["bot_feuds.json"]["changed"] == 1 and ov["rumors.json"]["changed"] == 0
    assert all(o["count"] > 0 for o in ov.values())
    found = hub.search("kill.cap")
    assert any(e["file"] == "bot_feuds.json" and e["changed"] and e["value"] == 999 for e in found)
    assert len(hub.search("a", limit=5)) == 5
    assert hub.entries("bot_feuds.json", "不存在的关键词") == []


# ---- 命令 -------------------------------------------------------------------

def make_cog(owner_ids=("1",)):
    async def is_owner(user):
        return str(user.id) in owner_ids
    return tuning.TuningCog(SimpleNamespace(is_owner=is_owner))


def ctx_with(uid, manage_guild=False):
    c = FakeContext(user_id=uid)
    c.author.guild_permissions = SimpleNamespace(manage_guild=manage_guild)
    return c


async def test_命令_没权限不能调(db):
    cog = make_cog()
    for cb, args in ((cog.tune.callback, ()), (cog.tune_list.callback, ("feuds",)), (cog.tune_search.callback, ("kill",)),
                     (cog.tune_set.callback, ("feuds", "kill.cap", "5")), (cog.tune_reset.callback, ("feuds",))):
        c = ctx_with(5)
        await cb(cog, c, *args)
        assert c.said("只有服务器管理员")
    assert hub.overrides_of("bot_feuds.json") == {}


async def test_命令_总览_列表_搜索(db):
    cog = make_cog()
    c = ctx_with(1)
    await cog.tune.callback(cog, c)
    assert c.said("调参总览") and c.said("bot_feuds.json")
    c = ctx_with(1)
    await cog.tune_list.callback(cog, c, "feuds", "kill")
    assert c.said("kill.cap") and c.said("含「kill」")
    c = ctx_with(1)
    await cog.tune_list.callback(cog, c, "feuds", "没有这个")
    assert c.said("没有路径含")
    c = ctx_with(1)
    await cog.tune_list.callback(cog, c, "不存在")
    assert c.said("没有这个配置文件")
    c = ctx_with(1)
    await cog.tune_search.callback(cog, c, "kills_per_day")
    assert c.said("bot_feuds.json") and c.said("kills_per_day")
    c = ctx_with(1)
    await cog.tune_search.callback(cog, c, "没有这个关键词")
    assert c.said("没找到")


async def test_命令_设置和恢复(db):
    cog = make_cog()
    c = ctx_with(1)
    await cog.tune_set.callback(cog, c, "feuds", "kill.cap", "123")
    assert c.said("✅") and bot_feuds.load()["kill"]["cap"] == 123
    c = ctx_with(1)
    await cog.tune_list.callback(cog, c, "feuds", "kill.cap")
    assert c.said("✏️") and c.said("默认")
    c = ctx_with(1)
    await cog.tune_set.callback(cog, c, "feuds", "kill.cap", "abc")
    assert c.said("❌")
    c = ctx_with(1)
    await cog.tune_set.callback(cog, c, "不存在", "a", "1")
    assert c.said("没有这个配置文件")
    c = ctx_with(1)
    await cog.tune_reset.callback(cog, c, "feuds", "kill.cap")
    assert c.said("✅") and bot_feuds.load()["kill"]["cap"] != 123
    c = ctx_with(1)
    await cog.tune_reset.callback(cog, c, "不存在")
    assert c.said("没有这个配置文件")


async def test_命令_初始化之后记下的管理员也能调(db):
    await world_settings.initialize("6", "正常")
    cog = make_cog()
    c = ctx_with(6)
    await cog.tune_set.callback(cog, c, "feuds", "kill.cap", "50")
    assert c.said("✅")


def test_输出被截断在一页内():
    es = [{"path": f"p{i}", "default": i, "value": i, "changed": False} for i in range(100)]
    out = tuning.clip([tuning.line(e) for e in es], len(es), "头\n")
    assert out.count("\n") <= tuning.PAGE + 2 and "还有 75 项" in out and len(out) < 2000


def test_格式化():
    assert tuning.fmt(True) == "开" and tuning.fmt(False) == "关" and tuning.fmt(0.25) == "0.25" and tuning.fmt(3) == "3"


# ---- 补：变异测试暴露的缺口 -------------------------------------------------

def test_下划线开头的键下面即使有数字也不算可调():
    assert dict(hub.leaves({"_n": 5, "_g": {"x": 1}, "a": 1})) == {"a": 1}


def test_路径中途序号越界_走不通():
    cfg = {"x": [{"y": 1}, {"y": 2}]}
    hub.apply(cfg, {"x.5.y": 9, "x.1.y": 7})
    assert cfg == {"x": [{"y": 1}, {"y": 7}]}


async def test_设置_路径里带下划线的段一律拒绝(db, monkeypatch):
    monkeypatch.setattr(hub, "defaults", lambda name: {"_n": 5, "a": 1})
    monkeypatch.setattr(hub, "validate", lambda name, cfg: [])
    ok, msg = await hub.set_value("bot_feuds.json", "_n", "7")
    assert not ok and "没有可调" in msg
    assert (await hub.set_value("bot_feuds.json", "a", "7"))[0]


async def test_重新读取时_库里被删掉的覆盖值恢复成默认(db):
    await hub.set_value("bot_feuds.json", "kill.cap", "999")
    assert bot_feuds.load()["kill"]["cap"] == 999                  # 缓存里是旧的覆盖值
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        await s.execute(D.BotWorldState.__table__.delete())
        await s.commit()
    assert await hub.refresh() == 0
    assert bot_feuds.load()["kill"]["cap"] == hub.defaults("bot_feuds.json")["kill"]["cap"]
