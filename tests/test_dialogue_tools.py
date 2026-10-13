"""台词写作工具（utils/bot_dialogue_tools.py、scripts/dialogue_tool.py、data/bot_voices.json）。

目标：以后用别的 AI 续写各种性格的台词，流程是『看缺口 → 出提示词 → 收稿校验合并』，每一步都有保护：
· 角色卡数据合法、和代码里的场景 / 档位 / 性格原型清单一致（新增原型忘了写角色卡会红）；
· 提示词带上角色卡、场景含义、已有台词、规则、输出格式，并且只包含被要求的场景 / 档位；
· 收稿：格式 / 占位符 / 长度不对一律不写；已有的句子去重；可以写独立批次文件；批次文件查找时自动合并。
"""

import importlib.util
import io
import json
import shutil
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from utils import bot_dialogue as bd
from utils import bot_dialogue_tools as tools

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("dialogue_tool", ROOT / "scripts" / "dialogue_tool.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


@pytest.fixture
def ddir(tmp_path, monkeypatch):
    """台词目录的临时副本：测试里写入不会弄脏仓库。"""
    for f in bd.DIR.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    monkeypatch.setattr(bd, "DIR", tmp_path)
    bd.reload()
    yield tmp_path
    bd.reload()


# ---- 角色卡 -----------------------------------------------------------------

def test_角色卡合法():
    assert tools.validate_voices(tools.load_voices()) == []


def test_每个性格原型都有角色卡():
    assert set(tools.load_voices()["archetypes"]) == set(tools.archetype_names())


@pytest.mark.parametrize("edit,words", [
    (lambda v: v.pop("world"), "world"),
    (lambda v: v["scenes"].pop("greet"), "scenes"),
    (lambda v: v["scenes"]["greet"].pop("when"), "when"),
    (lambda v: v["tiers"].pop("至交"), "tiers"),
    (lambda v: v["archetypes"].pop("豪爽"), "archetypes"),
    (lambda v: v["archetypes"]["豪爽"].pop("habits"), "habits"),
    (lambda v: v["archetypes"]["豪爽"]["toward_player"].pop("仇视"), "toward_player"),
    (lambda v: v["archetypes"]["豪爽"]["examples"].append("字" * 100), "示例"),
    (lambda v: v["archetypes"].update({"新原型": v["archetypes"]["豪爽"]}), "archetypes"),
])
def test_角色卡校验器抓得住错误(edit, words):
    v = tools.load_voices()
    edit(v)
    errors = tools.validate_voices(v)
    assert errors and any(words in e for e in errors), errors


def test_角色卡的示例本身合法():
    for name, card in tools.load_voices()["archetypes"].items():
        for ex in card["examples"]:
            assert len(ex) <= 40, (name, ex)


# ---- 缺口 / 覆盖 ------------------------------------------------------------

def test_缺口_按场景档位顺序(ddir):
    g = tools.gaps("豪爽", target=1)
    assert ("greet", "仇视", 0) in g and ("greet", "陌生", 2) not in g          # 豪爽 greet/陌生 写了 2 句
    assert g == sorted(g, key=lambda x: (bd.SCENES.index(x[0]), bd.TIERS.index(x[1])))


def test_缺口_目标越高缺口越多(ddir):
    assert len(tools.gaps("阴鸷", 1)) == 108 - 24 - 12                           # 108 格里，记忆种子写了 24 格、拦路种子写了 12 格
    assert len(tools.gaps("豪爽", 3)) > len(tools.gaps("豪爽", 1))


def test_覆盖报告(ddir):
    rep = tools.coverage_report(["豪爽", "阴鸷"], target=1)
    lines = rep.splitlines()
    assert lines[0].startswith("| 原型") and len(lines) == 4
    assert "| 豪爽 |" in lines[2] and "/108" in lines[2] and "| 阴鸷 | 36/108 | 36 |" in lines[3]


def test_覆盖报告_缺口最多的场景(ddir):
    row = tools.coverage_report(["阴鸷"], target=1).splitlines()[2]
    assert "greet" in row                                                       # 全空时并列，取靠前的


# ---- 提示词 -----------------------------------------------------------------

def test_提示词_包含角色卡_场景_规则_输出格式(ddir):
    p = tools.build_prompt("阴鸷", ["greet", "gift_hate"], ["陌生", "至交"], n=3)
    card = tools.load_voices()["archetypes"]["阴鸷"]
    assert "为性格「阴鸷」" in p and card["summary"] in p and card["values"] in p
    assert "**陌生**" in p and "**至交**" in p and "**仇视**" not in p and "**熟识**" not in p
    assert card["toward_player"]["至交"] in p and card["toward_player"]["仇视"] not in p
    assert "`greet`" in p and "`gift_hate`" in p and "`dual_accept`" not in p
    assert "各写 **3** 句" in p and "不要许诺任何游戏结果" in p and "{player}" in p and "```json" in p
    assert tools.load_voices()["world"] in p


def test_提示词_带上已有台词让新的不重复(ddir):
    p = tools.build_prompt("豪爽", ["greet"], ["陌生"])
    assert "哈哈，道友面生得很，来，喝一杯！" in p and "greet/陌生" in p
    assert "greet/熟识" not in p, "没被要求的档位不列已有台词"


def test_提示词_默认补缺口涉及的场景和档位(ddir):
    p = tools.build_prompt("阴鸷")
    assert all(f"`{s}`" in p for s in bd.SCENES) and all(f"**{t}**" in p for t in bd.TIERS)
    p2 = tools.build_prompt("豪爽", target=1)
    assert "`greet`" in p2 and "**仇视**" in p2


def test_提示词_缺口全补完就没有要写的场景():
    # 通用台词是完整的：对它没有缺口（target=2）
    assert tools.gaps(bd.DEFAULT, 2) == []


@pytest.mark.parametrize("kwargs", [{"scenes": ["不存在"]}, {"tiers": ["路人"]}])
def test_提示词_未知场景档位报错(ddir, kwargs):
    with pytest.raises(ValueError):
        tools.build_prompt("豪爽", **kwargs)


def test_提示词_未知原型报错(ddir):
    with pytest.raises(ValueError):
        tools.build_prompt("不存在的原型")


def test_每个原型都能出提示词(ddir):
    for name in tools.archetype_names():
        assert len(tools.build_prompt(name, ["greet"], ["陌生"])) > 500


# ---- 收稿合并 ---------------------------------------------------------------

NEW = {"lines": {"greet": {"陌生": ["呵，生面孔。", "这位道友，请。"]}, "gift_love": {"至交": ["{item}？{player}，你果然懂我。"]}}}


def test_合并_写入主文件(ddir):
    res = tools.merge_lines("阴鸷", NEW)
    assert res["ok"] and res["added"] == 3 and res["duplicates"] == 0 and res["path"].endswith("阴鸷.json")
    assert bd.get_line("阴鸷", "greet", "陌生", rng=__import__("random").Random(1), player="甲", bot="乙") in {"呵，生面孔。", "这位道友，请。"}
    doc = json.loads((ddir / "阴鸷.json").read_text(encoding="utf-8"))
    assert doc["archetype"] == "阴鸷" and list(doc["lines"]) == ["greet", "gift_love"]


def test_合并_已有的句子去重(ddir):
    tools.merge_lines("阴鸷", NEW)
    res = tools.merge_lines("阴鸷", NEW)
    assert res["ok"] and res["added"] == 0 and res["duplicates"] == 3


def test_合并_和批次文件里的也去重(ddir):
    tools.merge_lines("阴鸷", NEW, batch="aaa")
    res = tools.merge_lines("阴鸷", NEW)
    assert res["added"] == 0 and res["duplicates"] == 3


def test_合并_写到独立批次文件_查找时自动合并(ddir):
    tools.merge_lines("阴鸷", {"greet": {"陌生": ["主文件的一句。"]}})
    res = tools.merge_lines("阴鸷", {"greet": {"陌生": ["批次文件的一句。"]}}, batch="第二批")
    assert res["path"].endswith("阴鸷.第二批.json")
    assert {p.name for p in bd.files_for("阴鸷")} == {"阴鸷.json", "阴鸷.第二批.json", "阴鸷.记忆.json", "阴鸷.拦路.json"}
    assert set(bd._load("阴鸷")["greet"]["陌生"]) == {"主文件的一句。", "批次文件的一句。"}
    assert bd.coverage("阴鸷")["greet"]["陌生"] == 2


def test_合并_批次文件可以追加(ddir):
    tools.merge_lines("阴鸷", {"greet": {"陌生": ["一"]}}, batch="x")
    tools.merge_lines("阴鸷", {"greet": {"陌生": ["二"]}}, batch="x")
    doc = json.loads((ddir / "阴鸷.x.json").read_text(encoding="utf-8"))
    assert doc["lines"]["greet"]["陌生"] == ["一", "二"]


@pytest.mark.parametrize("payload", [NEW, NEW["lines"], json.dumps(NEW, ensure_ascii=False), json.dumps(NEW["lines"], ensure_ascii=False)])
def test_合并_接受几种输出格式(ddir, payload):
    res = tools.merge_lines("阴鸷", payload, dry_run=True)
    assert res["ok"] and res["added"] == 3


@pytest.mark.parametrize("payload,words", [
    ("不是json", "不是合法"),
    ("[1, 2]", "顶层"),
    ({"nope": {"陌生": ["x"]}}, "未知场景"),
    ({"greet": {"路人": ["x"]}}, "未知档位"),
    ({"greet": {"陌生": ["你好{name}"]}}, "占位符"),
    ({"greet": {"陌生": ["你好{player"]}}, "花括号"),
    ({"greet": {"陌生": ["字" * 100]}}, "超过"),
    ({"greet": {"陌生": ["  "]}}, "空台词"),
    ({"greet": "不是对象"}, "档位"),
])
def test_合并_格式不对一律不写(ddir, payload, words):
    before = sorted(p.name for p in ddir.glob("*.json"))
    res = tools.merge_lines("阴鸷", payload)
    assert res["ok"] is False and any(words in e for e in res["errors"]), res
    assert sorted(p.name for p in ddir.glob("*.json")) == before, "校验不过不能留下任何文件"


def test_合并_一半对一半错也整份退回(ddir):
    res = tools.merge_lines("阴鸷", {"greet": {"陌生": ["好的一句。", "坏的{x}"]}})
    assert res["ok"] is False and not (ddir / "阴鸷.json").exists()


def test_合并_未知原型和坏批次名(ddir):
    assert tools.merge_lines("不存在", NEW)["ok"] is False
    for bad in ("", "a.b", "a/b", "json"):
        assert tools.merge_lines("阴鸷", NEW, batch=bad)["ok"] is False, bad


def test_合并_试运行不写文件(ddir):
    res = tools.merge_lines("阴鸷", NEW, dry_run=True)
    assert res["ok"] and res["added"] == 3 and not (ddir / "阴鸷.json").exists()


def test_合并_通用台词也能追加(ddir):
    res = tools.merge_lines(bd.DEFAULT, {"greet": {"陌生": ["通用的新一句。"]}})
    assert res["ok"] and "通用的新一句。" in bd._load(bd.DEFAULT)["greet"]["陌生"]


def test_合并_落盘顺序按场景档位规定(ddir):
    tools.merge_lines("阴鸷", {"gift_love": {"至交": ["b"]}, "greet": {"至交": ["z"], "陌生": ["a"]}})
    doc = json.loads((ddir / "阴鸷.json").read_text(encoding="utf-8"))
    assert list(doc["lines"]) == ["greet", "gift_love"] and list(doc["lines"]["greet"]) == ["陌生", "至交"]


def test_合并_没有新内容不改文件(ddir):
    tools.merge_lines("阴鸷", NEW)
    before = (ddir / "阴鸷.json").stat().st_mtime_ns
    tools.merge_lines("阴鸷", NEW)
    assert (ddir / "阴鸷.json").stat().st_mtime_ns == before


# ---- 批次文件机制本身 -------------------------------------------------------

def test_批次文件属于哪个原型():
    assert bd.archetype_of(Path("豪爽.json")) == "豪爽" and bd.archetype_of(Path("豪爽.第二批.json")) == "豪爽"


def test_批次文件的_archetype_字段必须对(ddir):
    (ddir / "阴鸷.坏批次.json").write_text(json.dumps({"archetype": "豪爽", "lines": {}}), encoding="utf-8")
    assert any("archetype 字段应为 '阴鸷'" in e for e in bd.validate_all())


def test_批次文件也被校验(ddir):
    (ddir / "阴鸷.坏批次.json").write_text(json.dumps({"archetype": "阴鸷", "lines": {"greet": {"陌生": ["{bad}"]}}}), encoding="utf-8")
    assert any("占位符" in e for e in bd.validate_all())


def test_批次文件之间重复的句子只留一份(ddir):
    for name in ("a", "b"):
        (ddir / f"阴鸷.{name}.json").write_text(json.dumps({"archetype": "阴鸷", "lines": {"greet": {"陌生": ["同一句。", f"{name}独有。"]}}}), encoding="utf-8")
    bd.reload()
    assert bd._load("阴鸷")["greet"]["陌生"] == ["同一句。", "a独有。", "b独有。"]


def test_通用台词不受批次文件影响完整性要求(ddir):
    (ddir / "_default.补充.json").write_text(json.dumps({"archetype": "_default", "lines": {"greet": {"陌生": ["补一句。"]}}}), encoding="utf-8")
    assert bd.validate_all() == []


# ---- 命令行 -----------------------------------------------------------------

def run_cli(*args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(list(args))
    return code, buf.getvalue()


def test_命令行_check(ddir):
    code, out = run_cli("check")
    assert code == 0 and "全部合法" in out
    (ddir / "阴鸷.json").write_text(json.dumps({"archetype": "阴鸷", "lines": {"nope": {}}}), encoding="utf-8")
    code, out = run_cli("check")
    assert code == 1 and "未知场景" in out


def test_命令行_coverage(ddir):
    code, out = run_cli("coverage", "豪爽", "--target", "1")
    assert code == 0 and "| 豪爽 |" in out and "阴鸷" not in out


def test_命令行_prompt(ddir):
    code, out = run_cli("prompt", "阴鸷", "--scenes", "greet", "--tiers", "陌生,至交", "-n", "5")
    assert code == 0 and "各写 **5** 句" in out and "`greet`" in out and "**熟识**" not in out


def test_命令行_merge(ddir, tmp_path):
    f = tmp_path / "reply.json"
    f.write_text(json.dumps(NEW, ensure_ascii=False), encoding="utf-8")
    code, out = run_cli("merge", "阴鸷", str(f), "--batch", "gpt")
    assert code == 0 and "新增 3 句" in out and (ddir / "阴鸷.gpt.json").exists()
    code, out = run_cli("merge", "阴鸷", str(f), "--batch", "gpt", "--dry-run")
    assert code == 0 and "试运行" in out and "重复跳过 3" in out


def test_命令行_merge_坏稿子退出码为一(ddir, tmp_path):
    f = tmp_path / "bad.json"
    f.write_text('{"greet": {"陌生": ["{bad}"]}}', encoding="utf-8")
    code, out = run_cli("merge", "阴鸷", str(f))
    assert code == 1 and "未写入" in out and "占位符" in out


def test_命令行_merge_从标准输入读(ddir, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(NEW, ensure_ascii=False)))
    code, out = run_cli("merge", "阴鸷", "-", "--dry-run")
    assert code == 0 and "新增 3 句" in out


# ---- 新增性格原型的配套数据 --------------------------------------------------

def test_每个性格原型的配套数据都齐全():
    """新增一个性格原型要同时补齐这些数据，漏了任何一处这里就红（清单见 data/CONTENT_GUIDE.md）。"""
    from utils import bot_economy as be
    from utils import bot_legends as bl
    from utils.bot_social import load_archetypes
    names = set(load_archetypes())
    cfg = be.load_config()
    assert set(cfg["money"]) == names, "data/bot_economy.json 的 money（随身比例 / 开销）"
    assert set(cfg["combat"]["reaction"]) == names, "data/bot_economy.json 的 combat.reaction（被擒获后的处置权重）"
    assert set(bl.load()["epithets"]) == names and set(bl.load()["backstories"]) == names, "data/bot_legends.json（天骄称号 / 背景）"
    assert set(tools.load_voices()["archetypes"]) == names, "data/bot_voices.json（AI 写作角色卡）"
    from utils import bot_ambush, bot_grudges, bot_profile, bot_ties
    assert set(bot_ambush.load()["outcome"]) == names and set(bot_ambush.load()["buyout"]["accept"]) == names, "data/bot_ambush.json（拦路处置权重 / 买命意愿）"
    assert names <= set(bot_grudges.load()["windows"]) and names <= set(bot_grudges.load()["renew"]), "data/bot_grudges.json（蹲守年数 / 续期概率）"
    assert set(bot_profile.load()["archetypes"]) == names, "data/bot_profiles.json（行为画像：守序 / 冲动 / 义气 / 记仇 / 容量 / 偏离）"
    assert {x for row in bot_ties.load()["affinity"]["pairs"] for x in row[:2]} == names, "data/bot_ties.json（关系网：性格之间的亲和度）"
    assert set(cfg["public_events"]["auction"]["interest"]["equipment"]) <= names
    assert set(cfg["public_events"]["auction"]["interest"]["technique"]) <= names
    for p in bd.DIR.glob("*.json"):                                            # 台词文件只能属于已有的原型（或通用）
        assert bd.archetype_of(p) in names | {bd.DEFAULT}, p.name


# ---- 特质池的扩写工具 --------------------------------------------------------

@pytest.fixture
def traits_dir(tmp_path, monkeypatch):
    from utils import bot_traits as bt
    for f in bt.DIR.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    monkeypatch.setattr(bt, "DIR", tmp_path)
    bt.reload()
    yield tmp_path
    bt.reload()


NEW_ORIGIN = {"盐商": {"desc": "贩盐的", "weights": {"贪财": 3}, "rules": [{"swap": {"道友": "掌柜"}, "suffix": ["价钱好商量。"], "suffix_p": 0.1}]}}


def test_特质提示词_包含规则说明_已有条目_示例_格式():
    p = tools.traits_prompt("origins", 6)
    assert "扩写 6 个新条目" in p and "swap:" in p and "end_particles" in p and "max_clauses" in p
    assert "农户" in p and "渔村" in p and "```json" in p and "新条目名必须与已有的不同" in p
    assert "weights" in p and "性格原型有：豪爽" in p


def test_特质提示词_嗜好往事没有规则说明():
    for pool in ("hobbies", "pasts"):
        p = tools.traits_prompt(pool)
        assert "remarks" in p and "## 改写规则" not in p


def test_特质提示词_口头禅():
    p = tools.traits_prompt("catchphrases", 10)
    assert "通用" in p and "句首" in p and "阴鸷" in p and "说实话，" in p


def test_特质提示词_未知池():
    with pytest.raises(ValueError):
        tools.traits_prompt("不存在")


def test_特质合并_新条目写入(traits_dir):
    from utils import bot_traits as bt
    res = tools.traits_merge("origins", NEW_ORIGIN)
    assert res["ok"] and res["added"] == 1 and res["skipped"] == 0 and res["path"].endswith("origins.json")
    assert "盐商" in bt.pool("origins")
    assert "盐商" in json.loads((traits_dir / "origins.json").read_text(encoding="utf-8"))["origins"]


def test_特质合并_已存在的跳过_批次文件(traits_dir):
    from utils import bot_traits as bt
    res = tools.traits_merge("origins", {**NEW_ORIGIN, "农户": NEW_ORIGIN["盐商"]}, batch="aaa")
    assert res["ok"] and res["added"] == 1 and res["skipped"] == 1 and res["path"].endswith("origins.aaa.json")
    assert "盐商" in bt.pool("origins")
    assert not (traits_dir / "origins.json").read_text(encoding="utf-8").count("盐商")


def test_特质合并_接受带外层键的格式和字符串(traits_dir):
    assert tools.traits_merge("origins", {"origins": NEW_ORIGIN}, dry_run=True)["added"] == 1
    assert tools.traits_merge("origins", json.dumps(NEW_ORIGIN, ensure_ascii=False), dry_run=True)["added"] == 1


@pytest.mark.parametrize("entry,words", [
    ({"desc": "x", "rules": [{"乱写": 1}]}, "未知规则键"),
    ({"desc": "x", "rules": [{"prefix_p": 3}]}, "0~1"),
    ({"desc": "x", "rules": [{"swap": {"我": "{x}"}}]}, "花括号"),
    ({"desc": "x", "weights": {"不存在": 1}, "rules": [{"swap": {"我": "俺"}}]}, "weights"),
    ({"rules": [{"swap": {"我": "俺"}}]}, "desc"),
    ({"desc": "x"}, "rules"),
])
def test_特质合并_不合格一律不写(traits_dir, entry, words):
    before = (traits_dir / "origins.json").read_text(encoding="utf-8")
    res = tools.traits_merge("origins", {"坏条目": entry})
    assert res["ok"] is False and any(words in e for e in res["errors"]), res
    assert (traits_dir / "origins.json").read_text(encoding="utf-8") == before
    assert not list(traits_dir.glob("origins.*.json"))


def test_特质合并_坏输入():
    assert tools.traits_merge("origins", "不是json")["ok"] is False
    assert tools.traits_merge("origins", "[1]")["ok"] is False
    assert tools.traits_merge("不存在", {})["ok"] is False
    for bad in ("", "a.b", "a/b", "json"):
        assert tools.traits_merge("origins", NEW_ORIGIN, batch=bad)["ok"] is False


def test_特质合并_口头禅(traits_dir):
    from utils import bot_traits as bt
    res = tools.traits_merge("catchphrases", {"阴鸷": ["新口头禅一。", "呵，"], "通用": ["通用新一句。"]})
    assert res["ok"] and res["added"] == 2 and res["skipped"] == 1               # 『呵，』已有
    assert "新口头禅一。" in bt.pool("catchphrases")["阴鸷"]
    assert tools.traits_merge("catchphrases", {"不是原型": ["x"]})["ok"] is False
    assert tools.traits_merge("catchphrases", {"阴鸷": "不是列表"})["ok"] is False
    assert tools.traits_merge("catchphrases", {"阴鸷": ["{bad}"]})["ok"] is False


def test_特质合并_嗜好往事(traits_dir):
    ok = {"集邮": {"desc": "爱集邮", "remarks": ["新得了一枚好邮票。", "集邮这事，一旦上瘾就停不下来。"]}}
    assert tools.traits_merge("hobbies", ok)["ok"]
    assert tools.traits_merge("hobbies", {"坏": {"desc": "x", "remarks": ["只有一条"]}})["ok"] is False
    assert tools.traits_merge("pasts", {"坏": {"desc": "x", "remarks": ["含{花括号}的", "正常的一条"]}})["ok"] is False


def test_特质合并_试运行不写(traits_dir):
    before = sorted(p.name for p in traits_dir.glob("*.json"))
    assert tools.traits_merge("origins", NEW_ORIGIN, batch="x", dry_run=True)["added"] == 1
    assert sorted(p.name for p in traits_dir.glob("*.json")) == before


def test_特质合并_不把已有的错误算到新稿子头上(traits_dir):
    from utils import bot_traits as bt
    d = json.loads((traits_dir / "hobbies.json").read_text(encoding="utf-8"))
    d["hobbies"]["品茶"]["remarks"] = ["只有一条"]                                  # 已有的坏数据
    (traits_dir / "hobbies.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    bt.reload()
    assert tools.traits_merge("origins", NEW_ORIGIN, dry_run=True)["ok"] is True


def test_抽样看多样性():
    out = tools.sample_lines("豪爽", "greet", "陌生", n=10)
    assert len(out) == 10 and all(l.startswith("[出身：") for l in out) and len(set(out)) >= 7
    assert out == tools.sample_lines("豪爽", "greet", "陌生", n=10), "同一个种子结果可复现"
    assert out != tools.sample_lines("豪爽", "greet", "陌生", n=10, seed=2)
    assert not any("{" in l for l in out)


def test_命令行_特质():
    code, out = run_cli("traits-prompt", "habits", "-n", "4")
    assert code == 0 and "扩写 4 个新条目" in out
    code, out = run_cli("sample", "阴鸷", "greet", "陌生", "-n", "5")
    assert code == 0 and len(out.strip().splitlines()) == 5


def test_命令行_特质合并(traits_dir, tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps(NEW_ORIGIN, ensure_ascii=False), encoding="utf-8")
    code, out = run_cli("traits-merge", "origins", str(f), "--batch", "x")
    assert code == 0 and "新增 1 个" in out and (traits_dir / "origins.x.json").exists()
    code, out = run_cli("traits-merge", "origins", str(f), "--batch", "x")
    assert code == 0 and "新增 0 个" in out and "已存在跳过 1" in out
    f.write_text('{"坏": {"desc": "x", "rules": [{"乱写": 1}]}}', encoding="utf-8")
    code, out = run_cli("traits-merge", "origins", str(f))
    assert code == 1 and "未写入" in out and "未知规则键" in out


def test_命令行_check_包含特质池(traits_dir):
    code, out = run_cli("check")
    assert code == 0
    d = json.loads((traits_dir / "zodiac.json").read_text(encoding="utf-8"))
    d["signs"]["白羊"]["rules"][0]["prefix_p"] = 9
    (traits_dir / "zodiac.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    from utils import bot_traits as bt
    bt.reload()
    code, out = run_cli("check")
    assert code == 1 and "0~1" in out


def test_特质合并_没有新内容不建文件(traits_dir):
    assert tools.traits_merge("origins", {"农户": NEW_ORIGIN["盐商"]}, batch="y")["added"] == 0
    assert not (traits_dir / "origins.y.json").exists()
