"""游戏规则数值（utils/rules.py、data/game_rules.json）：校验、棘轮，以及『调参立刻生效』（管理员改了数字，对应的玩法马上变）。"""

import copy
import random

import pytest

from tests.conftest import make_player
from utils import rules
from utils import settings_hub as hub


@pytest.fixture(autouse=True)
def clean_hub():
    hub._overrides.clear()
    hub.reload_module("game_rules.json")
    yield
    hub._overrides.clear()
    hub.reload_module("game_rules.json")


async def tune(path: str, value) -> None:
    ok, msg = await hub.set_value("game_rules.json", path, str(value))
    assert ok, msg


# ---- 校验与棘轮 -------------------------------------------------------------

def test_默认配置合法():
    assert rules.validate(rules.load()) == []


def test_棘轮_每个数字都登记了取值范围_每条范围都有数字用到():
    cfg = rules.load()
    paths = [p for p, _ in hub.leaves(cfg)]
    assert all(rules.pattern(p) for p in paths), [p for p in paths if not rules.pattern(p)]
    used = {rules.pattern(p) for p in paths}
    assert set(rules.SPECS) == used, f"没用到的范围：{set(rules.SPECS) - used}"
    assert rules.INTEGER <= set(rules.SPECS)


def test_新增数字没登记范围会报错():
    cfg = copy.deepcopy(rules.load())
    cfg["bank"]["new_knob"] = 5
    assert any("没有登记取值范围" in e for e in rules.validate(cfg))


@pytest.mark.parametrize("mutate,expect", [
    (lambda c: c["bank"].update(demand_rate=2), "bank.demand_rate"),
    (lambda c: c["bank"].update(min_deposit=1.5), "应是整数"),
    (lambda c: c["bank"]["terms"][1].update(years=10), "年限不能重复"),
    (lambda c: c["bank"].update(terms=[]), "至少一档"),
    (lambda c: c["roulette"]["slots"][4].update(multiplier=500), "期望倍率不能超过 1"),
    (lambda c: [s.update(count=0) for s in c["roulette"]["slots"]], "至少要有一格"),
    (lambda c: c["tavern"]["quest_years"].pop("传说"), "tavern.quest_years"),
    (lambda c: c["alchemy"]["quality_multipliers"].pop(), "必须正好 12 档"),
    (lambda c: c["alchemy"]["exp_thresholds"].pop(), "必须正好 10 项"),
    (lambda c: c["alchemy"]["mastery_stages"][1].update(crafts=0), "次数严格递增"),
    (lambda c: c["alchemy"]["failure"].update(plain_p=0.9, ruin_p=0.2), "不能超过 1"),
    (lambda c: c["alchemy"]["failure"].update(ruin_loss=[5, 1]), "ruin_loss"),
    (lambda c: c["alchemy"]["success"].update(min=99), "min 不能大于 max"),
    (lambda c: c["forging"]["slot_ore_qty"].pop("饰品"), "slot_ore_qty"),
    (lambda c: c["forging"]["exp_thresholds"].pop(), "必须正好 10 项"),
    (lambda c: c["forging"]["reforge"]["cost_multiplier"].pop("传说"), "cost_multiplier"),
    (lambda c: c["forging"]["exam_materials"].clear(), "exam_materials 不能为空"),
    (lambda c: c["gathering"]["options"].reverse(), "gathering.options"),
    (lambda c: c["gathering"]["rarity_base"].pop("绝世"), "rarity_base"),
    (lambda c: [c["character"]["spirit_root_odds"].update({k: 0}) for k in list(c["character"]["spirit_root_odds"])], "权重总和 > 0"),
    (lambda c: c["character"]["spirit_root_odds"].pop("变异灵根"), "spirit_root_odds"),
    (lambda c: c["character"]["realm_lifespan"].update(炼气期=99999999), "character.realm_lifespan"),
    (lambda c: c["character"]["realm_lifespan"].update(炼气期=20000), "应随境界递增"),
    (lambda c: c["character"]["base_stats"].pop("soul"), "base_stats"),
])
def test_校验能拦住坏配置(mutate, expect):
    cfg = copy.deepcopy(rules.load())
    mutate(cfg)
    assert any(expect in e for e in rules.validate(cfg)), rules.validate(cfg)


def test_pattern匹配列表序号和字典键():
    assert rules.pattern("bank.terms.3.rate") == "bank.terms.*.rate"
    assert rules.pattern("tavern.quest_years.普通") == "tavern.quest_years.*"
    assert rules.pattern("bank.nope") is None and rules.pattern("a.b.c.d.e") is None


def test_get按路径取值():
    assert rules.get("bank.terms.0.years") == 10 and rules.get("tavern.quest_years.精英") == 1


# ---- 调参立即生效 -----------------------------------------------------------

async def add(db, uid="1", stones=1_000_000, **kw):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        p = make_player(D, uid, stones=stones)
        p.name, p.current_city = f"道友{uid}", "灵虚城"
        for k, v in kw.items():
            setattr(p, k, v)
        s.add(p)
        await s.commit()


async def test_钱庄_最低存款和转账上限和手续费(db):
    from utils import bank
    await add(db, "1")
    await add(db, "2", stones=0)
    assert (await bank.deposit_term("1", 20000, 10))["ok"]
    await tune("bank.min_deposit", 50000)
    assert "最低 50,000" in (await bank.deposit_term("1", 20000, 10))["reason"]
    await tune("bank.transfer_max", 100)
    assert "上限 100" in (await bank.transfer("1", "2", 101))["reason"]
    await tune("bank.transfer_fee_rate", 0.5)
    r = await bank.transfer("1", "2", 100)
    assert r["ok"] and r["fee"] == 50


async def test_钱庄_定期利率档位可调(db):
    from utils import bank
    await add(db, "1")
    await tune("bank.terms.0.rate", 0.5)
    r = await bank.deposit_term("1", 20000, 10)
    assert r["interest"] == 20000 * 0.5 * 10


async def test_坊市_手续费和上架数(db):
    from utils import market
    await tune("market.max_listings", 1)
    assert market.rules.section("market")["max_listings"] == 1
    await tune("market.fee_rate", 0.5)
    assert rules.get("market.fee_rate") == 0.5


async def test_轮转_下注额和每日次数(db):
    from utils import roulette
    await add(db, "1", stones=10_000)
    await tune("roulette.bet", 1000)
    await tune("roulette.daily_limit", 1)
    r = await roulette.do_roulette("1")
    assert r["ok"] and r["bet"] == 1000 and r["daily_limit"] == 1
    assert "上限" in (await roulette.do_roulette("1"))["reason"]


async def test_轮转_格数改了转盘跟着变_期望超过1的改法被拒(db):
    from utils import roulette
    assert len(roulette.wheel()) == 12
    await tune("roulette.slots.0.count", 8)
    assert len(roulette.wheel()) == 14 and [s["label"] for s in roulette.slots()][:2] == ["× 0", "× 0.5"]
    ok, msg = await hub.set_value("game_rules.json", "roulette.slots.4.multiplier", "500")
    assert not ok and "期望倍率" in msg and len(roulette.wheel()) == 14


async def test_打工_冷却和次数(db):
    from utils import jobs
    await tune("jobs.daily_limit", 1)
    await tune("jobs.cooldown_seconds", 0)
    await add(db, "1")
    player = {"discord_id": "1", "realm": "炼气期1层", "reputation": 0}
    job = jobs.JOBS[0]
    assert (await jobs.do_job(player, job))["ok"]
    assert "上限" in (await jobs.do_job(player, job))["reason"]


async def test_探险_次数上限可调(db):
    from cogs import explore as ex
    await tune("explore.limit", 2)
    assert await ex._get_explore_limit({"discord_id": "x", "current_city": "灵虚城", "cave": None}) == 2


async def test_组队_人数上限(db):
    from utils import party
    await add(db, "1")
    await add(db, "2")
    await add(db, "3")
    pid = await party.create_party("1", "灵虚城")
    await tune("party.max_size", 2)
    assert await party.add_to_party(pid, "1") in (True, False)
    assert await party.add_to_party(pid, "2")
    assert not await party.add_to_party(pid, "3")


async def test_炼丹_每日次数和品质倍率(db):
    from utils import alchemy
    await tune("alchemy.daily_limit", 1)
    assert alchemy.daily_limit() == 1
    await tune("alchemy.quality_multipliers.2", 9)
    assert alchemy.quality_multipliers()[2] == 9
    await tune("alchemy.exp_thresholds.2", 7)
    assert alchemy.exp_thresholds()[2] == 7


async def test_炼丹_成功率和失败后果(db):
    from utils import alchemy
    recipe = {"base_success_rate": 50}
    assert alchemy.calc_success_rate(recipe, 1, 0) == 50
    await tune("alchemy.success.free_mix_factor", 0.5)
    assert alchemy.calc_success_rate(recipe, 1, 0, free_mix=True) == 25
    await tune("alchemy.success.max", 40)
    assert alchemy.calc_success_rate(recipe, 1, 0) == 40
    await tune("alchemy.failure.plain_p", 0.0)
    await tune("alchemy.failure.ruin_p", 1.0)
    assert alchemy.roll_failure_consequence()[0] == "炉毁"


async def test_炼丹_熟练度阶段(db):
    from utils import alchemy
    assert alchemy.get_mastery_label(0) == "生疏" and alchemy.get_mastery_label(100) == "炉火纯青"
    await tune("alchemy.mastery_stages.3.crafts", 500)
    assert alchemy.get_mastery_label(100) == "精通" and alchemy.get_mastery_bonus(500) == (3, True)


async def test_炼器_成功率和熟练度(db):
    from utils import forging
    base = forging.calc_forge_success_rate(1, "普通", 0, 0)
    await tune("forging.success.base", 70)
    assert forging.calc_forge_success_rate(1, "普通", 0, 0) == base - 15
    await tune("forging.mastery_stages.1.bonus", 50)
    assert forging.get_forging_mastery(10) == ("熟悉", 50)


async def test_炼器_考核费用和淬炼费用(db):
    from utils import forging
    await tune("forging.exam_cost", 777)
    assert forging.exam_cost() == 777
    await tune("forging.reforge.base_cost", 1000)
    assert forging.reforge_cost("稀有") == 4000


async def test_采集_时长选项和稀有度(db):
    from utils.views import gathering as gv
    await tune("gathering.options.0", 0.3)
    assert gv.gather_options()[0][:3] == (0.3, "3.6个月", "现实 36 分钟")
    ok, msg = await hub.set_value("game_rules.json", "gathering.options.0", "0.5")
    assert not ok and "gathering.options" in msg, "和下一项重复会被拒"
    await tune("gathering.rarity_base.普通", 1)
    assert gv._rarity_weights(0, 0)["普通"] == 1


async def test_修炼公式和灵根概率_寿元(db):
    from utils import character as ch
    assert ch.calc_cultivation_gain(10, 5, "单灵根") == 200
    await tune("character.cultivation.base_per_year", 20)
    assert ch.calc_cultivation_gain(10, 5, "单灵根") == 400
    await tune("character.spirit_root_speed.单灵根", 3)
    assert ch.calc_cultivation_gain(10, 5, "单灵根") == 600
    await tune("character.realm_lifespan.炼气期", 150)
    assert ch.realm_lifespan("炼气期") == 150
    await tune("character.cave.bonus", 1)


async def test_灵根概率改了抽到的就变(db):
    from utils import character as ch
    for name in ("双灵根", "三灵根", "四灵根", "五灵根", "变异灵根"):
        await tune(f"character.spirit_root_odds.{name}", 0)
    rng = random.Random(1)
    assert {ch.roll_spirit_root(rng)[1] for _ in range(50)} == {"单灵根"}, "只剩一种权重，一定抽到它"
    await tune("character.spirit_root_odds.变异灵根", 5)
    await tune("character.spirit_root_odds.单灵根", 0)
    ok, msg = await hub.set_value("game_rules.json", "character.spirit_root_odds.变异灵根", "0")
    assert not ok and "权重总和" in msg, "全部归零会被拒"
    assert {ch.roll_spirit_root(rng)[1] for _ in range(50)} == {"变异灵根"}


async def test_置业价格和加成(db):
    from cogs import property as prop
    await tune("character.cave.price", 123)
    assert prop._cave_cfg()["price"] == 123
    await tune("character.residence.price_normal", 1)
    assert prop._residence_price("不存在的城") == 1


# ---- 境界节奏 / 战斗 / 任务 / 转世 / 大关 / 装备 / 签到 / 赌坊 / 奇遇 -------------

async def test_境界_突破所需修为_寿元_成功率_栏位可调(db):
    from utils import realms
    assert realms.cultivation_needed("炼气期1层") == 100 and realms.cultivation_needed("结丹期初期") == 400
    await tune("realms.cultivation_needed.tier1", 150)
    await tune("realms.cultivation_needed.late_step", 250)
    assert realms.cultivation_needed("炼气期3层") == 150 and realms.cultivation_needed("结丹期中期") == 650
    await tune("realms.lifespan_max.table.道祖", 5)
    assert realms.lifespan_max_for_realm("道祖") == 5 and realms.lifespan_max_for_realm("不存在") == 100
    base = realms.breakthrough_success_rate("炼气期1层", 5, 5, 0)
    await tune("realms.breakthrough.tier1_base", 0.5)
    assert realms.breakthrough_success_rate("炼气期1层", 5, 5, 0) == pytest.approx(0.5) and base > 0.5
    await tune("realms.breakthrough.cap", 0.6)
    assert realms.breakthrough_success_rate("炼气期1层", 5, 5, 10 ** 9) == 0.6
    await tune("realms.technique_slots.筑基期1层", 8)
    assert realms.get_technique_slot_limit("筑基期2层") == 8


async def test_境界_失败后果和权重可调(db):
    from utils import realms
    assert realms.apply_failure(1000, 100, realms.FAIL_HEAVY)[:2] == (500, 90)
    await tune("realms.failure.cultivation_keep", 0.8)
    await tune("realms.failure.heavy_loss_div", 5)
    await tune("realms.failure.deviate_loss_div", 2)
    assert realms.apply_failure(1000, 100, realms.FAIL_HEAVY)[:2] == (800, 80)
    assert realms.apply_failure(1000, 100, realms.FAIL_DEVIATE)[:2] == (0, 50)
    for k in ("light", "heavy"):
        await tune(f"realms.failure.early_weights.{k}", 0)
    assert {realms.roll_failure_outcome("炼气期1层") for _ in range(30)} == {realms.FAIL_DEVIATE}
    await tune("realms.failure.split_index", 0)
    assert realms.roll_failure_outcome("炼气期1层") in (realms.FAIL_LIGHT, realms.FAIL_HEAVY, realms.FAIL_DEVIATE)


async def test_战斗_战力境界系数_逃跑率_随机范围(db):
    from utils import combat
    p = {"discord_id": "x", "realm": "筑基期1层", "techniques": "[]", "soul": 5}
    power = await combat.calc_power(p, equipped=[])
    await tune("combat.realm_step", 0.3)
    assert await combat.calc_power(p, equipped=[]) > power
    base = await combat.calc_escape_rate({"discord_id": "x", "realm": "炼气期1层", "soul": 5})
    await tune("combat.escape.base", 0.6)
    assert await combat.calc_escape_rate({"discord_id": "x", "realm": "炼气期1层", "soul": 5}) == pytest.approx(base + 0.3)
    await tune("combat.escape.max", 0.5)
    assert await combat.calc_escape_rate({"discord_id": "x", "realm": "炼气期1层", "soul": 5}) == 0.5
    await tune("combat.noise.0", 1.15)
    won, atk, dfn = await combat.roll_combat({"discord_id": "a", "realm": "炼气期1层", "techniques": "[]"}, {"discord_id": "b", "realm": "炼气期1层", "techniques": "[]"})
    assert atk == dfn, "随机范围收成一个点之后，双方战力相同"


async def test_转世_加成_初始灵石_奇遇概率(db):
    from utils import death_rebirth_logic as dr
    p = {"rebirth_count": 1, "comprehension": 15, "physique": 5, "fortune": 5, "bone": 5, "soul": 5}
    assert dr.calculate_rebirth_bonus(p)["comprehension"] == 4
    await tune("rebirth.stat_keep", 0.5)
    assert dr.calculate_rebirth_bonus(p)["comprehension"] == 7
    await tune("rebirth.mult_step", 0)
    assert dr.calculate_rebirth_bonus(p)["comprehension"] == 5
    await tune("rebirth.yinyang_chance", 1)
    assert dr.should_trigger_yinyang({"rebirth_count": 0})
    await tune("rebirth.yinyang_chance", 0)
    assert not dr.should_trigger_yinyang({"rebirth_count": 0})


async def test_大关_突破率系数可调(db):
    from utils.items import breakthrough as bt
    p = {"spirit_root_type": "单灵根", "comprehension": 5, "fortune": 5, "bone": 5, "soul": 5}
    five = {**p, "spirit_root_type": "五灵根"}
    assert bt.calc_zhuji_breakthrough_rate(p) == 95 and bt.calc_zhuji_breakthrough_rate(five) == 30 + 25
    await tune("gates.zhuji.pill", 1)
    assert bt.calc_zhuji_breakthrough_rate(five, use_pill=True) == 30 + 25 + 1
    await tune("gates.skip_pill_min", 99)
    assert not bt.can_skip_pill(p)
    await tune("gates.root_base.五灵根", 10)
    assert bt.calc_zhuji_breakthrough_rate(five) == 10 + 25
    await tune("gates.huaying.base_factor", 1.0)
    assert bt.calc_huaying_breakthrough_rate(five) == 10 + 20
    await tune("gates.cap", 50)
    assert bt.calc_zhuji_breakthrough_rate(p) == 50


async def test_装备_品质倍数_词缀数_随机品质(db):
    from utils import equipment as eq
    random.seed(1)
    plain = eq.generate_equipment(tier=0, quality="普通", slot="武器")
    await tune("equipment.quality_mult.传说", 60)
    big = eq.generate_equipment(tier=0, quality="传说", slot="武器")
    assert sum(big["stats"].values()) > sum(plain["stats"].values()) * 10
    await tune("equipment.affix_count.普通.1", 3)
    await tune("equipment.affix_count.普通.0", 3)
    assert eq.generate_equipment(tier=0, quality="普通", slot="武器")["name"].count("·") >= 3
    for q in ("普通", "精良", "稀有", "史诗"):
        await tune(f"equipment.random_quality_weights.{q}", 0)
    assert {eq.generate_equipment(tier=0, slot="武器")["quality"] for _ in range(10)} == {"传说"}


async def test_任务_掉落品质_死亡率_扣寿元(db, monkeypatch):
    assert rules.get("quests.drops.传说.史诗") == 35
    await tune("quests.death.cap", 0.01)
    await tune("quests.escape_loss.精英", 7)
    await tune("quests.drops.普通.精良", 0)
    assert rules.section("quests")["escape_loss"]["精英"] == 7 and rules.section("quests")["drops"]["普通"] == {"普通": 70, "精良": 0}


async def test_签到_赌坊_奇遇_走同一套调参(db):
    from utils import adventure_chain, checkin, gamble
    await tune_file("checkin_config.json", "category_weights.spirit_stones", 100)
    assert checkin.cfg()["category_weights"]["spirit_stones"] == 100
    await tune_file("gamble_config.json", "daily_limit", 3)
    assert gamble.daily_limit() == 3
    await tune_file("gamble_config.json", "outcomes.0.weight", 2)
    assert dict(gamble.outcome_probs())["大赢"] > 1.5
    ok, msg = await hub.set_value("gamble_config.json", "outcomes.0.multiplier", "50")
    assert not ok and "期望倍率" in msg
    await tune_file("adventure_chains_config.json", "trigger_chance.spirit_fox", 0.5)
    assert adventure_chain.get_trigger_chance("spirit_fox", 0.1) == 0.5
    ok, msg = await hub.set_value("adventure_chains_config.json", "trigger_chance.spirit_fox", "2")
    assert not ok


async def tune_file(file: str, path: str, value) -> None:
    ok, msg = await hub.set_value(file, path, str(value))
    assert ok, msg


@pytest.fixture(autouse=True)
def clean_other_hub_files():
    yield
    hub._overrides.clear()
    for n in hub.REGISTRY:
        hub.reload_module(n)


# ---- 公共事件：灵雨 / 万宝楼 -----------------------------------------------

async def test_灵雨_说明文字跟着调参变(db):
    from utils.views import spirit_rain as sv
    assert "最多参与 **2 次**" in sv.spirit_rain_desc() and "(30% 概率)" not in sv.spirit_rain_desc() and "30% 概率" in sv.spirit_rain_desc()
    await tune("spirit_rain.max_activities", 3)
    await tune("spirit_rain.activity_cooldown_seconds", 1200)
    await tune("spirit_rain.temper_min_physique", 9)
    await tune("spirit_rain.beast_tide_chance", 0.5)
    await tune("spirit_rain.defense.rank1.equipment", 3)
    await tune("spirit_rain.defense.rank1.rep", 99)
    d = sv.spirit_rain_desc()
    assert "最多参与 **3 次**" in d and "**20 分钟**" in d and "体魄 ≥ 9" in d and "50% 概率" in d and "3件稀有装备" in d and "声望 +99" in d


async def test_灵雨_活动奖励范围可调(db):
    from utils.events.public import spirit_rain as sr
    await add(db, "1", stones=0, cultivation=0)
    await tune("spirit_rain.crystal.stones.1", 1000)               # 范围要先抬高上限，再抬下限
    await tune("spirit_rain.crystal.stones.0", 1000)
    await tune("spirit_rain.crystal.herb_chance", 0)
    msg, stones = await sr.grant_activity("1", "crystal", {}, "e")
    assert stones == 1000 and "1000 灵石" in msg
    await tune("spirit_rain.enlighten.cultivation.1", 777)
    await tune("spirit_rain.enlighten.cultivation.0", 777)
    msg, _ = await sr.grant_activity("1", "enlighten", {}, "e")
    assert "修为 +777" in msg
    await tune("spirit_rain.temper.cultivation.1", 555)
    await tune("spirit_rain.temper.cultivation.0", 555)
    await tune("spirit_rain.temper.physique_chance", 1)
    msg, _ = await sr.grant_activity("1", "temper", {}, "e")
    assert "修为 +555" in msg and "体魄 +1" in msg


async def test_万宝楼_说明和数值跟着调参变(db):
    from utils.events.public import wanbao as wb
    from utils.views import wanbao_public as wp
    assert wb.listing_fee() == 300 and "**300 灵石** 手续费" in wp.wanbao_desc() and "**8 件**" in wp.wanbao_desc()
    await tune("wanbao.listing_fee", 50)
    await tune("wanbao.commission", 0.1)
    await tune("wanbao.lot_seconds", 180)
    await tune("wanbao.official.techniques", 1)
    await tune("wanbao.max_lots", 30)
    d = wp.wanbao_desc()
    assert "**50 灵石** 手续费" in d and "**10%**" in d and "**3 分钟**" in d and "**7 件**" in d and "全场上限 **30 件**" in d
    assert wb.listing_fee() == 50 and wb.commission_rate() == 0.1 and wb.lot_duration() == 180


async def test_万宝楼_官方拍品件数和起拍价可调(db):
    from utils.events.public import wanbao as wb
    assert len(wb.generate_house_lots()) == 8
    await tune("wanbao.official.techniques", 0)
    await tune("wanbao.official.equipment", 0)
    await tune("wanbao.official.pills", 1)
    await tune("wanbao.official.materials", 1)
    lots = wb.generate_house_lots()
    assert len(lots) == 2 and {l["item_type"] for l in lots} == {"item"}
    for r in ("普通", "稀有", "珍贵", "绝世"):
        await tune(f"wanbao.start_price.pill.{r}", 7)
    assert all(l["start_price"] == 7 for l in wb.generate_house_lots() if l["item_name"] in __import__("utils.items", fromlist=["ITEMS"]).ITEMS and __import__("utils.items", fromlist=["ITEMS"]).ITEMS[l["item_name"]].get("type") == "pill")


async def test_万宝楼_上架数量限制可调(db):
    from utils.events.public import wanbao as wb
    await add(db, "1", stones=10_000)
    a = await wb.get_or_create_auction("2026-01-01")
    await tune("wanbao.max_player_lots", 1)
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        s.add(D.Inventory(discord_id="1", item_id="灵芝草", quantity=10))
        await s.commit()
    assert (await wb.list_item(a["auction_id"], "1", "灵芝草", 1, 10))[0]
    ok, msg = await wb.can_list_item("1", a["auction_id"])
    assert not ok and "最多上架 1 件" in msg
