"""机器人世界里原本写死在代码里的系数，搬进配置之后（批次 070）：校验能拦住坏配置，调参后行为立刻变。"""

import copy
import random

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from utils import bot_ambush, bot_chatter, bot_economy, bot_grudges, bot_memory, bot_profile, bot_requests, bot_social, bot_ties, fame
from utils import settings_hub as hub


@pytest.fixture(autouse=True)
def clean_hub():
    def reset():
        hub._overrides.clear()
        for name in hub.REGISTRY:
            hub.reload_module(name)
    reset()
    yield
    reset()


async def tune(file: str, path: str, value) -> None:
    ok, msg = await hub.set_value(file, path, str(value))
    assert ok, msg


class Z(random.Random):
    def __init__(self, value=0.0):
        super().__init__(0)
        self.value = value

    def random(self):
        return self.value

    def uniform(self, a, b):
        return a + (b - a) * self.value


def bad(module, mutate, expect, **kw):
    loader = getattr(module, "load", None) or getattr(module, "load_config", None) or module.favor_cfg
    cfg = copy.deepcopy(loader())
    mutate(cfg)
    errors = module.validate(cfg, **kw) if hasattr(module, "validate") else module.validate_config(cfg)
    assert any(expect in e for e in errors), errors


# ---- 记忆 -------------------------------------------------------------------

def test_记忆配置合法且能拦坏值():
    assert bot_memory.validate(bot_memory.load()) == []
    bad(bot_memory, lambda c: c.update(max_gifts=0), "max_gifts")
    bad(bot_memory, lambda c: c["recall"].update(base=2), "recall")
    bad(bot_memory, lambda c: c["recall"]["level_factor"].pop("外向"), "level_factor")


async def test_记忆_回忆概率和礼物保留数可调(db):
    await tune("bot_memory.json", "max_gifts", 1)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add_all([make_player(D, "1001"), make_player(D, "bot_00001")])
        await s.commit()
    await bot_memory.remember("1001", "bot_00001", "gift", "甲", "like", now=1.0)
    await bot_memory.remember("1001", "bot_00001", "gift", "乙", "like", now=2.0)
    assert [r.detail for r in (await bot_memory.recall("1001", "bot_00001"))["gift"]] == ["乙"]
    m = {"chat": [type("R", (), {"count": 1, "prev_at": 0, "extra": "", "last_at": 0})()]}
    await tune("bot_memory.json", "recall.base", 1.0)
    await tune("bot_memory.json", "recall.cap", 1.0)
    assert bot_memory.pick_recall({"gift": [type("R", (), {"detail": "x", "extra": "", "last_at": 1})()]}, "greet", "熟识", "中性", Z(0.99)) is not None


# ---- 名望 -------------------------------------------------------------------

def test_名望配置合法且能拦坏值():
    assert fame.validate(fame.load()) == []
    bad(fame, lambda c: c["tiers"].update(无名之辈=5), "最低一档")
    bad(fame, lambda c: c["tiers"].update(小有名气=0), "不能相同")
    bad(fame, lambda c: c.update(city_fame=300), "city_fame")
    bad(fame, lambda c: c.update(score_divisor=0), "score_divisor")


async def test_名望_分档和传播范围和涨幅可调(db):
    assert fame.tier(60) == "小有名气" and fame.reach(60) == "city" and fame.gain(41) == 20
    await tune("bot_fame.json", "tiers.小有名气", 100)
    await tune("bot_fame.json", "city_fame", 100)
    await tune("bot_fame.json", "score_divisor", 4)
    assert fame.tier(60) == "无名之辈" and fame.reach(60) == "none" and fame.gain(41) == 10 and fame.gain(1) == 1


# ---- 好感 -------------------------------------------------------------------

def test_好感配置合法且能拦坏值():
    assert bot_social.validate(bot_social.favor_cfg()) == []
    bad(bot_social, lambda c: c["required"].update(party=60), "required")
    bad(bot_social, lambda c: c.update(hostile_below=5), "hostile_below")
    bad(bot_social, lambda c: c["gift_delta"].pop("love"), "gift_delta")
    bad(bot_social, lambda c: c["remark_tier_factor"].pop("仇视"), "remark_tier_factor")
    bad(bot_social, lambda c: c.update(talkative_at=200), "talkative_at")


async def test_好感_档位门槛和送礼数值可调(db):
    assert bot_social.favor_tier(20) == "熟识" and bot_social.required_favor("party") == 20
    await tune("bot_favor.json", "required.party", 30)
    await tune("bot_favor.json", "hostile_below", -50)
    await tune("bot_favor.json", "kindness_div", 10)
    assert bot_social.favor_tier(20) == "陌生" and bot_social.favor_tier(-40) == "陌生" and bot_social.favor_tier(-50) == "仇视"
    assert bot_social.required_favor("party", 0) == 35
    await tune("bot_favor.json", "gift_delta.love", 20)
    await tune("bot_favor.json", "rarity_bonus.稀有", 5)
    assert bot_social.gift_reaction({"likes": {"items": ["筑基丹"]}}, "筑基丹")[1] >= 20


# ---- 世界规模与档位 ---------------------------------------------------------

def test_经济世界配置合法且能拦坏值():
    assert bot_economy.validate_config(bot_economy.load_config()) == []
    bad(bot_economy, lambda c: c["world"].update(max_bots=0), "max_bots")
    bad(bot_economy, lambda c: c["world"]["tier_weights"].update(炮灰=-1), "tier_weights")
    bad(bot_economy, lambda c: c["world"]["tiers"]["炮灰"].update(realms=["炼气期5层", "炼气期1层"]), "realms")
    bad(bot_economy, lambda c: c["world"]["tiers"]["正常"].update(stats=[9, 4]), "stats")
    bad(bot_economy, lambda c: c["world"].update(raid_keep_days=0), "raid_keep_days")
    bad(bot_economy, lambda c: c["public_events"].update(meet_pairs_per_event=-1), "meet_pairs_per_event")


async def test_世界规模_生成数量与档位比例可调(db):
    from utils import bot_world
    await tune("bot_economy.json", "world.max_per_batch", 3)
    assert bot_world.default_count() == 3, "默认个数不会超过一次最多生成数"
    res = await bot_world.generate_bots(4)
    assert not res["ok"] and "1~3" in res["reason"]
    await tune("bot_economy.json", "world.max_bots", 5)
    await tune("bot_economy.json", "world.default_count", 2)
    assert (await bot_world.generate_bots())["ok"] and len((await bot_world.generate_bots(3))["created"]) == 3
    res = await bot_world.generate_bots(1)
    assert not res["ok"] and "上限 5" in res["reason"]
    for tier, w in (("炮灰", 0), ("天骄", 0)):
        await tune("bot_economy.json", f"world.tier_weights.{tier}", w)
    rng = random.Random(1)
    assert {bot_world.roll_tier(rng) for _ in range(50)} == {"正常"}


async def test_世界规模_出生属性范围可调(db):
    from utils import bot_world
    await tune("bot_economy.json", "world.tiers.炮灰.stats.0", 6)
    f = bot_world.roll_player_fields(random.Random(1), "炮灰", "bot_00001", "某", 0.0)
    assert f["comprehension"] == 6


# ---- 人格 -------------------------------------------------------------------

def test_人格配置合法且能拦坏值():
    assert bot_profile.validate(bot_profile.load()) == []
    bad(bot_profile, lambda c: c["righteous"].update(min_kindness=200), "righteous")
    bad(bot_profile, lambda c: c["revenge_style"].update(direct_above=10), "revenge_style")
    bad(bot_profile, lambda c: c["captive"]["kind_high"].update(跑=1), "captive")
    bad(bot_profile, lambda c: c["captive"].update(lawful_low_kill=-1), "captive")


async def test_人格_复仇风格阈值和处置倍数可调(db):
    prof = {"impulse": 70, "deviance": 0, "lawful": 50}
    assert bot_profile.revenge_style(prof, Z(0.0)) == "直接"
    assert bot_profile.revenge_style(prof, Z(0.9)) == "等待时机", "冲动 70 ≥ 65：八成直接，其余等待时机"
    await tune("bot_profiles.json", "revenge_style.direct_above", 80)
    assert bot_profile.revenge_style(prof, Z(0.9)) == "隐忍", "冲动 70 < 80 就走折中公式了"
    assert bot_profile.is_righteous(60, {"loyalty": 100, "impulse": 0}) is True
    await tune("bot_profiles.json", "righteous.min_kindness", 70)
    assert bot_profile.is_righteous(60, {"loyalty": 100, "impulse": 0}) is False
    await tune("bot_profiles.json", "captive.kind_high.release", 9)
    assert bot_profile.captive_shift(100, {"lawful": 50, "impulse": 50, "deviance": 0}, Z(0.99))["release"] == 9


# ---- 仇恨 / 拦路 / 关系 / 请求 / 搭话 ---------------------------------------

def test_各系统新增的系数能拦坏值():
    bad(bot_grudges, lambda c: c["formula"].update(third_cap=2), "formula")
    bad(bot_grudges, lambda c: c["appease"]["apology"].update(chance_cap=2), "appease")
    bad(bot_ambush, lambda c: c["fight"].update(noise=[1.2, 0.8]), "fight.noise")
    bad(bot_ambush, lambda c: c["severity_weight"].update(release_div=0), "release_div")
    bad(bot_ambush, lambda c: c.update(stuck_seconds=-1), "stuck_seconds")
    bad(bot_ties, lambda c: c["daily"].update(quarrel_aff_base=0.5), "quarrel_aff_base")
    bad(bot_ties, lambda c: c["player"].update(enemy_recover_margin=-1), "enemy_recover_margin")
    bad(bot_requests, lambda c: c["repay"]["default_div"].update(lawful=0), "default_div")
    bad(bot_requests, lambda c: c["repay"].update(default_cap=2), "default_cap")
    bad(bot_requests, lambda c: c["ask"].update(tries_per_offer=0), "tries_per_offer")
    bad(bot_chatter, lambda c: c["queue"].update(claim_limit=0), "queue")


async def test_仇恨_公式系数可调(db):
    cfg = bot_grudges.load()
    assert cfg["formula"]["third_cap"] == 0.95
    await tune("bot_grudges.json", "formula.third_cap", 0.1)
    assert bot_grudges.load()["formula"]["third_cap"] == 0.1


async def test_拦路_战力随机范围和卡死时长可调(db):
    await tune("bot_ambush.json", "stuck_seconds", 5)
    assert bot_ambush.load()["stuck_seconds"] == 5
    await tune("bot_ambush.json", "fight.noise.0", 1.0)
    assert bot_ambush.load()["fight"]["noise"][0] == 1.0
    await tune("bot_ambush.json", "severity_weight.release_div", 10)
    w = bot_ambush.outcome_weights("豪爽", 50, "rob", 50, None, "apologize", True, Z(0.5))
    assert w["release"] >= 0


def test_赖账公式除数可调():
    base = bot_requests.default_probability("憨直", 20, 50, 50, "熟识")
    cfg = copy.deepcopy(bot_requests.load())
    cfg["repay"]["default_div"]["lawful"] = 10
    assert bot_requests.default_probability("憨直", 20, 50, 50, "熟识", cfg) > base
