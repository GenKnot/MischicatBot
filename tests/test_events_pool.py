"""探险事件池（utils/events/__init__.py）：事件选取逻辑与事件数据的合法性。

B71 —— 三个事件的奖励里用了 `_apply_rewards` 根本不认识的键，静默被忽略：
  · 【稀有】仙界碎片「直接吸纳仙灵之气」：`{lifespan: 30, lifespan_cost: 15}`，文案写「寿元 +15」，
    实际 `lifespan_cost` 没人处理，玩家拿到的是 +30（多了一倍）；
  · 沙罗城情报商「前去拦截商队」：`{spirit_stones: -50, spirit_stones_gain: 200}`，文案「灵石 -50+200」，
    实际 `spirit_stones_gain` 被忽略，玩家只会亏 50；
  · 沙罗城消息贩子「前往矿脉」：同样，`-30 + 200` 实际只亏 30。
  数据改成净值，并加一条全量校验：事件里出现的每个奖励键都必须是 `_apply_rewards` 认识的。
  （冒险奇遇链 `adventure_chains` 早就有这种校验，普通事件没有。）
"""

import json
import random
from collections import Counter

import pytest

from cogs.explore import REWARD_STAT_COLUMNS, SPECIAL_REWARD_KEYS
from utils.events import (EVENTS, RARE_CHANCE, RARE_EVENTS, REGION_EVENTS, SECT_EVENTS, _ALL_CITY_EVENTS,
                          _RECENT_LIMIT, _hidden_sects, _recent_events, get_event_pool)
from utils.sects import SECTS
from utils.world import CITIES, SPECIAL_REGIONS

ALL_POOLS = {
    "common": EVENTS, "rare": RARE_EVENTS, "sect": SECT_EVENTS, "city": _ALL_CITY_EVENTS, "hidden": _hidden_sects,
    **{f"region:{k}": v for k, v in REGION_EVENTS.items()},
}
PLAYER_STATS = {"comprehension", "physique", "fortune", "bone", "soul", "reputation"}
PLACES = {c["name"] for c in CITIES} | {r["name"] for r in SPECIAL_REGIONS}


@pytest.fixture(autouse=True)
def _clean_recent():
    _recent_events.clear()
    yield
    _recent_events.clear()


def walk(event, top=None):
    """遍历事件及其 next 里嵌套的事件（next 是内嵌的事件字典，不是标题引用）。"""
    top = top or event.get("title")
    yield top, event
    for c in event["choices"]:
        if isinstance(c.get("next"), dict):
            yield from walk(c["next"], top)


# --- 数据校验 -----------------------------------------------------------------

def test_事件池规模():
    assert len(EVENTS) > 100 and len(RARE_EVENTS) > 20 and len(SECT_EVENTS) >= 10 and len(_ALL_CITY_EVENTS) > 50
    assert set(REGION_EVENTS) == {"东域", "南域", "西域", "北域", "中州"} and all(len(v) >= 10 for v in REGION_EVENTS.values())


def test_每个事件结构完整():
    for pool, events in ALL_POOLS.items():
        for e in events:
            for top, node in walk(e):
                assert node.get("desc") and node["choices"], (pool, top)
                if node is e:
                    assert e.get("title"), pool
                for c in node["choices"]:
                    assert {"label", "next", "condition", "rewards", "flavor"} <= set(c), (pool, top)
                    assert c["label"] and len(c["label"]) <= 80, (pool, top, c["label"])         # Discord 按钮文字上限 80
                    assert len(node["choices"]) <= 25


def test_B71_事件里的奖励键都是_apply_rewards认识的():
    handled = set(REWARD_STAT_COLUMNS) | set(SPECIAL_REWARD_KEYS)
    used = Counter()
    for events in ALL_POOLS.values():
        for e in events:
            for top, node in walk(e):
                for c in node["choices"]:
                    for k in c["rewards"]:
                        used[k] += 1
    assert set(used) <= handled, f"未知奖励键（会被静默忽略）：{set(used) - handled}"


def test_奖励数值是数字_装备与发现宗门格式正确():
    for events in ALL_POOLS.values():
        for e in events:
            for top, node in walk(e):
                for c in node["choices"]:
                    for k, v in c["rewards"].items():
                        if k == "discover_sect":
                            assert v in SECTS, (top, v)
                        elif k == "equipment":
                            assert isinstance(v, dict) and 0 < v.get("chance", 1.0) <= 1, (top, v)
                        else:
                            assert isinstance(v, (int, float)) and not isinstance(v, bool), (top, k, v)


def test_条件的属性是玩家字段():
    for events in ALL_POOLS.values():
        for e in events:
            for top, node in walk(e):
                for c in node["choices"]:
                    cond = c["condition"]
                    if cond:
                        assert cond["stat"] in PLAYER_STATS and isinstance(cond["val"], (int, float)), (top, cond)


def test_城市事件的城市真实存在():
    for e in _ALL_CITY_EVENTS:
        assert e["city"] in PLACES, (e["title"], e["city"])


def test_隐世宗门事件都有触发条件_地点真实存在():
    """`get_event_pool` 里的触发条件是按标题写死的字典：新增隐世事件却忘了加条件 → 永远触发不了。"""
    import inspect
    src = inspect.getsource(get_event_pool)
    for e in _hidden_sects:
        assert f'"{e["title"]}"' in src, f"隐世事件「{e['title']}」没有触发条件"
    for place in ("太虚城", "虚空裂缝", "望月楼", "古战场", "昆仑秘境"):
        assert place in PLACES, place


def test_重复标题有已知清单_不再新增():
    """同标题的事件会各占一份权重，防重复（按标题）也会互相影响。现有重复先登记，新增的会被这条挡住。"""
    where = Counter()
    for pool, events in ALL_POOLS.items():
        for e in events:
            where[e["title"]] += 1
    dupes = {t for t, n in where.items() if n > 1}
    assert len(dupes) <= 11, f"重复标题变多了：{sorted(dupes)}"


# --- 事件选取 -----------------------------------------------------------------

def player(**kw):
    base = {"discord_id": "u1", "current_city": "灵虚城", "sect": "", "realm": "炼气期1层", "spirit_root_type": "三灵根",
            "rebirth_count": 0, "discovered_sects": "[]", "fortune": 5, "active_buffs": "{}"}
    base.update(kw)
    return base


def no_rare(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.99)


def test_稀有事件概率(monkeypatch):
    monkeypatch.setattr(random, "random", lambda: RARE_CHANCE - 0.001)
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    assert get_event_pool(player()) is RARE_EVENTS[0]
    monkeypatch.setattr(random, "random", lambda: RARE_CHANCE + 0.001)
    assert get_event_pool(player()) not in RARE_EVENTS


def test_稀有事件概率_探灵丹加成(monkeypatch):
    from utils.buffs import apply_buff
    buffs = apply_buff("{}", "explore_rare_bonus_once", 50)
    monkeypatch.setattr(random, "random", lambda: 0.4)                      # 0.12 + 0.5 = 0.62 > 0.4
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    assert get_event_pool(player(active_buffs=buffs)) is RARE_EVENTS[0]
    assert get_event_pool(player()) not in RARE_EVENTS


def capture_pool(monkeypatch, p):
    """拦下 random.choices，看当前候选事件和权重。"""
    seen = {}

    def choices(events, weights=None, k=1):
        seen["events"], seen["weights"] = list(events), list(weights)
        return [events[0]]
    no_rare(monkeypatch)
    monkeypatch.setattr(random, "choices", choices)
    get_event_pool(p)
    return seen


def test_候选池_通用事件权重1(monkeypatch):
    seen = capture_pool(monkeypatch, player(current_city="不存在的地方"))
    assert len(seen["events"]) == len(EVENTS) and set(seen["weights"]) == {1}


def test_候选池_所在大洲的事件权重15_本城事件权重2(monkeypatch):
    seen = capture_pool(monkeypatch, player(current_city="灵虚城"))
    titles = [e["title"] for e in seen["events"]]
    region = [e for e in seen["events"] if e in REGION_EVENTS["中州"]]
    assert len(region) == len(REGION_EVENTS["中州"]) and all(
        w == 1.5 for e, w in zip(seen["events"], seen["weights"]) if e in REGION_EVENTS["中州"] and e not in EVENTS)
    mine = [(e, w) for e, w in zip(seen["events"], seen["weights"]) if e.get("city") == "灵虚城"]
    assert all(w == 2 for _, w in mine) and len(titles) == len(seen["events"])
    assert not [e for e in seen["events"] if e in REGION_EVENTS["东域"]]


def test_候选池_宗门弟子多出宗门事件(monkeypatch):
    no_sect = capture_pool(monkeypatch, player())["events"]
    with_sect = capture_pool(monkeypatch, player(sect="青云宗"))
    assert len(with_sect["events"]) - len(no_sect) == len(SECT_EVENTS) and 1.5 in with_sect["weights"]


def hidden_titles(seen):
    return {e["title"] for e in seen["events"] if e in _hidden_sects}


HIDDEN_CASES = [
    ("【奇遇】太虚城地脉异动", dict(current_city="太虚城", spirit_root_type="单灵根", realm="结丹期初期")),
    ("【奇遇】虚空裂缝的呼唤", dict(current_city="虚空裂缝", spirit_root_type="变异灵根", realm="元婴期初期")),
    ("【奇遇】望月楼的隐秘入口", dict(current_city="望月楼", fortune=8)),
    ("【奇遇】古战场的考验", dict(current_city="古战场")),
    ("【奇遇】昆仑秘境的轮回感应", dict(current_city="昆仑秘境", rebirth_count=1)),
]


@pytest.mark.parametrize("title,fields", HIDDEN_CASES)
def test_隐世事件_满足条件且掷中5pct才进池(monkeypatch, title, fields):
    seen_hit = {}

    def choices(events, weights=None, k=1):
        seen_hit["events"] = list(events)
        return [events[0]]
    monkeypatch.setattr(random, "choices", choices)
    rolls = iter([0.99, 0.04])                                        # 第一次判稀有（不中），第二次判 5%（中）
    monkeypatch.setattr(random, "random", lambda: next(rolls))
    get_event_pool(player(**fields))
    assert title in hidden_titles(seen_hit)
    rolls = iter([0.99, 0.06])                                        # 没掷中 5%
    seen_hit.clear()
    get_event_pool(player(**fields))
    assert title not in hidden_titles(seen_hit)


@pytest.mark.parametrize("title,fields,spoil", [
    ("【奇遇】太虚城地脉异动", dict(current_city="太虚城", spirit_root_type="单灵根", realm="结丹期初期"), dict(realm="筑基期1层")),
    ("【奇遇】太虚城地脉异动", dict(current_city="太虚城", spirit_root_type="单灵根", realm="结丹期初期"), dict(spirit_root_type="双灵根")),
    ("【奇遇】望月楼的隐秘入口", dict(current_city="望月楼", fortune=8), dict(fortune=7)),
    ("【奇遇】昆仑秘境的轮回感应", dict(current_city="昆仑秘境", rebirth_count=1), dict(rebirth_count=0)),
    ("【奇遇】古战场的考验", dict(current_city="古战场"), dict(current_city="灵虚城")),
])
def test_隐世事件_条件不满足不进池(monkeypatch, title, fields, spoil):
    got = {}
    monkeypatch.setattr(random, "choices", lambda events, weights=None, k=1: (got.update(e=list(events)), [events[0]])[1])
    rolls = iter([0.99] + [0.0] * 5)
    monkeypatch.setattr(random, "random", lambda: next(rolls))
    get_event_pool(player(**{**fields, **spoil}))
    assert title not in hidden_titles({"events": got["e"]})


def test_隐世事件_已发现的宗门不再触发(monkeypatch):
    got = {}
    monkeypatch.setattr(random, "choices", lambda events, weights=None, k=1: (got.update(e=list(events)), [events[0]])[1])
    rolls = iter([0.99, 0.0, 0.0, 0.0])
    monkeypatch.setattr(random, "random", lambda: next(rolls))
    get_event_pool(player(current_city="古战场", discovered_sects=json.dumps(["无极道"])))
    assert "【奇遇】古战场的考验" not in hidden_titles({"events": got["e"]})


# --- 防重复 -------------------------------------------------------------------

def test_防重复_最近出过的事件会重抽(monkeypatch):
    no_rare(monkeypatch)
    a, b = EVENTS[0], EVENTS[1]
    _recent_events["u1"] = [a["title"]]
    picks = iter([a, b])
    monkeypatch.setattr(random, "choices", lambda events, weights=None, k=1: [next(picks)])
    assert get_event_pool(player()) is b


def test_防重复_最多重抽三次_最后一次不管(monkeypatch):
    no_rare(monkeypatch)
    a = EVENTS[0]
    _recent_events["u1"] = [a["title"]]
    calls = []
    monkeypatch.setattr(random, "choices", lambda events, weights=None, k=1: (calls.append(1), [a])[1])
    assert get_event_pool(player()) is a and len(calls) == 3


def test_防重复_只记最近8个_按玩家分开(monkeypatch):
    no_rare(monkeypatch)
    monkeypatch.setattr(random, "choices", lambda events, weights=None, k=1: [events[len(_recent_events.get("u1", []))]])
    for _ in range(12):
        get_event_pool(player())
    assert len(_recent_events["u1"]) == _RECENT_LIMIT
    get_event_pool(player(discord_id="u2"))
    assert len(_recent_events["u2"]) == 1 and len(_recent_events["u1"]) == _RECENT_LIMIT


def test_没有玩家id时不记录(monkeypatch):
    no_rare(monkeypatch)
    get_event_pool(player(discord_id=""))
    assert "" not in _recent_events


def test_真实随机_多次抽取不报错且都是合法事件():
    random.seed(7)
    for n in range(300):
        e = get_event_pool(player(discord_id=f"u{n % 5}", current_city=random.choice([c["name"] for c in CITIES] + ["古战场", "昆仑秘境"]),
                                  sect=random.choice(["", "青云宗"])))
        assert e["title"] and e["choices"]


SECT_OF = {"【奇遇】太虚城地脉异动": "太虚阁", "【奇遇】虚空裂缝的呼唤": "混沌宗", "【奇遇】望月楼的隐秘入口": "天机门",
           "【奇遇】古战场的考验": "无极道", "【奇遇】昆仑秘境的轮回感应": "仙葬谷"}


@pytest.mark.parametrize("title,fields", HIDDEN_CASES)
def test_隐世事件_已发现对应宗门后不再触发(monkeypatch, title, fields):
    got = {}
    monkeypatch.setattr(random, "choices", lambda events, weights=None, k=1: (got.update(e=list(events)), [events[0]])[1])
    rolls = iter([0.99, 0.0, 0.0, 0.0])
    monkeypatch.setattr(random, "random", lambda: next(rolls))
    get_event_pool(player(**fields, discovered_sects=json.dumps([SECT_OF[title]], ensure_ascii=False)))
    assert title not in hidden_titles({"events": got["e"]})


def test_隐世事件与宗门一一对应():
    assert set(SECT_OF) == {e["title"] for e in _hidden_sects} and set(SECT_OF.values()) <= set(SECTS)
