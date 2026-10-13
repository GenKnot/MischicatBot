"""机器人经济的共用参数与公式（utils/bot_economy.py、data/bot_economy.json）。

· 配置合法（并且校验器抓得住各类错误）；
· 随机取整期望不变、全服上限按期望缩放、收入分成守恒；
· 天花板：覆盖 > 最高真人所在大境 > 下限；
· 打工材料：只看机器人能做的工种、概率按折扣打折。
"""

import random

import pytest

from utils import bot_economy as be
from utils.items import ITEMS
from utils.realms import REALMS, get_realm_index

CFG = be.load_config()


def test_配置合法():
    assert be.validate_config(CFG) == []


def test_配置是拷贝_改了不影响别人():
    a = be.load_config()
    a["income"]["炮灰"] = 10**6
    assert be.load_config()["income"]["炮灰"] == CFG["income"]["炮灰"]


def test_杀人开关默认关():
    assert CFG["combat"]["can_kill_humans"] is True and CFG["combat"]["kill_protect_below"] == "筑基期1层"


def test_配置里是用户定下的数值():
    """2026-10-10 用户确认的参数（见 .gk/ISSUES.md「经济参数」「模拟结果」）。"""
    assert CFG["income"] == {"炮灰": 80, "正常": 200, "天骄": 500}
    assert CFG["speed"] == {"炮灰": 0.2, "正常": 0.4, "天骄": 0.8}
    assert CFG["refill_rate"] == 0.02
    assert CFG["combat"]["rob"] == {"share": 0.15, "cap": 150, "per_human_per_day": 3}
    assert CFG["combat"]["kill"] == {"share": 0.30, "cap": 300, "per_human_per_day": 5, "global_per_day": 4}
    assert CFG["pill_price"] == {"筑基丹": 1000, "凝丹丹": 3000, "化婴丹": 8000}
    assert CFG["materials"]["discount"] == 0.25 and CFG["day_years"] == 12


@pytest.mark.parametrize("edit,words", [
    (lambda c: c["income"].pop("天骄"), "income"),
    (lambda c: c["income"].update({"炮灰": -1}), "income"),
    (lambda c: c["speed"].update({"正常": 1.5}), "speed"),
    (lambda c: c.update(income_noise=[1.2, 0.8]), "income_noise"),
    (lambda c: c["money"].pop("豪爽"), "money"),
    (lambda c: c["money"]["豪爽"].update(carry=2), "carry"),
    (lambda c: c["pill_price"].pop("筑基丹"), "pill_price"),
    (lambda c: c.update(refill_rate=0), "refill_rate"),
    (lambda c: c.update(daily_cap_per_bot=0), "daily_cap_per_bot"),
    (lambda c: c["materials"].update(discount=2), "materials"),
    (lambda c: c["combat"]["rob"].update(share=0), "combat.rob"),
    (lambda c: c["combat"]["kill"].update(cap=0), "combat.kill"),
    (lambda c: c["combat"]["kill"].update(global_per_day=0), "global_per_day"),
    (lambda c: c["combat"]["captive_rob"].update(share=2), "captive_rob"),
    (lambda c: c["combat"]["power_bonus"].pop("天骄"), "power_bonus"),
    (lambda c: c["combat"]["power_bonus"].update({"正常": -0.1}), "power_bonus"),
    (lambda c: c["combat"]["cost"].pop("kill"), "combat.cost"),
    (lambda c: c["combat"]["cost"]["rob"].update(reputation=-1), "combat.cost"),
    (lambda c: c["combat"]["cost"]["rob"].update(favor=5), "好感变化"),
    (lambda c: c["combat"]["reaction"].pop("豪爽"), "combat.reaction"),
    (lambda c: c["combat"]["reaction"].update({"豪爽": {}}), "combat.reaction.豪爽"),
    (lambda c: c["combat"]["reaction"].update({"豪爽": {"fight": 1}}), "combat.reaction.豪爽"),
    (lambda c: c["combat"]["reaction"].update({"豪爽": {"release": 0}}), "combat.reaction.豪爽"),
    (lambda c: c["combat"].update(can_kill_humans="是"), "can_kill_humans"),
    (lambda c: c["combat"].update(kill_protect_below="不存在"), "kill_protect_below"),
    (lambda c: c["wild"].update(trip_chance=1.5), "wild.trip_chance"),
    (lambda c: c["public_events"].update(migrate_share=2), "migrate_share"),
    (lambda c: c["public_events"].update(activity_reward_budget_per_event=-1), "activity_reward_budget"),
    (lambda c: c["public_events"].update(stat_cap_over_tier=-1), "stat_cap_over_tier"),
    (lambda c: c["public_events"].update(bots_compete_for_defense_rewards="是"), "bots_compete"),
    (lambda c: c["public_events"]["auction"].update(max_multiple=0.5), "public_events.auction"),
    (lambda c: c["public_events"]["auction"].update(bid_window=[0.9, 0.1]), "public_events.auction"),
    (lambda c: c["public_events"]["auction"]["interest"].update(equipment=["不存在"]), "interest"),
    (lambda c: c["materials"].update(keep_equipment=0), "keep_equipment"),
    (lambda c: c.update(refill_min_per_day=0), "refill_min_per_day"),
    (lambda c: c["ceiling"].update(override="不存在期"), "ceiling.override"),
    (lambda c: c["ceiling"].update(floor=None), "floor"),
])
def test_校验器抓得住错误(edit, words):
    cfg = be.load_config()
    edit(cfg)
    errors = be.validate_config(cfg)
    assert errors and any(words in e for e in errors), errors


# ---- 公式 -------------------------------------------------------------------

def test_随机取整_期望不变():
    rng = random.Random(1)
    vals = [be.stochastic_round(2.4, rng) for _ in range(20000)]
    assert set(vals) == {2, 3} and abs(sum(vals) / len(vals) - 2.4) < 0.02
    assert be.stochastic_round(5, rng) == 5 and be.stochastic_round(0, rng) == 0


def test_收入在噪声范围内():
    rng = random.Random(2)
    lo, hi = CFG["income_noise"]
    for tier, base in CFG["income"].items():
        vals = [be.daily_income(tier, CFG, rng) for _ in range(500)]
        assert all(base * lo <= v <= base * hi for v in vals)


def test_全服上限_按期望缩放():
    tiers = ["正常"] * 10                                            # 期望 2000
    cfg = be.load_config()
    cfg["daily_cap_per_bot"] = 250
    assert be.income_scale(tiers, cfg) == 1.0
    cfg["daily_cap_per_bot"] = 100
    assert be.income_scale(tiers, cfg) == pytest.approx(0.5)        # 期望 2000，上限 1000
    assert be.income_scale([], cfg) == 1.0
    cfg["daily_cap_per_bot"] = 10**6
    assert be.income_scale(tiers, cfg) == 1.0


def test_默认上限不压低正常收入():
    """上限是『保险丝』：按 60/35/5 混合的期望收入（≈143/个）远低于配置的每机器人上限（170 ≈ 期望的 1.2 倍），
    正常情况下缩放系数恰好是 1，不会天天触发。"""
    tiers = ["炮灰"] * 300 + ["正常"] * 175 + ["天骄"] * 25
    assert be.income_scale(tiers, CFG) == 1.0
    assert CFG["daily_cap_per_bot"] > 143 * 1.1


def test_收入分成守恒():
    rng = random.Random(3)
    for arche, m in CFG["money"].items():
        for paid in (0, 1, 7, 100, 999):
            carry, bank = be.split_income(paid, arche, CFG, rng)
            assert carry + bank == paid and 0 <= carry <= paid
        carries = [be.split_income(1000, arche, CFG, rng)[0] for _ in range(50)]
        assert all(abs(c - 1000 * m["carry"]) <= 1 for c in carries)


def test_日常开销():
    assert be.spend_amount(1000, "豪爽", CFG) == 150 and be.spend_amount(1000, "高冷", CFG) == 70
    assert be.spend_amount(0, "豪爽", CFG) == 0 and be.spend_amount(5, "高冷", CFG) == 0


def test_补员上限_比例与下限():
    assert be.refill_cap(500, CFG) == 10                    # 2%
    assert be.refill_cap(100, CFG) == 5                     # 2% = 2，被下限抬到 5
    assert be.refill_cap(0, CFG) == 5
    cfg = be.load_config()
    cfg["refill_min_per_day"] = 1
    assert be.refill_cap(100, cfg) == 2


def test_小世界补员不塌陷():
    """100 个的世界：只按 2% 补最低掉到 52%；加了每天至少补 5 个之后最低在 85% 以上。"""
    import importlib.util, os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "sim_bots.py")
    spec = importlib.util.spec_from_file_location("sim_bots_for_refill", path)
    sb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sb)
    sim = sb.Sim(sb.Params(bots=100, days=120, human_top="炼气期", robbers=0, robs_each=0)).run()
    assert min(d["pop"] for d in sim.daily) >= 85


def test_活跃年数():
    assert be.active_years("正常", CFG, random.Random(0)) in (4, 5)         # 12 × 0.4 = 4.8
    assert be.active_years("炮灰", CFG, random.Random(0)) in (2, 3)         # 2.4
    assert be.active_years("天骄", CFG, random.Random(0)) in (9, 10)        # 9.6


def test_大关价格():
    assert be.gate_price("炼气期10层", CFG) == ("筑基丹", 1000)
    assert be.gate_price("筑基期10层", CFG) == ("凝丹丹", 3000)
    assert be.gate_price("结丹期后期", CFG) == ("化婴丹", 8000)
    assert be.gate_price("炼气期9层", CFG) is None and be.gate_price("元婴期初期", CFG) is None


# ---- 天花板 -----------------------------------------------------------------

def test_天花板_取最高真人所在大境的末层():
    assert REALMS[be.ceiling_index("筑基期3层", CFG)] == "筑基期10层"
    assert REALMS[be.ceiling_index("结丹期初期", CFG)] == "结丹期后期"
    assert REALMS[be.ceiling_index("太乙中期", CFG)] == "太乙后期"


def test_天花板_没有真人或真人更低时取下限():
    assert REALMS[be.ceiling_index(None, CFG)] == "炼气期10层"
    cfg = be.load_config()
    cfg["ceiling"]["floor"] = "筑基期"
    assert REALMS[be.ceiling_index(None, cfg)] == "筑基期10层"
    assert REALMS[be.ceiling_index("炼气期2层", cfg)] == "筑基期10层"
    assert REALMS[be.ceiling_index("元婴期初期", cfg)] == "元婴期后期"


def test_天花板_覆盖优先():
    cfg = be.load_config()
    cfg["ceiling"]["override"] = "结丹期"
    assert REALMS[be.ceiling_index("太乙中期", cfg)] == "结丹期后期"        # 现网那个调试账号不会拉高天花板
    assert REALMS[be.ceiling_index(None, cfg)] == "结丹期后期"


def test_境界截断():
    realms = REALMS[:30]
    assert be.realm_at_most(realms, 4) == REALMS[:5]
    assert be.realm_at_most(REALMS[10:20], 3) == [REALMS[3]], "全都超过时退而取天花板那一层"


# ---- 材料 -------------------------------------------------------------------

def test_机器人能做的工种():
    names = lambda realm: {j["id"] for j in be.eligible_jobs(realm)}      # noqa: E731
    assert "porter" not in names("元婴期初期"), "限定城市的工种不算"
    assert "mine_labor" not in names("炼气期1层") and "mine_labor" in names("炼气期5层")
    assert "sweep" in names("炼气期1层")
    assert names("炼气期1层") < names("元婴期初期")


def test_材料掉落_折扣与确定性():
    cfg = be.load_config()
    cfg["materials"]["discount"] = 0
    assert be.material_roll("炼气期5层", cfg, random.Random(1)) == []
    cfg["materials"]["discount"] = 1
    full = [len(be.material_roll("炼气期5层", cfg, random.Random(i))) for i in range(300)]
    cfg["materials"]["discount"] = 0.25
    cut = [len(be.material_roll("炼气期5层", cfg, random.Random(i))) for i in range(300)]
    assert sum(cut) < sum(full) * 0.5
    assert be.material_roll("炼气期5层", cfg, random.Random(9)) == be.material_roll("炼气期5层", cfg, random.Random(9))
    for name in be.material_roll("炼气期5层", {**cfg, "materials": {**cfg["materials"], "discount": 1}}, random.Random(4)):
        assert name in ITEMS


def test_物品价值():
    assert be.item_value("铜矿石") == 5 and be.item_value("不存在") == 0 and be.item_value("筑基丹") == 0


def test_大关表覆盖三道大关且在境界体系内():
    assert set(be.GATES) <= set(REALMS)
    assert [get_realm_index(r) for r in be.GATES] == sorted(get_realm_index(r) for r in be.GATES)
