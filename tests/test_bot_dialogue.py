"""机器人台词（utils/bot_dialogue.py、data/bot_dialogues/）。

· 数据校验（会在 CI 里拦住 AI 批量生成时的格式问题）：JSON 合法、场景 / 档位在清单内、占位符合法、长度上限；
· `_default.json` 格子齐全；
· 查找：原型自己的 → 最接近的档位 → 通用台词；占位符代入；未知原型不报错。
"""

import json
import random

import pytest

from utils import bot_dialogue as bd
from utils.bot_social import TIER_ACQUAINT, TIER_CLOSE, TIER_HOSTILE, TIER_STRANGER, load_archetypes


def test_所有台词文件合法():
    assert bd.validate_all() == []


def test_默认台词格子齐全():
    data = json.loads((bd.DIR / "_default.json").read_text(encoding="utf-8"))["lines"]
    assert set(data) == set(bd.SCENES)
    assert all(set(cells) == set(bd.TIERS) and all(len(v) >= 2 for v in cells.values()) for cells in data.values())


def test_档位名与好感模块一致():
    assert bd.TIERS == (TIER_HOSTILE, TIER_STRANGER, TIER_ACQUAINT, TIER_CLOSE)


def test_台词文件对应真实原型():
    names = set(load_archetypes()) | {bd.DEFAULT}
    assert {bd.archetype_of(p) for p in bd.DIR.glob("*.json")} <= names           # 批次文件 <原型>.<批次>.json 也算


def test_场景清单与_README_一致():
    readme = (bd.DIR / "README.md").read_text(encoding="utf-8")
    for scene in bd.SCENES:
        assert f"`{scene}`" in readme or scene in readme, scene
    for tier in bd.TIERS:
        assert tier in readme


# ---- 校验器本身 -------------------------------------------------------------

def write(tmp_path, name, lines, archetype=None):
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"archetype": archetype or name, "lines": lines}, ensure_ascii=False), encoding="utf-8")
    return p


def test_校验器_抓得住各类错误(tmp_path):
    cases = {
        "未知场景": {"nope": {"陌生": ["x"]}},
        "未知档位": {"greet": {"路人": ["x"]}},
        "空格子": {"greet": {"陌生": []}},
        "空台词": {"greet": {"陌生": ["  "]}},
        "太长": {"greet": {"陌生": ["字" * (bd.MAX_LINE_LEN + 1)]}},
        "坏占位符": {"greet": {"陌生": ["你好{name}"]}},
        "花括号不成对": {"greet": {"陌生": ["你好{player"]}},
        "非字符串": {"greet": {"陌生": [123]}},
    }
    for label, lines in cases.items():
        assert bd.validate_file(write(tmp_path, "豪爽", lines)), label
    assert bd.validate_file(write(tmp_path, "豪爽", {"greet": {"陌生": ["你好{player}，我是{bot}，收下{item}"]}})) == []


def test_校验器_档案名与原型字段要一致(tmp_path):
    assert bd.validate_file(write(tmp_path, "豪爽", {}, archetype="阴鸷"))


def test_校验器_坏JSON与缺_lines(tmp_path):
    bad = tmp_path / "豪爽.json"
    bad.write_text("{不是json", encoding="utf-8")
    assert "不是合法 JSON" in bd.validate_file(bad)[0]
    bad.write_text(json.dumps({"archetype": "豪爽"}), encoding="utf-8")
    assert "缺少 lines" in bd.validate_file(bad)[0]


def test_校验器_完整性要求只对默认文件(tmp_path):
    p = write(tmp_path, "豪爽", {"greet": {"陌生": ["x"]}})
    assert bd.validate_file(p) == [] and bd.validate_file(p, require_complete=True)


# ---- 查找 -------------------------------------------------------------------

def test_取台词_代入占位符():
    line = bd.get_line("豪爽", "greet", "熟识", player="张三", bot="李四")
    assert "{" not in line and line == "张三！来得正好，陪我痛饮三杯！"


def test_取台词_原型缺的档位用最接近的():
    # 豪爽 greet 写了 陌生 / 熟识 / 至交，没写 仇视 → 最接近的是 陌生
    assert bd._candidates("豪爽", "greet", "仇视") == bd._load("豪爽")["greet"]["陌生"]
    # gift_love 只写了 陌生 / 至交：熟识离两边一样近，取排在前面的陌生
    assert bd._candidates("豪爽", "gift_love", "熟识") == bd._load("豪爽")["gift_love"]["陌生"]


def test_取台词_原型没写的场景回退到通用():
    assert bd._candidates("豪爽", "chat_again", "陌生") == bd._load(bd.DEFAULT)["chat_again"]["陌生"]


def test_取台词_未知原型和空原型不报错():
    for arche in ("没有这个原型", None, ""):
        assert bd.get_line(arche, "gift_limit", "至交", player="甲", bot="乙")


@pytest.mark.parametrize("scene", bd.SCENES)
@pytest.mark.parametrize("tier", bd.TIERS)
def test_每个格子都能取到台词(scene, tier):
    for arche in list(load_archetypes()) + [None]:
        line = bd.get_line(arche, scene, tier, player="甲", bot="乙", item="筑基丹", days=4, count=3, city="丁", victim="戊")
        assert line and "{" not in line


def test_取台词_缺少的占位符保留原样不崩():
    line = bd.get_line("没有这个原型", "gift_love", "陌生")          # 没传 item
    assert "{item}" in line


def test_取台词_可传随机源复现():
    a = bd.get_line(None, "greet", "陌生", rng=random.Random(1), player="甲", bot="乙")
    b = bd.get_line(None, "greet", "陌生", rng=random.Random(1), player="甲", bot="乙")
    assert a == b
