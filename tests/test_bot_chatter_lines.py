"""条件化文案库（utils/bot_chatter_lines.py、data/bot_chatter/）。

用户 2026-10-12 的要求：文案要能按 性格 / 阵营 / 出身 / 状态 / 境界 / 关系 / 事件 …… 多条件挑选，结构清晰、能让 AI 批量扩写，不把台词写死在代码里。
"""

import copy
import json
import random
from pathlib import Path

import pytest

from utils import bot_chatter_lines as cl
from utils.bot_social import load_archetypes


def R(seed=0):
    return random.Random(seed)


# ---- 数据 -------------------------------------------------------------------

def test_所有文案文件合法():
    assert cl.validate_all() == []


def test_每个场景都有文件和兜底规则():
    cov = cl.coverage()
    assert set(cov) == set(cl.SCENES)
    for scene, c in cov.items():
        assert c["fallback"] >= 1 and c["rules"] >= 3 and c["lines"] >= 3, scene


def test_每个性格在每个场景都有专属规则():
    for scene, c in cl.coverage().items():
        assert c["archetypes"] == len(load_archetypes()), scene


def test_道贺的四种态度每个性格都有台词():
    got = {(a, att) for r in cl.rules_of("chatter_congrats") for a in r.get("when", {}).get("archetype", [])
           for att in r.get("when", {}).get("attitude", [])}
    assert got == {(a, att) for a in load_archetypes() for att in cl.ATTITUDES}


def test_场景说明齐全():
    assert set(cl.SCENE_INFO) == set(cl.SCENES)
    for scene, (when, beat) in cl.SCENE_INFO.items():
        assert when and beat


def test_批次文件按场景名归并(tmp_path, monkeypatch):
    for f in cl.DIR.glob("chatter_mediate*.json"):
        (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    extra = {"scene": "chatter_mediate", "rules": [{"when": {"archetype": ["阴鸷"]}, "lines": ["批次里的一句。"]}]}
    (tmp_path / "chatter_mediate.批次甲.json").write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cl, "DIR", tmp_path)
    cl.reload()
    try:
        assert cl.scene_of(tmp_path / "chatter_mediate.批次甲.json") == "chatter_mediate"
        assert "批次里的一句。" in {t for r in cl.rules_of("chatter_mediate") for t in r["lines"]}
        assert [p.name for p in cl.files_for("chatter_mediate")] == ["chatter_mediate.json", "chatter_mediate.批次甲.json"]
    finally:
        monkeypatch.undo()
        cl.reload()


# ---- 校验 -------------------------------------------------------------------

def rule(**kw):
    return {"lines": ["一句话。"], **kw}


@pytest.mark.parametrize("bad,expect", [
    ([], "非空列表"),
    ("不是列表", "非空列表"),
    ([rule(when={"不存在的键": ["x"]})], "未知条件"),
    ([rule(when={"archetype": ["没这个性格"]})], "未知的值"),
    ([rule(when={"archetype": []})], "非空列表"),
    ([rule(when={"tier": "陌生"})], "非空列表"),
    ([rule(when={"tags": ["无此标签"]})], "未知的值"),
    ([rule(when={"attitude": ["开心"]})], "未知的值"),
    ([rule(when={"realm_gap": ["much"]})], "未知的值"),
    ([rule(weight=0)], "weight"),
    ([rule(weight=99)], "weight"),
    ([rule(lines=[])], "lines"),
    ([rule(lines=["", "好"])], "空台词"),
    ([rule(lines=["长" * 81])], "超过"),
    ([rule(lines=["{player}{没有这个}"])], "占位符"),
    ([rule(lines=["{item}不在这个场景里"])], "占位符"),
    ([rule(lines=["花括号不成对 {player"])], "花括号"),
    (["字符串不是对象"], "应是对象"),
    ([rule(when="不是对象")], "when 应是对象"),
])
def test_校验能拦住坏规则(bad, expect):
    errors = cl.validate_rules(bad, "chatter_arrive")
    assert any(expect in e for e in errors), errors


def test_合法规则通过_场景自己的占位符允许():
    assert cl.validate_rules([rule(lines=["{player}在{city}，我是{bot}。"], when={"archetype": ["豪爽"], "tags": ["重义气", "守序善良"], "bond": ["self", "结拜"]})],
                             "chatter_arrive") == []
    assert cl.validate_rules([rule(lines=["{realm}"])], "chatter_arrive")        # city 才是 arrive 的变量
    assert cl.validate_rules([rule(lines=["{realm}"])], "chatter_congrats") == []


def test_校验文件_坏JSON_未知场景_文件名对不上(tmp_path):
    p = tmp_path / "chatter_arrive.json"
    p.write_text("不是json", encoding="utf-8")
    assert "不是合法 JSON" in cl.validate_file(p)[0]
    p.write_text(json.dumps({"scene": "没有的场景", "rules": []}), encoding="utf-8")
    assert "未知场景" in cl.validate_file(p)[0]
    p.write_text(json.dumps({"scene": "chatter_congrats", "rules": [rule()]}), encoding="utf-8")
    assert any("文件名应以场景名" in e for e in cl.validate_file(p))


def test_缺兜底规则会被发现(tmp_path, monkeypatch):
    for f in cl.DIR.glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        if data["scene"] == "chatter_mediate":
            data["rules"] = [r for r in data["rules"] if r.get("when")]
        (tmp_path / f.name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cl, "DIR", tmp_path)
    cl.reload()
    try:
        assert any("chatter_mediate: 至少要有一条没有条件的兜底规则" in e for e in cl.validate_all())
    finally:
        monkeypatch.undo()
        cl.reload()


def test_缺场景文件会被发现(tmp_path, monkeypatch):
    for f in cl.DIR.glob("*.json"):
        if f.name != "reply_cold.json":
            (tmp_path / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(cl, "DIR", tmp_path)
    cl.reload()
    try:
        assert "缺少场景 reply_cold 的文件" in cl.validate_all()
    finally:
        monkeypatch.undo()
        cl.reload()


# ---- 匹配与挑选 -------------------------------------------------------------

def test_匹配_且_或_标签任一个():
    ctx = {"archetype": "豪爽", "tier": "熟识", "tags": ["守序善良", "冲动"], "origin": None}
    assert cl.matches({}, ctx)
    assert cl.matches({"archetype": ["豪爽", "憨直"]}, ctx)
    assert not cl.matches({"archetype": ["憨直"]}, ctx)
    assert cl.matches({"archetype": ["豪爽"], "tier": ["熟识", "至交"]}, ctx)
    assert not cl.matches({"archetype": ["豪爽"], "tier": ["陌生"]}, ctx), "条件之间是『且』"
    assert cl.matches({"tags": ["冲动", "谨慎"]}, ctx) and not cl.matches({"tags": ["谨慎"]}, ctx)
    assert not cl.matches({"origin": ["书香"]}, ctx), "上下文里这个值是 None"
    assert not cl.matches({"zodiac": ["白羊"]}, ctx), "上下文里没这个键"


def test_挑选_没有匹配返回None(monkeypatch):
    monkeypatch.setattr(cl, "rules_of", lambda scene: [{"when": {"archetype": ["豪爽"]}, "lines": ["x"]}])
    assert cl.pick("chatter_arrive", {"archetype": "阴鸷"}) is None
    assert cl.pick("chatter_arrive", {"archetype": "豪爽"}) == "x"


def test_挑选_越具体权重越大(monkeypatch):
    rules = [{"lines": ["泛"]}, {"when": {"archetype": ["豪爽"]}, "lines": ["一个条件"]},
             {"when": {"archetype": ["豪爽"], "tier": ["熟识"]}, "lines": ["两个条件"]}]
    monkeypatch.setattr(cl, "rules_of", lambda scene: rules)
    rng, counts = R(1), {"泛": 0, "一个条件": 0, "两个条件": 0}
    for _ in range(7000):
        counts[cl.pick("chatter_arrive", {"archetype": "豪爽", "tier": "熟识"}, rng)] += 1
    assert counts["泛"] < counts["一个条件"] < counts["两个条件"]
    assert 0.1 < counts["泛"] / 7000 < 0.2 and 0.55 < counts["两个条件"] / 7000 < 0.65        # 1 : 2 : 4


def test_挑选_显式权重也生效(monkeypatch):
    rules = [{"lines": ["轻"], "weight": 1}, {"lines": ["重"], "weight": 9}]
    monkeypatch.setattr(cl, "rules_of", lambda scene: rules)
    rng = R(2)
    heavy = sum(cl.pick("chatter_arrive", {}, rng) == "重" for _ in range(3000)) / 3000
    assert 0.86 < heavy < 0.94


def test_挑选_真实库里每个性格每个档位都能挑出一句():
    for scene, vars_ in cl.SCENES.items():
        for a in load_archetypes():
            for tier in ("仇视", "陌生", "熟识", "至交"):
                ctx = {"archetype": a, "tier": tier, "relation": "无", "tags": [], "realm_gap": "equal", "attitude": "真心", "kind": "rob", "bond": "朋友"}
                assert cl.pick(scene, ctx, R(3)), (scene, a, tier)


def test_真实库里的条件组合真的被用上():
    ctx = {"archetype": "阴鸷", "tier": "仇视", "relation": "无", "tags": ["记仇"], "realm_gap": "higher", "origin": "书香"}
    seen = {cl.pick("chatter_arrive", ctx, R(s)) for s in range(300)}
    assert any("上回的账" in t for t in seen), "tags=记仇 且 仇视 的规则"
    assert any("这点修为" in t for t in seen), "realm_gap=higher 且 仇视"
    assert any("雅事" in t for t in seen), "origin=书香"
    assert any("呵" in t for t in seen), "阴鸷专属"


def test_标签接口():
    assert "守序善良" in cl.tags_of(80, {"lawful": 80, "impulse": 50, "loyalty": 50, "vengeful": 50, "capacity": 5, "deviance": 0})
    assert cl.tags_of(50, None) == []


def test_挑选_规则里的几句台词都有机会(monkeypatch):
    monkeypatch.setattr(cl, "rules_of", lambda scene: [{"lines": ["甲", "乙", "丙"]}])
    rng = R(4)
    assert {cl.pick("chatter_arrive", {}, rng) for _ in range(100)} == {"甲", "乙", "丙"}
