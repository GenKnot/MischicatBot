from utils.items.pills import PILLS
from utils.items.materials import MATERIALS
from utils.items.tools import TOOLS
from utils.items.wood import WOOD
from utils.items.fish import FISH
from utils.items.herbs import HERBS
from utils.items.breakthrough import (
    SPIRIT_ROOT_BASE_RATE,
    calc_zhuji_breakthrough_rate,
    can_skip_pill,
)
from utils.alchemy import PILLS as ALCHEMY_PILLS

_PILLS_MERGED = {**PILLS}
for _k, _v in ALCHEMY_PILLS.items():
    _PILLS_MERGED[_k] = {**_v, "type": "pill"}

ITEMS = {**_PILLS_MERGED, **MATERIALS, **TOOLS, **WOOD, **FISH, **HERBS}
