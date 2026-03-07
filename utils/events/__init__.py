from utils.events.common_1 import EVENTS as _e1
from utils.events.common_2 import EVENTS as _e2
from utils.events.common_3 import EVENTS as _e3
from utils.events.rare_1 import EVENTS as _rare1
from utils.events.rare_2 import EVENTS as _rare2
from utils.events.regions.east import EVENTS as _east
from utils.events.regions.south import EVENTS as _south
from utils.events.regions.west import EVENTS as _west
from utils.events.regions.north import EVENTS as _north
from utils.events.regions.central import EVENTS as _central
from utils.events.sects_events import EVENTS as _sects

EVENTS = _e1 + _e2 + _e3
RARE_EVENTS = _rare1 + _rare2

REGION_EVENTS = {
    "东域": _east,
    "南域": _south,
    "西域": _west,
    "北域": _north,
    "中州": _central,
}

SECT_EVENTS = _sects

RARE_CHANCE = 0.12


def get_event_pool(player: dict) -> list:
    import random
    if random.random() < RARE_CHANCE:
        return RARE_EVENTS

    pool = list(EVENTS)

    city = player.get("city", "")
    from utils.world import get_city
    city_data = get_city(city)
    if city_data:
        region = city_data.get("region", "")
        region_pool = REGION_EVENTS.get(region, [])
        pool = pool + region_pool * 2

    sect = player.get("sect", "")
    if sect:
        pool = pool + SECT_EVENTS * 2

    return pool
