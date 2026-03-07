from utils.events.common_1 import EVENTS as _e1
from utils.events.common_2 import EVENTS as _e2
from utils.events.common_3 import EVENTS as _e3
from utils.events.common_4 import EVENTS as _e4
from utils.events.common_5 import EVENTS as _e5
from utils.events.common_6 import EVENTS as _e6
from utils.events.common_7 import EVENTS as _e7
from utils.events.common_5 import EVENTS as _e5
from utils.events.common_6 import EVENTS as _e6
from utils.events.common_7 import EVENTS as _e7
from utils.events.rare_1 import EVENTS as _rare1
from utils.events.rare_2 import EVENTS as _rare2
from utils.events.rare_3 import EVENTS as _rare3
from utils.events.regions.east import EVENTS as _east
from utils.events.regions.south import EVENTS as _south
from utils.events.regions.west import EVENTS as _west
from utils.events.regions.north import EVENTS as _north
from utils.events.regions.central import EVENTS as _central
from utils.events.sects_events import EVENTS as _sects
from utils.events.city_trade import EVENTS as _city_trade
from utils.events.city_combat import EVENTS as _city_combat
from utils.events.city_culture import EVENTS as _city_culture

EVENTS = _e1 + _e2 + _e3 + _e4 + _e5 + _e6 + _e7 + _e5 + _e6 + _e7
RARE_EVENTS = _rare1 + _rare2 + _rare3

REGION_EVENTS = {
    "东域": _east,
    "南域": _south,
    "西域": _west,
    "北域": _north,
    "中州": _central,
}

SECT_EVENTS = _sects

_ALL_CITY_EVENTS = _city_trade + _city_combat + _city_culture

RARE_CHANCE = 0.12


_recent_events: dict[str, list] = {}
_RECENT_LIMIT = 8


def get_event_pool(player: dict) -> list:
    import random
    uid = player.get("discord_id", "")

    if random.random() < RARE_CHANCE:
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

    recent = _recent_events.get(uid, [])
    for _ in range(3):
        result = random.choices(events, weights=weights, k=1)[0]
        if result["title"] not in recent:
            break

    if uid:
        recent.append(result["title"])
        _recent_events[uid] = recent[-_RECENT_LIMIT:]

    return result
