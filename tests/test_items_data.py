"""物品表（utils/items、data/pills.json）的数据完整性。

B75 —— `data/pills.json` 里有一个给人看的 `_schema_notes` 说明块，`_load_pills` 把它当成一件丹药读了进来，
  于是 `ITEMS["_schema_notes"]` 是一件没有 `name` 的「物品」：网页物品页一搜索就 `KeyError: 'name'` → 500；
  它也出现在所有遍历 ITEMS 的地方（候选池、列表……）。加载时跳过下划线开头的键，并加完整性校验。
"""

from utils.alchemy import PILLS
from utils.items import ITEMS


def test_B75_没有说明块混进物品表():
    assert not [k for k in ITEMS if k.startswith("_")]
    assert not [k for k in PILLS if k.startswith("_")]


def test_每件物品都有名字_且名字等于键():
    for key, item in ITEMS.items():
        assert item.get("name") == key, key


def test_每件物品都有类型():
    assert not [k for k, v in ITEMS.items() if not v.get("type")]


def test_售价是非负整数():
    for key, item in ITEMS.items():
        price = item.get("sell_price", 0)
        assert isinstance(price, int) and not isinstance(price, bool) and price >= 0, key
