"""连环奇遇测试（utils/adventure_chain.py、utils/views/adventure_chain.py、奇遇数据）。

结构：
  A 进度存取  B 奖励发放  C 触发条件  D 狐符  E 触发概率配置
  F 奇遇数据校验  G 章节面板  H 触发入口  I 三条链完整通关

F 值得单独强调：`apply_chain_rewards` 对不认识的奖励键、`check_chain_trigger` 对不认识的触发条件
都是**静默忽略** —— 数据里手误写成 `fortunee`，奖励就悄悄失效，或者触发条件失效让奇遇人人都能碰上。
所以数据本身要有测试守着。
"""

import asyncio
import json

import pytest

from cogs.explore import _try_adventure_chain
from tests.conftest import make_player
from tests.discord_fakes import FakeInteraction, FakeUser
from utils import adventure_chain as ac
from utils.events.adventure_chains import ALL_CHAINS
from utils.realms import REALMS
from utils.views.adventure_chain import ChainStageView, _pick_best_choice, choice_available

UID = "1"
FOX = next(c for c in ALL_CHAINS if c["id"] == "spirit_fox")


async def _add_player(db, uid=UID, **fields):
    D = db["db_async"]
    p = make_player(D, uid, stones=100)
    for k, v in fields.items():
        setattr(p, k, v)
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def _row(db, uid=UID):
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        return await s.get(D.Player, uid)


# =============================================================================
# A. 进度存取
# =============================================================================

async def test_没有进度时是空字典(db):
    assert await ac.get_chain_progress(UID) == {}
    assert await ac.get_stage(UID, "spirit_fox") == 0
    assert await ac.is_completed(UID, "spirit_fox") is False


async def test_保存后能原样读回_中文不被转义(db):
    await ac.save_chain_progress(UID, {"spirit_fox": {"stage": 2, "completed": False, "data": {"名字": "九尾"}}})

    got = await ac.get_chain_progress(UID)

    assert got["spirit_fox"]["data"] == {"名字": "九尾"}
    D = db["db_async"]
    from sqlalchemy import text
    async with D.AsyncSessionLocal() as s:
        raw = (await s.execute(text("SELECT progress FROM adventure_progress WHERE discord_id=:u"), {"u": UID})).scalar()
    assert "九尾" in raw                                   # ensure_ascii=False


async def test_重复保存是覆盖不是新增(db):
    await ac.save_chain_progress(UID, {"a": {"stage": 1}})
    await ac.save_chain_progress(UID, {"b": {"stage": 5}})

    assert await ac.get_chain_progress(UID) == {"b": {"stage": 5}}
    D = db["db_async"]
    from sqlalchemy import text
    async with D.AsyncSessionLocal() as s:
        n = (await s.execute(text("SELECT COUNT(*) FROM adventure_progress WHERE discord_id=:u"), {"u": UID})).scalar()
    assert n == 1


async def test_进度按玩家隔离(db):
    await ac.advance_stage("p1", "spirit_fox")
    assert await ac.get_stage("p1", "spirit_fox") == 1
    assert await ac.get_stage("p2", "spirit_fox") == 0


async def test_推进阶段_从零开始逐级加一(db):
    await ac.advance_stage(UID, "spirit_fox")
    await ac.advance_stage(UID, "spirit_fox")
    assert await ac.get_stage(UID, "spirit_fox") == 2
    assert await ac.is_completed(UID, "spirit_fox") is False


async def test_推进阶段_额外数据合并而不是覆盖(db):
    await ac.advance_stage(UID, "spirit_fox", {"a": 1})
    await ac.advance_stage(UID, "spirit_fox", {"b": 2})
    assert (await ac.get_chain_progress(UID))["spirit_fox"]["data"] == {"a": 1, "b": 2}


async def test_几条链的进度互不影响(db):
    await ac.advance_stage(UID, "spirit_fox")
    await ac.advance_stage(UID, "ancient_tomb")
    await ac.advance_stage(UID, "ancient_tomb")
    assert await ac.get_stage(UID, "spirit_fox") == 1
    assert await ac.get_stage(UID, "ancient_tomb") == 2


async def test_标记完成_保留阶段号(db):
    await ac.advance_stage(UID, "spirit_fox")
    await ac.mark_completed(UID, "spirit_fox")
    assert await ac.is_completed(UID, "spirit_fox") is True
    assert await ac.get_stage(UID, "spirit_fox") == 1


async def test_没推进过也能直接标记完成(db):
    await ac.mark_completed(UID, "spirit_fox")
    assert await ac.is_completed(UID, "spirit_fox") is True
    assert await ac.get_stage(UID, "spirit_fox") == 0


# =============================================================================
# B. 奖励发放
# =============================================================================

async def test_属性奖励逐项入账(db):
    await _add_player(db, fortune=5, soul=5, spirit_stones=100, lifespan=50, cultivation=0)

    await ac.apply_chain_rewards(UID, {"fortune": 2, "soul": 1, "spirit_stones": 500, "lifespan": 30, "cultivation": 300})

    p = await _row(db)
    assert (p.fortune, p.soul, p.spirit_stones, p.lifespan, p.cultivation) == (7, 6, 600, 80, 300)


async def test_负数奖励是扣减_但不会扣成负数(db):
    await _add_player(db, spirit_stones=100, lifespan=5)
    await ac.apply_chain_rewards(UID, {"spirit_stones": -999, "lifespan": -2})
    p = await _row(db)
    assert p.spirit_stones == 0 and p.lifespan == 3


async def test_空奖励不报错(db):
    await _add_player(db)
    await ac.apply_chain_rewards(UID, {})
    assert (await _row(db)).spirit_stones == 100


async def test_功法奖励_记入功法列表_初始为入门且未装备(db):
    await _add_player(db)
    await ac.apply_chain_rewards(UID, {"technique": "九尾灵狐诀"})
    techs = json.loads((await _row(db)).techniques)
    assert techs == [{"name": "九尾灵狐诀", "stage": "入门", "equipped": False}]


async def test_功法奖励_已有同名功法不重复发(db):
    await _add_player(db, techniques=json.dumps(["九尾灵狐诀", {"name": "别的功法"}]))
    await ac.apply_chain_rewards(UID, {"technique": "九尾灵狐诀"})
    assert json.loads((await _row(db)).techniques) == ["九尾灵狐诀", {"name": "别的功法"}]


async def test_功法奖励_保留已有功法(db):
    await _add_player(db, techniques=json.dumps([{"name": "旧功法", "stage": "小成", "equipped": True}]))
    await ac.apply_chain_rewards(UID, {"technique": "新功法"})
    names = [t["name"] for t in json.loads((await _row(db)).techniques)]
    assert names == ["旧功法", "新功法"]


async def test_称号奖励_记入titles_不重复_不动其它buff(db):
    await _add_player(db, active_buffs=json.dumps({"cultivation_speed_bonus": {"value": 20}}))

    await ac.apply_chain_rewards(UID, {"title": "灵狐之友"})
    await ac.apply_chain_rewards(UID, {"title": "灵狐之友"})
    await ac.apply_chain_rewards(UID, {"title": "古墓行者"})

    buffs = json.loads((await _row(db)).active_buffs)
    assert buffs["titles"] == ["灵狐之友", "古墓行者"]
    assert buffs["cultivation_speed_bonus"] == {"value": 20}


async def test_特殊buff奖励_写入并保留原有buff(db):
    await _add_player(db, active_buffs=json.dumps({"titles": ["甲"]}))
    await ac.apply_chain_rewards(UID, {"special_buff": {"key": "fox_charm", "value": 1}})
    buffs = json.loads((await _row(db)).active_buffs)
    assert buffs == {"titles": ["甲"], "fox_charm": 1}


async def test_不认识的奖励键被静默忽略(db):
    """记录现状：手误的奖励键不会报错也不会生效 —— 所以才需要 F 组的数据校验。"""
    await _add_player(db, fortune=5)
    await ac.apply_chain_rewards(UID, {"fortunee": 99, "不存在": 1})
    assert (await _row(db)).fortune == 5


async def test_奖励发给不存在的玩家不报错(db):
    await ac.apply_chain_rewards("nobody", {"fortune": 1, "technique": "x", "title": "y",
                                           "special_buff": {"key": "k", "value": 1}})


async def test_奇遇送的狐符_能被突破逻辑认出来并救命(db):
    """跨模块的闭环：九尾灵狐链发出的 special_buff 就是 try_fox_charm 要找的东西。"""
    reward = next(c["rewards"]["special_buff"] for st in FOX["stages"] for c in st["choices"]
                  if "special_buff" in c.get("rewards", {}) and c["rewards"]["special_buff"]["key"] == "fox_charm")
    await _add_player(db, lifespan=0)
    await ac.apply_chain_rewards(UID, {"special_buff": reward})
    D = db["db_async"]

    async with D.AsyncSessionLocal() as s:
        p = await s.get(D.Player, UID)
        saved = await ac.try_fox_charm(UID, p)
        await s.commit()

    assert saved is True
    after = await _row(db)
    assert after.lifespan == 1 and "fox_charm" not in json.loads(after.active_buffs)


# =============================================================================
# C. 触发条件
# =============================================================================

def _chain(*triggers):
    return {"id": "t", "stages": [{"trigger": t, "choices": []} for t in triggers]}


@pytest.mark.parametrize("trigger,player,expected", [
    ({}, {}, True),
    ({"city": "灵虚城"}, {"current_city": "灵虚城"}, True),
    ({"city": "灵虚城"}, {"current_city": "别处"}, False),
    ({"city": ["甲", "乙"]}, {"current_city": "乙"}, True),
    ({"city": ["甲", "乙"]}, {"current_city": "丙"}, False),
    ({"city": "甲"}, {}, False),
    ({"min_realm_index": 10}, {"realm": REALMS[10]}, True),
    ({"min_realm_index": 10}, {"realm": REALMS[9]}, False),
    ({"min_realm_index": 10}, {"realm": REALMS[30]}, True),
    ({"min_realm_index": 1}, {}, False),                            # 缺 realm 按炼气期1层(0)算
    ({"fortune": 7}, {"fortune": 7}, True),
    ({"fortune": 7}, {"fortune": 6}, False),
    ({"fortune": 7}, {}, False),
    ({"comprehension": 3, "soul": 4}, {"comprehension": 3, "soul": 4}, True),
    ({"comprehension": 3, "soul": 4}, {"comprehension": 3, "soul": 3}, False),
    ({"sect": "any"}, {"sect": "青云宗"}, True),
    ({"sect": "any"}, {"sect": None}, False),
    ({"sect": "any"}, {}, False),
    ({"sect": "青云宗"}, {"sect": "青云宗"}, True),
    ({"sect": "青云宗"}, {"sect": "别宗"}, False),
    ({"min_rebirth": 1}, {"rebirth_count": 1}, True),
    ({"min_rebirth": 2}, {"rebirth_count": 1}, False),
    ({"min_rebirth": 1}, {}, False),
])
def test_触发条件(trigger, player, expected):
    assert ac.check_chain_trigger(_chain(trigger), player, 0) is expected


def test_触发条件_多个条件要同时满足():
    chain = _chain({"city": "甲", "fortune": 7, "min_realm_index": 5})
    ok = {"current_city": "甲", "fortune": 7, "realm": REALMS[5]}
    assert ac.check_chain_trigger(chain, ok, 0) is True
    for broken in ({"current_city": "乙"}, {"fortune": 6}, {"realm": REALMS[4]}):
        assert ac.check_chain_trigger(chain, {**ok, **broken}, 0) is False


def test_阶段号越界不触发():
    chain = _chain({}, {})
    assert ac.check_chain_trigger(chain, {}, 1) is True
    assert ac.check_chain_trigger(chain, {}, 2) is False


def test_每个阶段按自己的条件判():
    chain = _chain({"fortune": 5}, {"fortune": 9})
    assert ac.check_chain_trigger(chain, {"fortune": 6}, 0) is True
    assert ac.check_chain_trigger(chain, {"fortune": 6}, 1) is False


def test_可用奇遇_跳过已完成_带出当前阶段():
    c1, c2, c3 = ({"id": n, "stages": [{"trigger": {}}, {"trigger": {}}]} for n in ("a", "b", "c"))
    progress = {"a": {"stage": 1, "completed": False}, "b": {"stage": 0, "completed": True}}

    got = ac.get_available_chains([c1, c2, c3], {}, progress)

    assert [(c["id"], stage) for c, stage in got] == [("a", 1), ("c", 0)]


def test_可用奇遇_条件不满足的不在其中():
    chain = {"id": "a", "stages": [{"trigger": {"fortune": 9}}]}
    assert ac.get_available_chains([chain], {"fortune": 1}, {}) == []


def test_可用奇遇_阶段走完但未标记完成_不再出现():
    chain = {"id": "a", "stages": [{"trigger": {}}]}
    assert ac.get_available_chains([chain], {}, {"a": {"stage": 1, "completed": False}}) == []


# =============================================================================
# D. 狐符
# =============================================================================

class _P:
    def __init__(self, buffs="{}", lifespan=0):
        self.active_buffs = buffs
        self.lifespan = lifespan


async def test_有狐符_寿元救回一年_狐符消耗_其它buff保留():
    p = _P(json.dumps({"fox_charm": 1, "titles": ["甲"]}))
    assert await ac.try_fox_charm(UID, p) is True
    assert p.lifespan == 1
    assert json.loads(p.active_buffs) == {"titles": ["甲"]}


async def test_字典形式的狐符也认():
    p = _P(json.dumps({"fox_charm": {"value": 1}}))
    assert await ac.try_fox_charm(UID, p) is True


@pytest.mark.parametrize("buffs", ["{}", None, "", json.dumps({"fox_charm": 0}), json.dumps({"别的": 1})])
async def test_没有狐符_什么都不变(buffs):
    p = _P(buffs, lifespan=0)
    assert await ac.try_fox_charm(UID, p) is False
    assert p.lifespan == 0


# =============================================================================
# E. 触发概率配置
# =============================================================================

def test_概率取配置文件里的值():
    cfg = json.load(open(ac._CONFIG_PATH, encoding="utf-8"))["trigger_chance"]
    assert ac.get_trigger_chance("spirit_fox", 0.5) == cfg["spirit_fox"]


def test_配置里没有的链用默认值():
    assert ac.get_trigger_chance("不存在的链", 0.123) == 0.123


def test_配置文件缺失或损坏_退回默认值而不是炸(monkeypatch, tmp_path):
    monkeypatch.setattr(ac, "_CONFIG_PATH", str(tmp_path / "nope.json"))
    assert ac.get_trigger_chance("spirit_fox", 0.5) == 0.5
    bad = tmp_path / "bad.json"
    bad.write_text("{这不是json")
    monkeypatch.setattr(ac, "_CONFIG_PATH", str(bad))
    assert ac.get_trigger_chance("spirit_fox", 0.5) == 0.5


# =============================================================================
# F. 奇遇数据校验
# =============================================================================

SUPPORTED_TRIGGERS = {"city", "min_realm_index", "comprehension", "physique", "fortune",
                      "bone", "soul", "sect", "min_rebirth"}
SUPPORTED_REWARDS = {"spirit_stones", "lifespan", "cultivation", "comprehension", "physique",
                     "fortune", "bone", "soul", "reputation", "technique", "title", "special_buff"}
CONDITION_STATS = {"comprehension", "physique", "fortune", "bone", "soul"}


def _all_choices():
    for chain in ALL_CHAINS:
        for i, stage in enumerate(chain["stages"]):
            for c in stage["choices"]:
                yield chain, i, stage, c


def test_奇遇id不重复():
    ids = [c["id"] for c in ALL_CHAINS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("chain", ALL_CHAINS, ids=lambda c: c["id"])
def test_奇遇结构完整(chain):
    assert chain["id"] and chain["name"] and chain["stages"]
    for i, stage in enumerate(chain["stages"]):
        assert stage["title"] and stage["desc"], f"{chain['id']} 阶段{i} 缺标题或正文"
        assert isinstance(stage["trigger"], dict)
        assert stage["choices"], f"{chain['id']} 阶段{i} 没有选项"
        for c in stage["choices"]:
            assert c["label"] and c["flavor"]
            assert isinstance(c["rewards"], dict) and isinstance(c["advance"], bool)


@pytest.mark.parametrize("chain", ALL_CHAINS, ids=lambda c: c["id"])
def test_每个阶段都有推进的路_且只有最后阶段能完结(chain):
    last = len(chain["stages"]) - 1
    for i, stage in enumerate(chain["stages"]):
        advancing = [c for c in stage["choices"] if c["advance"]]
        assert advancing, f"{chain['id']} 阶段{i} 没有任何能推进的选项，玩家会卡死在这里"
        finals = [c for c in stage["choices"] if c.get("is_final")]
        if i < last:
            assert not finals, f"{chain['id']} 阶段{i} 不是最后阶段却能完结"
        else:
            assert finals, f"{chain['id']} 最后阶段没有能完结的选项，这条奇遇永远通不了关"
            assert all(c["advance"] for c in finals), "完结选项必须同时 advance，否则不会被结算"


def test_触发条件只用系统认得的键():
    """认不得的键会被 check_chain_trigger 静默忽略 —— 等于条件没写，人人都能触发。"""
    used = {k for chain in ALL_CHAINS for st in chain["stages"] for k in st["trigger"]}
    assert used <= SUPPORTED_TRIGGERS, f"未知触发条件：{used - SUPPORTED_TRIGGERS}"


def test_奖励只用系统认得的键():
    """认不得的键会被 apply_chain_rewards 静默忽略 —— 剧情写了奖励，玩家什么也没拿到。"""
    used = {k for _c, _i, _s, ch in _all_choices() for k in ch["rewards"]}
    assert used <= SUPPORTED_REWARDS, f"未知奖励键：{used - SUPPORTED_REWARDS}"


def test_奖励值的类型对得上():
    for chain, i, _s, c in _all_choices():
        for k, v in c["rewards"].items():
            where = f"{chain['id']} 阶段{i}「{c['label']}」{k}"
            if k in ("technique", "title"):
                assert isinstance(v, str) and v, where
            elif k == "special_buff":
                assert set(v) == {"key", "value"}, where
            else:
                assert isinstance(v, int) and not isinstance(v, bool), where


def test_选项条件指向真实属性():
    for chain, i, _s, c in _all_choices():
        cond = c.get("condition")
        if cond:
            assert cond["stat"] in CONDITION_STATS and isinstance(cond["val"], int), f"{chain['id']} 阶段{i}"


def test_每个阶段都有一个无条件且能推进的选项():
    """纯门槛选项（只有带条件的版本）属性不够就不能选，所以必须永远留一条人人能走的路，
    否则属性低的玩家会被卡死在某个阶段。"""
    for chain in ALL_CHAINS:
        for i, stage in enumerate(chain["stages"]):
            assert any(not c.get("condition") and c["advance"] for c in stage["choices"]), (
                f"{chain['id']} 阶段{i} 没有人人能选的推进选项，低属性玩家会卡死")


def test_纯门槛选项的清单_改数据时要有意识():
    """记录现状：这些选项只有带条件的版本。属性不够时按钮禁用（见 G 组）。
    清单变了说明有人加/删了门槛选项 —— 确认是有意的再更新这里。"""
    gated = sorted(
        (chain["id"], i, label)
        for chain in ALL_CHAINS for i, stage in enumerate(chain["stages"])
        for label in {c["label"] for c in stage["choices"]}
        if all(c.get("condition") for c in stage["choices"] if c["label"] == label)
    )
    assert len(gated) == 6, gated


def test_触发概率配置里的链都存在_且概率合理():
    cfg = json.load(open(ac._CONFIG_PATH, encoding="utf-8"))["trigger_chance"]
    ids = {c["id"] for c in ALL_CHAINS}
    assert set(cfg) <= ids, f"配置里有不存在的链：{set(cfg) - ids}"
    assert all(0 < v < 1 for v in cfg.values())


def test_每条链都在配置里有触发概率():
    cfg = json.load(open(ac._CONFIG_PATH, encoding="utf-8"))["trigger_chance"]
    assert {c["id"] for c in ALL_CHAINS} <= set(cfg), "没配概率的链会退回数据里的默认值，通常高得多"


# =============================================================================
# G. 章节面板
# =============================================================================

def _view(chain=FOX, stage_idx=0, player=None):
    player = player or {"discord_id": UID, "fortune": 9, "comprehension": 9, "soul": 9}
    return ChainStageView(author=FakeUser(id=1), chain=chain, stage_idx=stage_idx, player=player, cog=None)


def _button(view, label):
    return next(b for b in view.children if b.label == label)


def test_面板按选项标签生成按钮_同名只出一个():
    chain = {"id": "t", "name": "t", "stages": [{"title": "s", "choices": [
        {"label": "甲", "condition": {"stat": "soul", "val": 9}}, {"label": "甲", "condition": None},
        {"label": "乙", "condition": None}]}]}
    view = _view(chain)
    assert [b.label for b in view.children] == ["甲", "乙"]


async def test_别人点不动这个奇遇面板(db):
    view = _view()
    intruder = FakeInteraction(user_id=999)
    assert await view.interaction_check(intruder) is False
    assert intruder.said("这不是你的奇遇")
    assert await view.interaction_check(FakeInteraction(user_id=1)) is True


def test_择优_条件满足的先上_否则无条件的_再否则最后一个():
    hi = {"label": "x", "condition": {"stat": "soul", "val": 8}, "tag": "hi"}
    base = {"label": "x", "condition": None, "tag": "base"}
    cond_only = [{"label": "y", "condition": {"stat": "soul", "val": 8}, "tag": "a"},
                 {"label": "y", "condition": {"stat": "soul", "val": 9}, "tag": "b"}]
    assert _pick_best_choice([hi, base], {"soul": 8})["tag"] == "hi"
    assert _pick_best_choice([hi, base], {"soul": 7})["tag"] == "base"
    assert _pick_best_choice([base, hi], {"soul": 99})["tag"] == "hi"           # 有条件的优先于排在前面的兜底
    assert _pick_best_choice(cond_only, {"soul": 1})["tag"] == "b"              # 全不满足又没兜底：取最后一个


async def test_点推进选项_发奖励并进入下一阶段(db):
    await _add_player(db, fortune=9)
    view = _view()
    it = FakeInteraction(user_id=1)

    await _button(view, "跟上去").callback(it)

    assert (await _row(db)).fortune == 10                     # 奖励 fortune +1
    assert await ac.get_stage(UID, "spirit_fox") == 1
    assert await ac.is_completed(UID, "spirit_fox") is False
    assert it.last.embed.title.startswith(f"✦ {FOX['name']} · 九尾灵狐·初遇")
    assert it.last.embed.footer.text is None
    assert view.is_finished()


async def test_点不推进的选项_不发奖励也不进阶段(db):
    await _add_player(db, fortune=9)
    view = _view()
    it = FakeInteraction(user_id=1)

    await _button(view, "停下来，不去追").callback(it)

    assert await ac.get_stage(UID, "spirit_fox") == 0
    assert (await _row(db)).fortune == 9
    assert it.said("那双琥珀色的眼睛")


async def test_点完结选项_标记完成并提示奇遇完成(db):
    await _add_player(db, soul=9, comprehension=9)
    last = len(FOX["stages"]) - 1
    final = next(c for c in FOX["stages"][last]["choices"] if c.get("is_final"))
    view = _view(stage_idx=last)
    it = FakeInteraction(user_id=1)

    await _button(view, final["label"]).callback(it)

    assert await ac.is_completed(UID, "spirit_fox") is True
    assert "奇遇完成" in it.last.embed.footer.text


def _synthetic_chain():
    """同名选项『按条件择优』（有条件版本 + 无条件兜底），以及一个纯门槛选项。"""
    return {"id": "syn", "name": "【合成】", "stages": [{"title": "试炼", "desc": "d", "trigger": {}, "choices": [
        {"label": "参悟", "condition": {"stat": "soul", "val": 8}, "flavor": "你一眼看穿", "rewards": {"soul": 2}, "advance": True},
        {"label": "参悟", "condition": None, "flavor": "你勉强看懂", "rewards": {}, "advance": True},
        {"label": "硬闯", "condition": None, "flavor": "你冲了进去", "rewards": {}, "advance": True},
        {"label": "读碑", "condition": {"stat": "comprehension", "val": 7}, "flavor": "你读懂了碑文",
         "rewards": {"cultivation": 1000}, "advance": True, "is_final": True},
    ]}]}


async def test_同名选项按属性择优_够了走好结果_不够走兜底(db):
    chain = _synthetic_chain()
    await _add_player(db)

    strong = FakeInteraction(user_id=1)
    await _button(_view(chain, player={"discord_id": UID, "soul": 8}), "参悟").callback(strong)
    assert strong.last.embed.description == "你一眼看穿"

    weak = FakeInteraction(user_id=1)
    await _button(_view(chain, player={"discord_id": UID, "soul": 7}), "参悟").callback(weak)
    assert weak.last.embed.description == "你勉强看懂"


def test_选项可用性():
    gated = [{"label": "x", "condition": {"stat": "soul", "val": 8}}]
    with_fallback = gated + [{"label": "x", "condition": None}]
    assert choice_available(gated, {"soul": 8}) is True
    assert choice_available(gated, {"soul": 7}) is False
    assert choice_available(gated, {}) is False
    assert choice_available(with_fallback, {"soul": 0}) is True            # 有兜底人人可选
    assert choice_available([{"label": "y", "condition": None}], {}) is True


def test_纯门槛选项_属性不够时按钮禁用并注明要求():
    chain = _synthetic_chain()
    view = _view(chain, player={"discord_id": UID, "comprehension": 6})
    by_label = {b.label: b for b in view.children}

    assert by_label["参悟"].disabled is False and by_label["硬闯"].disabled is False
    gated = next(b for b in view.children if b.label.startswith("读碑"))
    assert gated.disabled is True and "需悟性≥7" in gated.label


def test_纯门槛选项_属性够了按钮可用且标签干净():
    chain = _synthetic_chain()
    view = _view(chain, player={"discord_id": UID, "comprehension": 7})
    gated = _button(view, "读碑")
    assert gated.disabled is False


async def test_纯门槛选项_属性不够硬点也拿不到奖励(db):
    """B10 回归：条件曾经形同虚设 —— 悟性 1 的玩家点「需悟性7」的选项，照样拿全部奖励并通关。
    这里绕过禁用状态直接调回调（比如过期面板、手工构造的交互）。"""
    chain = _synthetic_chain()
    await _add_player(db, cultivation=0)
    view = _view(chain, player={"discord_id": UID, "comprehension": 1})
    btn = next(b for b in view.children if b.label.startswith("读碑"))
    it = FakeInteraction(user_id=1)

    await btn.callback(it)

    assert it.said("条件不足") and it.said("需悟性≥7")
    assert (await _row(db)).cultivation == 0
    assert await ac.is_completed(UID, "syn") is False
    assert not view.is_finished()                           # 被拒绝不算用掉这次机会，玩家可以改选别的


async def test_真实数据里的纯门槛选项_低属性玩家点不动(db):
    """古墓最后一幕：『先读完石碑上的文字』需悟性 7，奖励比无条件的『打开玉匣』丰厚得多。"""
    tomb = next(c for c in ALL_CHAINS if c["id"] == "ancient_tomb")
    last = len(tomb["stages"]) - 1
    await _add_player(db, comprehension=1, cultivation=0)
    view = _view(tomb, stage_idx=last, player={"discord_id": UID, "comprehension": 1})
    btn = next(b for b in view.children if b.label.startswith("先读完石碑上的文字"))
    assert btn.disabled is True

    await btn.callback(FakeInteraction(user_id=1))

    assert (await _row(db)).cultivation == 0
    assert await ac.is_completed(UID, "ancient_tomb") is False


async def test_点过之后按钮全部禁用_面板作废(db):
    await _add_player(db)
    view = _view()
    await _button(view, "跟上去").callback(FakeInteraction(user_id=1))
    assert all(b.disabled for b in view.children) and view.is_finished()


async def test_连点_奖励只发一次_阶段只推进一格(db):
    """两次点击几乎同时到达：defer 要走网络，两个回调会在 view.stop() 之前同时越过入口。
    曾经因此奖励发两遍；这里用会让出事件循环的 defer 模拟真实的网络延迟。"""
    await _add_player(db, fortune=9)
    view = _view()
    btn = _button(view, "跟上去")
    its = [FakeInteraction(user_id=1), FakeInteraction(user_id=1)]
    for it in its:
        real_defer = it.response.defer

        async def _slow(real=real_defer, **kw):
            await asyncio.sleep(0.01)
            await real(**kw)
        it.response.defer = _slow

    await asyncio.gather(btn.callback(its[0]), btn.callback(its[1]))

    assert (await _row(db)).fortune == 10                       # 奖励 +1，不是 +2
    assert await ac.get_stage(UID, "spirit_fox") == 1           # 只推进一格
    results = [m for it in its for m in it.messages if m.embed is not None]
    assert len(results) == 1                                    # 只发一份结果


# =============================================================================
# H. 触发入口（cogs/explore.py::_try_adventure_chain）
# =============================================================================

def _always(monkeypatch, roll):
    import random
    monkeypatch.setattr(random, "random", lambda: roll)
    monkeypatch.setattr(random, "sample", lambda seq, k: list(seq))


async def test_触发入口_没有可用奇遇时返回空(db):
    got = await _try_adventure_chain({"discord_id": UID, "fortune": 1, "realm": REALMS[0], "current_city": "灵虚城"})
    assert got == (None, -1)


async def test_触发入口_骰中就返回那条链和阶段(db, monkeypatch):
    _always(monkeypatch, 0.0)
    player = {"discord_id": UID, "fortune": 9, "realm": REALMS[0], "current_city": "灵虚城"}

    chain, stage = await _try_adventure_chain(player)

    assert chain["id"] == "spirit_fox" and stage == 0


async def test_触发入口_骰不中返回空(db, monkeypatch):
    _always(monkeypatch, 0.999999)
    player = {"discord_id": UID, "fortune": 9, "realm": REALMS[0], "current_city": "灵虚城"}
    assert await _try_adventure_chain(player) == (None, -1)


async def test_触发入口_已通关的链不再触发(db, monkeypatch):
    _always(monkeypatch, 0.0)
    await ac.mark_completed(UID, "spirit_fox")
    player = {"discord_id": UID, "fortune": 9, "realm": REALMS[0], "current_city": "灵虚城"}
    assert await _try_adventure_chain(player) == (None, -1)


async def test_触发入口_从玩家当前阶段接着往下(db, monkeypatch):
    _always(monkeypatch, 0.0)
    await ac.advance_stage(UID, "spirit_fox")
    await ac.advance_stage(UID, "spirit_fox")
    player = {"discord_id": UID, "fortune": 9, "realm": REALMS[0], "current_city": "灵虚城"}

    chain, stage = await _try_adventure_chain(player)

    assert (chain["id"], stage) == ("spirit_fox", 2)


# =============================================================================
# I. 三条链从头到尾走一遍
# =============================================================================

def _player_meeting(chain):
    """造一个满足这条链所有阶段触发条件、且属性拉满的玩家。"""
    p = {"discord_id": UID, "comprehension": 99, "physique": 99, "fortune": 99, "bone": 99, "soul": 99,
         "current_city": "灵虚城", "realm": REALMS[0], "sect": None, "rebirth_count": 0}
    for st in chain["stages"]:
        t = st["trigger"]
        if "city" in t:
            p["current_city"] = t["city"][0] if isinstance(t["city"], list) else t["city"]
        if "min_realm_index" in t:
            p["realm"] = REALMS[max(REALMS.index(p["realm"]), t["min_realm_index"])]
        if "sect" in t:
            p["sect"] = "青云宗" if t["sect"] == "any" else t["sect"]
        if "min_rebirth" in t:
            p["rebirth_count"] = max(p["rebirth_count"], t["min_rebirth"])
    return p


@pytest.mark.parametrize("chain", ALL_CHAINS, ids=lambda c: c["id"])
async def test_整条奇遇能从头通到尾(db, chain):
    """每个阶段都挑一个能推进的选项点下去：阶段逐级前进，最后一步完结，期间每一步都发了奖励。"""
    player = _player_meeting(chain)
    await _add_player(db, **{k: v for k, v in player.items() if k != "discord_id"},
                      lifespan=100, spirit_stones=0, cultivation=0)

    for stage_idx, stage in enumerate(chain["stages"]):
        assert ac.check_chain_trigger(chain, player, stage_idx), f"阶段{stage_idx} 的触发条件对满足它的玩家不成立"
        assert await ac.get_stage(UID, chain["id"]) == stage_idx
        view = ChainStageView(author=FakeUser(id=1), chain=chain, stage_idx=stage_idx, player=player, cog=None)
        label = next(c["label"] for c in stage["choices"]
                     if _pick_best_choice([x for x in stage["choices"] if x["label"] == c["label"]], player)["advance"])
        it = FakeInteraction(user_id=1)

        await _button(view, label).callback(it)

        assert it.last.embed is not None, f"阶段{stage_idx} 没有给出结果"

    assert await ac.is_completed(UID, chain["id"]) is True
    assert await ac.get_stage(UID, chain["id"]) == len(chain["stages"]) - 1
    # 完结后不再出现在可触发列表里
    assert ac.get_available_chains([chain], player, await ac.get_chain_progress(UID)) == []
