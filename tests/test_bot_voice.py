"""机器人的说话特质与改写（utils/bot_traits.py、utils/bot_voice.py、data/bot_traits/）。

用户的目标：遇到 100 个机器人，说话方式都不太一样（纯文案，不影响数值）。所以测试分四块：
· 数据与规则的校验（AI 会往里加内容，格式错误要被拦住）；
· 改写引擎的每一种规则、占位符保护、兜底；
· 多样性本身（同性格同场景同档位的一百个人，句子要真的不同；内向的话少、外向的话多）；
· 接入：生成时抽特质、老机器人补特质、`say` 用上特质、资料页展示。
"""

import json
import random
import re
import shutil
import statistics
from collections import Counter

import pytest
from sqlalchemy import select

from tests.conftest import make_player
from utils import bot_dialogue as bd
from utils import bot_social as bs
from utils import bot_traits as bt
from utils import bot_voice as bv
from utils import bot_world
from utils.views.bot_actions import profile_lines

ARCHETYPES = sorted(__import__("utils.bot_social", fromlist=["x"]).load_archetypes())


# ---- 数据校验 ---------------------------------------------------------------

def test_特质池合法():
    assert bt.validate_pools() == []


def test_各池规模够用():
    assert len(bt.pool("zodiac")) == 12 and len(bt.pool("origins")) >= 12 and len(bt.pool("habits")) >= 10
    assert len(bt.pool("hobbies")) >= 12 and len(bt.pool("pasts")) >= 10 and len(bt.pool("catchphrases")["通用"]) >= 25
    assert list(bt.pool("introversion")) == bt.LEVELS_ORDER
    # 组合数远大于机器人上限（2000）
    combos = 12 * len(bt.pool("origins")) * len(bt.pool("habits")) * len(bt.pool("hobbies")) * len(bt.pool("pasts")) * 5
    assert combos > 100_000


@pytest.mark.parametrize("rule,words", [
    ("不是对象", "应是对象"),
    ({"乱写": 1}, "未知规则键"),
    ({"prefix_p": 2}, "0~1"),
    ({"max_clauses": 0}, "max_clauses"),
    ({"swap": {}}, "非空对象"),
    ({"swap": {"": "x"}}, "不合法"),
    ({"swap": {"我": "{player}"}}, "花括号"),
    ({"prefix": []}, "非空列表"),
    ({"prefix": ["{x}"]}, "不合法"),
    ({"suffix": ["字" * 30]}, "不合法"),
    ({"end_particles": ["啦啦"]}, "一个字"),
    ({"tiers": ["路人"]}, "tiers"),
    ({"scenes": ["nope"]}, "scenes"),
    ({"punct": {"！": "{"}}, "不合法"),
    ({"suffix": ["我再多说一句，"]}, "句尾补话"),
    ({"suffix": ["没有标点"]}, "句尾补话"),
    ({"prefix": ["说起来。"]}, "句首补话"),
    ({"prefix": ["没有标点"]}, "句首补话"),
])
def test_规则校验器抓得住错误(rule, words):
    errors = bt.validate_rule(rule, "x")
    assert errors and any(words in e for e in errors), errors


def test_合法规则无错误():
    assert bt.validate_rule({"swap": {"我": "俺"}, "swap_p": 0.5, "prefix": ["嗯，"], "prefix_p": 1, "tiers": ["陌生"],
                             "scenes": ["greet"], "max_clauses": 2, "end_particles": ["啦"], "end_p": 0.1,
                             "punct": {"！": "。"}, "ellipsis_p": 0.2}, "x") == []


@pytest.fixture
def tdir(tmp_path, monkeypatch):
    for f in bt.DIR.glob("*.json"):
        shutil.copy(f, tmp_path / f.name)
    monkeypatch.setattr(bt, "DIR", tmp_path)
    bt.reload()
    yield tmp_path
    bt.reload()


def test_池校验器抓得住池里的错误(tdir):
    d = json.loads((tdir / "origins.json").read_text(encoding="utf-8"))
    d["origins"]["农户"]["weights"] = {"不存在的性格": 1}
    d["origins"]["书香"]["rules"] = []
    d["origins"]["商贾"].pop("desc")
    (tdir / "origins.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    h = json.loads((tdir / "hobbies.json").read_text(encoding="utf-8"))
    h["hobbies"]["品茶"]["remarks"] = ["只有一条"]
    h["hobbies"]["钓鱼"]["remarks"] = ["含{花括号}的一条", "正常的一条"]
    (tdir / "hobbies.json").write_text(json.dumps(h, ensure_ascii=False), encoding="utf-8")
    c = json.loads((tdir / "catchphrases.json").read_text(encoding="utf-8"))
    c["不是原型"] = ["x"]
    c["通用"] = c["通用"][:3]
    (tdir / "catchphrases.json").write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    i = json.loads((tdir / "introversion.json").read_text(encoding="utf-8"))
    i["levels"]["中性"]["talk_max"] = 10
    (tdir / "introversion.json").write_text(json.dumps(i, ensure_ascii=False), encoding="utf-8")
    bt.reload()
    text = "\n".join(bt.validate_pools())
    for words in ("weights", "需要 rules", "缺 desc", "remarks 至少", "花括号", "不是性格原型", "至少 10 条", "talk_max"):
        assert words in text, words


def test_批次文件自动合并(tdir):
    (tdir / "origins.第二批.json").write_text(json.dumps({"origins": {"盐商": {"desc": "贩盐的", "rules": [
        {"swap": {"道友": "掌柜"}}]}, "农户": {"desc": "x", "rules": [{"suffix": ["多一条规则。"], "suffix_p": 0.1}]}}}, ensure_ascii=False), encoding="utf-8")
    (tdir / "hobbies.补充.json").write_text(json.dumps({"hobbies": {"品茶": {"desc": "x", "remarks": ["批次里新增的一句品茶。", "我这壶茶，泡了三遍了。"]}}}, ensure_ascii=False), encoding="utf-8")
    (tdir / "catchphrases.补充.json").write_text(json.dumps({"阴鸷": ["批次口头禅。"], "通用": []}, ensure_ascii=False), encoding="utf-8")
    bt.reload()
    assert "盐商" in bt.pool("origins") and len(bt.pool("origins")["农户"]["rules"]) == 2, "已有条目的规则追加，原有的保留"
    assert "批次里新增的一句品茶。" in bt.pool("hobbies")["品茶"]["remarks"] and len(bt.pool("hobbies")["品茶"]["remarks"]) == 5
    assert "批次口头禅。" in bt.pool("catchphrases")["阴鸷"]
    assert bt.validate_pools() == []


# ---- 抽特质 -----------------------------------------------------------------

@pytest.mark.parametrize("talk,level", [(0, "内向"), (10, "内向"), (30, "偏内向"), (55, "中性"), (75, "偏外向"), (95, "外向"), (100, "外向")])
def test_内向外向由健谈数值决定(talk, level):
    got = Counter(bt.introversion_of(talk, random.Random(i)) for i in range(200))
    assert got.most_common(1)[0][0] == level
    assert set(got) <= set(bt.LEVELS_ORDER)


def test_抽特质可复现且引用都有效():
    a = bt.roll_traits("阴鸷", 30, random.Random(5))
    assert a == bt.roll_traits("阴鸷", 30, random.Random(5))
    for seed in range(300):
        t = bt.roll_traits(random.Random(seed).choice(ARCHETYPES), random.Random(seed).randint(0, 100), random.Random(seed))
        assert t["introversion"] in bt.LEVELS_ORDER and t["zodiac"] in bt.pool("zodiac")
        assert t["origin"] in bt.pool("origins") and t["hobby"] in bt.pool("hobbies") and t["past"] in bt.pool("pasts")
        assert 1 <= len(t["habits"]) <= 2 and len(set(t["habits"])) == len(t["habits"]) and set(t["habits"]) <= set(bt.pool("habits"))
        assert 1 <= len(t["catchphrases"]) <= 2 and len(set(t["catchphrases"])) == len(t["catchphrases"])
        assert all(p in sum(bt.pool("catchphrases").values(), []) for p in t["catchphrases"])


def test_权重让性格和特质相配():
    def freq(arche, field, value, n=600):
        hits = 0
        for i in range(n):
            t = bt.roll_traits(arche, 50, random.Random(i))
            hits += value in (t[field] if isinstance(t[field], list) else [t[field]])
        return hits / n
    assert freq("迂腐", "habits", "文言腔") > 3 * freq("憨直", "habits", "文言腔")
    assert freq("憨直", "habits", "乡土腔") > 3 * freq("迂腐", "habits", "乡土腔")
    assert freq("贪财", "origin", "商贾") > 3 * freq("迂腐", "origin", "商贾")
    assert freq("高冷", "habits", "冷面") > freq("话痨", "habits", "冷面")


def test_权重为零的永远抽不到():
    d = {"a": {"weights": {"阴鸷": 0}}, "b": {"weights": {"阴鸷": 1}}}
    assert {bt._weighted(d, "阴鸷", random.Random(i))[0] for i in range(50)} == {"b"}
    assert bt._weighted({"a": {"weights": {"阴鸷": 0}}}, "阴鸷", random.Random(1)) == []


def test_资料页描述():
    t = {"origin": "渔村", "zodiac": "天蝎", "introversion": "内向"}
    assert bt.describe(t) == "出身：渔村 · 天蝎座 · 内向" and bt.describe(None) == "" and bt.describe({}) == ""


# ---- 改写引擎 ---------------------------------------------------------------

R = random.Random


def apply(text, rule, seed=1):
    return bv._apply(text, rule, R(seed))


def test_替换_只改占位符之外():
    assert apply("我给{player}送{item}，你收下。", {"swap": {"我": "在下", "你": "阁下"}}) == "在下给{player}送{item}，阁下收下。"
    assert apply("{player}我很好。", {"swap": {"player": "X", "我": "俺"}}) == "{player}俺很好。", "占位符里的字不动"


def test_替换_长词优先_概率可控():
    assert apply("道友好道", {"swap": {"道": "X", "道友": "老哥"}}) == "老哥好X"
    outs = {apply("我来了。", {"swap": {"我": "俺"}, "swap_p": 0.5}, seed=s) for s in range(30)}
    assert outs == {"我来了。", "俺来了。"}


def test_标点_省略号_语气词():
    assert apply("好！走！", {"punct": {"！": "。"}}) == "好。走。"
    assert apply("你好，走吧。", {"ellipsis_p": 1.0}) == "你好……走吧。"
    assert apply("你好。", {"ellipsis_p": 1.0}) == "你好。", "没有逗号就不动"
    assert apply("你好。", {"end_particles": ["啦"], "end_p": 1.0}) == "你好啦。"
    assert apply("你好啦。", {"end_particles": ["啦"], "end_p": 1.0}) == "你好啦。", "已经带语气词不再叠加"
    assert apply("你好", {"end_particles": ["啦"], "end_p": 1.0}) == "你好啦"


def test_语气词不会插进占位符里():
    out = apply("收下{item}。", {"end_particles": ["啦"], "end_p": 1.0})
    assert "{item}" in out


def test_前缀后缀_不重复():
    assert apply("好。", {"prefix": ["嗯，"], "prefix_p": 1.0, "suffix": ["对吧？"], "suffix_p": 1.0}) == "嗯，好。对吧？"
    assert apply("嗯，好。", {"prefix": ["嗯，"], "prefix_p": 1.0}) == "嗯，好。"
    assert apply("好。对吧？", {"suffix": ["对吧？"], "suffix_p": 1.0}) == "好。对吧？"
    assert apply("好。", {"prefix": ["嗯，"], "prefix_p": 0.0}) == "好。"


def test_截断_保留前几句():
    assert bv._truncate("一。二！三？", 2) == "一。二！" and bv._truncate("一。", 3) == "一。" and bv._truncate("没标点", 1) == "没标点"


def test_规则按档位和场景生效():
    traits = {"introversion": "中性", "origin": "渔村", "habits": [], "zodiac": "天蝎", "catchphrases": [], "hobby": "品茶", "past": "受过骗"}
    hostile = bv.active_rules(traits, "greet", "仇视")
    close = bv.active_rules(traits, "greet", "至交")
    assert any("我记着" in "".join(r.get("suffix", [])) or "我记性好" in "".join(r.get("suffix", [])) for r in hostile)
    assert not any("我记性好" in "".join(r.get("suffix", [])) for r in close)
    assert any("这话只对你说" in "".join(r.get("suffix", [])) for r in close)
    only = {"tiers": ["陌生"], "scenes": ["greet"], "prefix": ["x"], "prefix_p": 1.0}
    traits2 = {"introversion": "中性", "origin": "渔村", "habits": [], "zodiac": "摩羯", "catchphrases": [], "hobby": "品茶", "past": "立过誓"}
    assert only not in bv.active_rules(traits2, "greet", "陌生"), "池里没有这条，自然没有"
    seen = []
    orig = bt.pool("zodiac")["摩羯"]["rules"]
    try:
        bt.pool("zodiac")["摩羯"]["rules"] = orig + [only]
        for scene, tier, expect in (("greet", "陌生", True), ("greet", "熟识", False), ("chat_again", "陌生", False)):
            seen.append((only in bv.active_rules(traits2, scene, tier)) == expect)
    finally:
        bt.pool("zodiac")["摩羯"]["rules"] = orig
    assert all(seen), "限定了档位和场景的规则只在对应的档位 / 场景生效"


def test_style_没有特质原样返回():
    assert bv.style("你好。", None, "greet", "陌生") == "你好。" and bv.style("你好。", {}, "greet", "陌生") == "你好。"
    assert bv.style("", {"introversion": "外向"}, "greet", "陌生") == ""


def test_style_内向取第一句():
    traits = {"introversion": "内向", "origin": "农户", "habits": ["言简意赅"], "zodiac": "摩羯", "catchphrases": [], "hobby": "品茶", "past": "立过誓"}
    for seed in range(40):
        out = bv.style("第一句。第二句。第三句。", traits, "greet", "陌生", R(seed))
        assert "第二句" not in out


def test_style_太长就退回骨架(monkeypatch):
    monkeypatch.setattr(bv, "MAX_STYLED_LEN", 5)
    traits = {"introversion": "外向", "origin": "农户", "habits": ["啰嗦"], "zodiac": "白羊", "catchphrases": ["很长的口头禅，"], "hobby": "品茶", "past": "立过誓"}
    assert bv.style("你好。", traits, "greet", "至交", R(1)) == "你好。"


def test_口头禅_前缀后缀按结尾判断():
    traits = {"introversion": "外向", "origin": "农户", "habits": [], "zodiac": "摩羯", "catchphrases": ["嗯，"], "hobby": "品茶", "past": "立过誓"}
    pre = {bv.style("好。", {**traits, "catchphrases": ["嗯，"]}, "greet", "陌生", R(s)) for s in range(60)}
    suf = {bv.style("好。", {**traits, "catchphrases": ["就这么回事。"]}, "greet", "陌生", R(s)) for s in range(60)}
    assert any(x.startswith("嗯，") for x in pre) and any(x.endswith("就这么回事。") for x in suf)


def test_插话_仇视从不_不在白名单场景不说():
    traits = {"introversion": "外向", "origin": "农户", "habits": [], "zodiac": "摩羯", "catchphrases": [], "hobby": "品茶", "past": "立过誓"}
    remarks = set(bt.pool("hobbies")["品茶"]["remarks"]) | set(bt.pool("pasts")["立过誓"]["remarks"])
    def has_remark(scene, tier, n=300):
        return any(any(r in bv.style("好。", traits, scene, tier, R(s)) for r in remarks) for s in range(n))
    assert has_remark("greet", "至交") and has_remark("greet", "熟识")
    assert not has_remark("greet", "仇视"), "仇视档从不插话"
    assert not has_remark("bot_killed", "至交") and not has_remark("captive_kill", "至交"), "遗言 / 杀戮场景不插闲话"


# ---- 兜底与安全：随机特质 × 所有场景 × 所有档位 × 所有原型 ----------------------

def test_任何组合都不会弄坏一句话():
    rng = R(11)
    for arche in ARCHETYPES:
        for scene in bd.SCENES:
            for tier in bd.TIERS:
                for _ in range(6):
                    traits = bt.roll_traits(arche, rng.randint(0, 100), R(rng.random()))
                    tpl = bd.pick_template(arche, scene, tier, rng)
                    out = bv.style(tpl, traits, scene, tier, rng)
                    assert out.strip() and len(out) <= bv.MAX_STYLED_LEN or out == tpl
                    assert not re.search(r"\{(?!player\}|bot\}|item\}|days\}|count\}|city\}|victim\})[^}]*\}", out), out
                    filled = bd.fill(out, player="甲", bot="乙", item="丙", days=4, count=3, city="丁", victim="戊")
                    assert filled and "{" not in filled
                    assert not out.startswith(("，", "。", "！", "？")), out


# ---- 多样性本身 -------------------------------------------------------------

def sample(arche, scene, tier, n=100, seed=3):
    out = []
    for i in range(n):
        rng = R(f"{seed}:{i}")
        traits = bt.roll_traits(arche, rng.randint(*__import__("utils.bot_social", fromlist=["x"]).load_archetypes()[arche]["talk"]), rng)
        out.append(bd.fill(bv.style(bd.pick_template(arche, scene, tier, rng), traits, scene, tier, rng), player="甲", bot="乙", item="灵芝"))
    return out


@pytest.mark.parametrize("arche", ARCHETYPES)
def test_一百个同性格机器人说同一场景_句子大都不同(arche):
    got = sample(arche, "greet", "陌生")
    assert len(set(got)) >= 60, f"{arche}：100 个人只有 {len(set(got))} 种说法"


def test_骨架台词本来很少_特质把它放大了很多倍():
    skeleton = {bd.fill(t, player="甲", bot="乙") for t in bd._candidates("阴鸷", "gift_hate", "陌生")}
    got = set(sample("阴鸷", "gift_hate", "陌生", n=200))
    assert len(skeleton) <= 3 and len(got) > 40


def test_内向的话比外向的少():
    def avg_len(level):
        lengths = []
        for i in range(150):
            rng = R(i)
            traits = bt.roll_traits("豪爽", 50, rng)
            traits["introversion"] = level
            lengths.append(len(bv.style("哈哈，道友面生得很，来，喝一杯！在下乙，道友怎么称呼？", traits, "greet", "陌生", rng)))
        return statistics.mean(lengths)
    assert avg_len("内向") < avg_len("中性") < avg_len("外向")


def test_同一个机器人每次说话也不会一模一样():
    traits = bt.roll_traits("话痨", 90, R(1))
    outs = {bv.style("你好，我来了。", traits, "greet", "熟识", R(s)) for s in range(40)}
    assert len(outs) >= 6


def test_不同出身的人称呼不同():
    names = Counter()
    for origin in bt.pool("origins"):
        traits = {"introversion": "中性", "origin": origin, "habits": [], "zodiac": "摩羯", "catchphrases": [], "hobby": "品茶", "past": "立过誓"}
        out = bv.style("道友好。", traits, "greet", "陌生", R(1))
        names[out.split("好")[0][:4]] += 1
    assert len(names) >= 8, "14 种出身至少有 8 种不同的称呼"


# ---- 接入 -------------------------------------------------------------------

async def mk(db, uid="bot_00001", traits=None, tier="正常", archetype="豪爽"):
    D = db["db_async"]
    p = make_player(D, uid)
    p.name, p.is_bot, p.current_city = f"道友{uid[-2:]}", True, "灵虚城"
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        s.add(D.BotPersonality(bot_id=uid, archetype=archetype, tier=tier, home_city="灵虚城",
                               traits=json.dumps(traits, ensure_ascii=False) if traits else ""))
        await s.commit()


async def human(db, uid="1001"):
    D = db["db_async"]
    p = make_player(D, uid)
    p.name, p.current_city = "玩家甲", "灵虚城"
    async with D.AsyncSessionLocal() as s:
        s.add(p)
        await s.commit()


async def test_生成时抽特质并存下来(db):
    await bot_world.generate_bots(30, R(2))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        rows = list((await s.execute(select(D.BotPersonality))).scalars())
    assert len(rows) == 30
    for r in rows:
        t = json.loads(r.traits)
        assert t["origin"] in bt.pool("origins") and t["zodiac"] in bt.pool("zodiac")
    assert len({r.traits for r in rows}) == 30, "没有两个机器人的特质完全一样"


async def test_特质可复现_同一个_id_得到同一份(db):
    await bot_world.generate_bots(3, R(2))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        row = (await s.execute(select(D.BotPersonality).order_by(D.BotPersonality.bot_id))).scalars().first()
        persona = await s.get(D.BotPersonality, row.bot_id)
    again = bt.roll_traits(persona.archetype, persona.talk, R(f"{row.bot_id}:traits"))
    assert json.loads(persona.traits) == again


async def test_老机器人每日结算时补上特质(db, monkeypatch):
    from utils import bot_economy as be
    from utils import bot_settle as bsl
    c = be.load_config()
    c["wild"]["trip_chance"] = 0
    c["speed"] = {k: 0.0 for k in c["speed"]}
    c["materials"]["jobs_per_day"] = 0
    monkeypatch.setattr(be, "load_config", lambda: json.loads(json.dumps(c)))
    await mk(db, traits=None)
    await bsl.run_settlement(rng=R(0))
    D = db["db_async"]
    async with D.AsyncSessionLocal() as s:
        first = (await s.get(D.BotPersonality, "bot_00001")).traits
    assert first and json.loads(first)["origin"] in bt.pool("origins")
    monkeypatch.setattr(bsl, "today", lambda: "2099-01-01")
    await bsl.run_settlement(rng=R(1))
    async with D.AsyncSessionLocal() as s:
        assert (await s.get(D.BotPersonality, "bot_00001")).traits == first, "补上之后不会再变"


async def test_say_用上特质_带特质的人说话和骨架不同(db):
    traits = {"introversion": "外向", "origin": "渔村", "habits": ["爱用语气词", "啰嗦"], "zodiac": "白羊",
              "catchphrases": ["哈哈，"], "hobby": "钓鱼", "past": "受过骗"}
    await mk(db, "bot_00001", traits)
    await mk(db, "bot_00002", None)
    await human(db)
    skeletons = {bd.fill(t, player="玩家甲", bot="道友01") for t in bd._candidates("豪爽", "greet", "陌生")}
    styled = {await bs.say("greet", "1001", "bot_00001") for _ in range(60)}
    plain = {await bs.say("greet", "1001", "bot_00002") for _ in range(60)}
    assert len(styled) > len(plain) and not styled <= skeletons
    assert all("玩家甲" in s or "{" not in s for s in styled)


async def test_say_特质为空时和以前一样(db):
    await mk(db, "bot_00002", None)
    await human(db)
    plain = {await bs.say("greet", "1001", "bot_00002") for _ in range(40)}
    skeletons = {bd.fill(t, player="玩家甲", bot="道友02") for t in bd._candidates("豪爽", "greet", "陌生")}
    assert plain <= skeletons


async def test_get_line_带特质(db):
    traits = {"introversion": "内向", "origin": "农户", "habits": ["言简意赅"], "zodiac": "摩羯", "catchphrases": [], "hobby": "品茶", "past": "立过誓"}
    out = bd.get_line("豪爽", "greet", "陌生", R(1), traits=traits, player="甲", bot="乙")
    assert "{" not in out and len(out) < 40


async def test_资料页显示出身星座内向外向(db):
    traits = bt.roll_traits("豪爽", 80, R(1))
    await mk(db, "bot_00001", traits)
    await human(db)
    lines = await profile_lines("1001", "bot_00001")
    assert bt.describe(traits) in lines and lines[0] == "性格：豪爽" and lines[1] == bt.describe(traits)
    await mk(db, "bot_00002", None)
    assert not any("出身" in l for l in await profile_lines("1001", "bot_00002"))


def test_迁移补上新列(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = tmp_path / "old.db"
    env = dict(os.environ, DB_PATH=str(path))

    def alembic(*a):
        return subprocess.run([sys.executable, "-m", "alembic", "-c", os.path.join(root, "alembic.ini"), *a],
                              cwd=root, env=env, capture_output=True, text=True)

    assert alembic("upgrade", "f2c6b9d41a37").returncode == 0
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE bot_personality DROP COLUMN traits")
    conn.execute("INSERT INTO bot_personality (bot_id, archetype) VALUES ('bot_00001', '豪爽')")
    conn.commit()
    conn.close()
    assert alembic("upgrade", "head").returncode == 0
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT traits FROM bot_personality").fetchone() == ("",)
    conn.close()
    assert alembic("upgrade", "head").returncode == 0


def test_内向外向在交界处有一点随机():
    near = Counter(bt.introversion_of(25, R(i)) for i in range(300))
    assert {"内向", "偏内向"} <= set(near)
    far = Counter(bt.introversion_of(10, R(i)) for i in range(300))
    assert set(far) == {"内向"}, "离交界远的不会跳档"
    assert bt.introversion_of(-50, R(1)) == "内向" and bt.introversion_of(500, R(1)) == "外向", "越界的数值夹回 0~100"


def test_口头禅多半来自自己性格的池子():
    own = set(bt.pool("catchphrases")["阴鸷"])
    picks = [p for i in range(300) for p in bt.roll_traits("阴鸷", 30, R(i))["catchphrases"]]
    share = sum(p in own for p in picks) / len(picks)
    assert 0.4 < share < 0.85, share
