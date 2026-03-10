from utils.events.common_1 import EVENTS as _e1
from utils.events.common_2 import EVENTS as _e2
from utils.events.common_3 import EVENTS as _e3
from utils.events.common_4 import EVENTS as _e4
from utils.events.common_5 import EVENTS as _e5
from utils.events.common_6 import EVENTS as _e6
from utils.events.common_7 import EVENTS as _e7
from utils.events.common_8 import EVENTS as _e8
from utils.events.common_9 import EVENTS as _e9
from utils.events.common_10 import EVENTS as _e10
from utils.events.rare_1 import EVENTS as _rare1
from utils.events.rare_2 import EVENTS as _rare2
from utils.events.rare_3 import EVENTS as _rare3
from utils.events.regions.east import EVENTS as _east
from utils.events.regions.east_2 import EVENTS as _east2
from utils.events.regions.south import EVENTS as _south
from utils.events.regions.south_2 import EVENTS as _south2
from utils.events.regions.west import EVENTS as _west
from utils.events.regions.west_2 import EVENTS as _west2
from utils.events.regions.north import EVENTS as _north
from utils.events.regions.north_2 import EVENTS as _north2
from utils.events.regions.central import EVENTS as _central
from utils.events.regions.central_2 import EVENTS as _central2
from utils.events.sects_events import EVENTS as _sects, HIDDEN_SECT_EVENTS as _hidden_sects
from utils.events.city_trade import EVENTS as _city_trade
from utils.events.city_trade_2 import EVENTS as _city_trade2
from utils.events.city_combat import EVENTS as _city_combat
from utils.events.city_combat_2 import EVENTS as _city_combat2
from utils.events.city_culture import EVENTS as _city_culture
from utils.events.city_culture_2 import EVENTS as _city_culture2

EVENTS = _e1 + _e2 + _e3 + _e4 + _e5 + _e6 + _e7 + _e8 + _e9 + _e10
RARE_EVENTS = _rare1 + _rare2 + _rare3

REGION_EVENTS = {
    "东域": _east + _east2,
    "南域": _south + _south2,
    "西域": _west + _west2,
    "北域": _north + _north2,
    "中州": _central + _central2,
}

SECT_EVENTS = _sects

_ALL_CITY_EVENTS = _city_trade + _city_trade2 + _city_combat + _city_combat2 + _city_culture + _city_culture2

RARE_CHANCE = 0.12


_recent_events: dict[str, list] = {}
_RECENT_LIMIT = 8


def get_event_pool(player: dict) -> dict:
    import random
    from utils.buffs import get_explore_rare_bonus
    uid = player.get("discord_id", "")

    rare_bonus = get_explore_rare_bonus(player)
    if random.random() < RARE_CHANCE + rare_bonus:
        return random.choice(RARE_EVENTS)

    events = []
    weights = []

    for e in EVENTS:
        events.append(e)
        weights.append(1)

    city = player.get("current_city", "")
    from utils.world import get_city
    city_data = get_city(city)
    if city_data:
        region = city_data.get("region", "")
        for e in REGION_EVENTS.get(region, []):
            events.append(e)
            weights.append(1.5)
        for e in _ALL_CITY_EVENTS:
            if e.get("city") == city:
                events.append(e)
                weights.append(2)

    sect = player.get("sect", "")
    if sect:
        for e in SECT_EVENTS:
            events.append(e)
            weights.append(1.5)

    import json
    from utils.realms import get_realm_index
    discovered = json.loads(player.get("discovered_sects") or "[]")
    root_type = player.get("spirit_root_type", "")
    rebirth = player.get("rebirth_count", 0)
    realm_idx = get_realm_index(player.get("realm", "炼气期1层"))

    _hidden_conditions = {
        "【奇遇】太虚城地脉异动":    lambda: city == "太虚城" and root_type == "单灵根" and realm_idx >= get_realm_index("结丹期初期") and "太虚阁" not in discovered,
        "【奇遇】虚空裂缝的呼唤":    lambda: city == "虚空裂缝" and root_type == "变异灵根" and realm_idx >= get_realm_index("元婴期初期") and "混沌宗" not in discovered,
        "【奇遇】望月楼的隐秘入口":  lambda: city == "望月楼" and player.get("fortune", 0) >= 8 and "天机门" not in discovered,
        "【奇遇】古战场的考验":      lambda: city == "古战场" and "无极道" not in discovered,
        "【奇遇】昆仑秘境的轮回感应": lambda: city == "昆仑秘境" and rebirth >= 1 and "仙葬谷" not in discovered,
    }
    for e in _hidden_sects:
        cond = _hidden_conditions.get(e["title"])
        if cond and cond() and random.random() < 0.05:
            events.append(e)
            weights.append(1)

    recent = _recent_events.get(uid, [])
    for _ in range(3):
        result = random.choices(events, weights=weights, k=1)[0]
        if result["title"] not in recent:
            break

    if uid:
        recent.append(result["title"])
        _recent_events[uid] = recent[-_RECENT_LIMIT:]

    return result
