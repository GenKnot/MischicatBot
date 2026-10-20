"""条件化文案库（U1·江湖百态 P5）：机器人主动搭话的台词，按『场景 × 一组条件』挑一句。

和 `bot_dialogue`（场景 × 好感档位 × 性格，固定三维）不同，这里每条**规则**自己声明适用条件（`when`），条件可以任意组合：
性格原型、好感档位、和玩家的关系、阵营 / 行为标签、出身、星座、内向外向、境界差、道贺的态度、事件、冲突种类……
规则越具体（条件越多）被抽中的权重越大（×2 每多一个条件），没写条件的规则是兜底，永远能被抽到，所以**每个场景必须至少有一条无条件规则**。

文件在 `data/bot_chatter/`：`<场景名>.json`（主文件）和 `<场景名>.<批次名>.json`（批次文件，AI 批量扩写时写这里，自动合并）。格式：

    {"scene": "chatter_arrive",
     "rules": [{"when": {"archetype": ["豪爽"], "tier": ["熟识", "至交"]}, "weight": 1, "lines": ["{player}！好久不见！"]}]}

`when` 里每个键的值是列表，条件之间是『且』，列表内是『或』。所有文字都是数据，不改代码；校验在 `validate_file / validate_all`，
AI 扩写用 `scripts/dialogue_tool.py chatter-prompt / chatter-merge`（见 data/CONTENT_GUIDE.md 第 4 节）。纯文案，不影响任何数值。
"""

import json
import random
import string
from functools import lru_cache
from pathlib import Path

from utils import bot_dialogue as bd
from utils import bot_profile
from utils import bot_traits as bt

DIR = Path(__file__).resolve().parent.parent / "data" / "bot_chatter"
MAX_LINE_LEN = 80

# 场景 → 这个场景的台词里额外允许的占位符（{player} {bot} 永远可用）
SCENES = {
    "chatter_arrive": {"city"},                    # 玩家来到了它所在的城
    "chatter_congrats": {"realm"},                 # 玩家突破了大境界
    "chatter_event_before": {"event", "city"},     # 公共事件开始时
    "chatter_event_after": {"event", "city"},      # 公共事件结束后
    "chatter_conflict_self": {"victim"},           # 它被玩家打劫 / 废修为之后（{victim} 是它自己，写『我』）
    "chatter_conflict_friend": {"victim"},         # 它的朋友被玩家打劫 / 废修为 / 击杀之后，来替朋友说话
    "chatter_mediate": {"victim"},                 # 劝架的人
    "reply_warm": set(), "reply_ok": set(), "reply_neutral": set(), "reply_cold": set(),     # 玩家用按钮回应后，它的一句话
    # 请求 / 委托（utils/bot_requests.py）：机器人开口相求，以及后续的还钱、赖账、办成
    "request_ask_borrow_stones": {"amount"}, "request_ask_borrow_item": {"item"},
    "request_ask_deliver_letter": {"target", "city"}, "request_ask_gather_together": {"what"},
    "request_thanks": set(), "request_declined": set(),
    "request_repay": {"amount"}, "request_repay_plus": {"amount"}, "request_repay_item": {"item"}, "request_short": {"amount"},
    "request_default": set(), "request_errand_arrive": {"asker"}, "request_gather_done": {"what"}, "request_failed": set(),
    # 玩家主动向机器人求助（借灵石 / 借物品 / 陪采集）
    "request_lend_accept": {"amount", "item", "what"}, "request_lend_refuse": set(), "request_dun": {"amount", "item"},
    "request_debt_cleared": {"amount", "item"}, "request_player_default": set(),
    # 失踪调查（utils/bot_investigation.py）：问玩家见没见过失踪的朋友、道谢、没线索、查出凶手
    "investigation_ask": {"missing"}, "investigation_thanks": {"missing"}, "investigation_ack": set(), "investigation_found": {"missing"},
}
SCENE_INFO = {                                  # 给 AI 看的场景说明（when = 什么时候说，beat = 这句话要做什么）
    "chatter_arrive": ("玩家来到了它所在的城，它迎上来打招呼", "按好感档位和关系决定热络还是冷淡；可以提{city}；别问太多问题，一句话就好"),
    "chatter_congrats": ("玩家突破了大境界，它来说一句", "语气由 attitude 决定：真心=衷心祝贺，酸=话里带刺，不服=想赶上你，觊觎=盯上了你的好处但不要明说；可提{realm}"),
    "chatter_event_before": ("公共事件（灵雨，可能带兽潮）开始时，它对在场的熟人说", "可提{event}和{city}；兽潮时更紧张 / 更有责任感"),
    "chatter_event_after": ("公共事件结束后，它对在场的熟人说", "可提{event}；回顾、吹牛、抱怨、关心都行"),
    "chatter_conflict_self": ("玩家打劫 / 废了它之后几分钟，它找上来放话", "kind=rob 是被劫，cripple 是被废修为；愤怒 / 不甘 / 委屈，按性格；至交档是失望而不是单纯凶"),
    "chatter_conflict_friend": ("玩家对它的朋友（{victim}）下手后，它来替朋友说话", "bond 是它和受害者的关系（结拜 / 同门 / 朋友 / 相识）：越近越狠；点出{victim}"),
    "chatter_mediate": ("冲突后，一个第三方出来劝架", "劝双方各退一步；可提{victim}；性格决定是和稀泥、讲道理还是不耐烦"),
    "reply_warm": ("玩家用很热情的态度回应了它", "高兴 / 感动，按性格表达"),
    "reply_ok": ("玩家客客气气地回应了它", "礼貌地收下，不过分热络"),
    "reply_neutral": ("玩家不冷不热地回应了它", "淡淡的一句，不要生气"),
    "reply_cold": ("玩家冷冷地回应了它", "有点受挫或不悦，但不要恶语相向"),
    "request_ask_borrow_stones": ("它缺钱，向熟人（玩家）开口借灵石", "点出借多少{amount}；按性格：豪爽爽快、贪财说有好买卖、阴鸷带点施压、高冷只说一句；别太卑微"),
    "request_ask_borrow_item": ("它缺一件东西，向熟人借", "点出要借的东西{item}；说明会还"),
    "request_ask_deliver_letter": ("它想请玩家替它给另一个人送信", "点出收信人{target}和所在的城{city}；语气客气或不客气按性格"),
    "request_ask_gather_together": ("它想请玩家陪它去采集", "点出采集的类型{what}（采药 / 采矿 / 伐木 / 钓鱼）；一个人怪闷的 / 想要个照应"),
    "request_thanks": ("玩家答应了它的请求", "道谢，按性格表达：豪爽痛快、迂腐文绉绉、阴鸷『我记下了』"),
    "request_declined": ("玩家婉拒了它的请求", "不要生气，最多失望或无所谓；不要说成玩家的错"),
    "request_repay": ("它按时把借的灵石还给玩家", "点出还的数目{amount}；按性格：守信的坦然、爽快的顺带请客"),
    "request_repay_plus": ("它还钱时多还了一些（感念玩家当年相助）", "点出总数{amount}，说明多出来的是谢意"),
    "request_repay_item": ("它归还了借的物品", "点出物品{item}"),
    "request_short": ("它想还钱但手头不够，先还了一部分", "还欠{amount}，保证以后补上"),
    "request_default": ("它欠了玩家的账，一直不还（被玩家碰上）", "按性格：赖皮、装傻、冷淡、翻脸；不要写成露骨威胁"),
    "request_errand_arrive": ("玩家替人送的信送到了，收信人（它）说话", "点出托信的人{asker}，表示收到并道谢"),
    "request_gather_done": ("玩家陪它采集完毕", "点出{what}，高兴 / 满意，按性格"),
    "request_failed": ("玩家答应的事没办成，期限已过", "失望或淡淡地说算了，不要辱骂玩家"),
    "request_lend_accept": ("玩家向它求助（借灵石 / 借物品 / 陪采集），它答应了", "点出借的数目{amount}或物品{item}或陪采集的{what}（用到哪个写哪个）；按性格：豪爽痛快、贪财提醒要还、阴鸷带点施压"),
    "request_lend_refuse": ("玩家向它求助，它婉拒了", "不要羞辱玩家；原因含糊带过（手头紧 / 没空 / 不方便）；仇视的人可以冷"),
    "request_dun": ("借给玩家的钱 / 物品到期了，它来催", "点出{amount}灵石或{item}；语气按性格从客气到施压；别威胁人身"),
    "request_debt_cleared": ("玩家还清了欠它的账", "点出{amount}或{item}；满意 / 感慨，按性格"),
    "request_player_default": ("玩家欠的账过了宽限期还是不还，它翻脸", "失望 / 愤怒，按性格；会记仇但不要写成死亡威胁"),
    "investigation_ask": ("它的朋友{missing}失踪了，它在找，在城里遇到玩家就问", "问『见过{missing}吗』；担心 / 焦急 / 冷淡按性格；别暗示玩家是凶手"),
    "investigation_thanks": ("玩家给了它一条真线索", "道谢，点出{missing}；按性格"),
    "investigation_ack": ("玩家说没见过 / 不想说，或给的是条没用的线索", "平淡地接受，不要追问"),
    "investigation_found": ("它查出来凶手就是眼前的玩家", "震惊 / 愤怒 / 冷静地宣战，点出{missing}；不要写成直接动手的描写"),
}
RELATIONS = ("结拜", "同门", "朋友", "相识", "仇敌", "无")
REALM_GAPS = ("higher", "equal", "lower")               # 它的大境界相对玩家
ATTITUDES = ("真心", "酸", "不服", "觊觎")
EVENTS = ("灵雨", "兽潮", "拍卖")
KINDS = ("rob_fail", "rob", "cripple", "kill")
TAGS = ("守序善良", "中立善良", "混乱善良", "守序中立", "绝对中立", "混乱中立", "守序邪恶", "中立邪恶", "混乱邪恶",
        "冲动", "谨慎", "重义气", "记仇", "好打抱不平")
WHEN_KEYS = {"archetype", "tier", "relation", "tags", "origin", "zodiac", "introversion", "realm_gap", "attitude", "event",
             "kind", "bond"}


def valid_values(key: str) -> set | None:
    from utils.bot_social import load_archetypes
    return {
        "archetype": set(load_archetypes()), "tier": set(bd.TIERS), "relation": set(RELATIONS), "tags": set(TAGS),
        "origin": set(bt.pool("origins")), "zodiac": set(bt.pool("zodiac")), "introversion": set(bt.pool("introversion")),
        "realm_gap": set(REALM_GAPS), "attitude": set(ATTITUDES), "event": set(EVENTS), "kind": set(KINDS),
        "bond": set(RELATIONS) | {"self"},
    }.get(key)


def scene_of(path: Path) -> str:
    return path.stem.split(".", 1)[0]


def files_for(scene: str) -> list[Path]:
    main = DIR / f"{scene}.json"
    return ([main] if main.exists() else []) + sorted(DIR.glob(f"{scene}.*.json"))


@lru_cache(maxsize=1)
def _load() -> dict[str, list[dict]]:
    out = {s: [] for s in SCENES}
    for path in sorted(DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("scene") in out:
            out[data["scene"]].extend(data.get("rules", []))
    return out


def reload() -> None:
    _load.cache_clear()


def rules_of(scene: str) -> list[dict]:
    return _load().get(scene, [])


# ---- 校验 -------------------------------------------------------------------

def validate_rules(rules, scene: str, label: str = "") -> list[str]:
    errors = []
    if not isinstance(rules, list) or not rules:
        return [f"{label}rules 应是非空列表"]
    allowed_vars = {"player", "bot"} | SCENES.get(scene, set())
    for i, rule in enumerate(rules):
        where = f"{label}rules[{i}]"
        if not isinstance(rule, dict):
            errors.append(f"{where}: 应是对象")
            continue
        when = rule.get("when", {})
        if not isinstance(when, dict):
            errors.append(f"{where}: when 应是对象")
            when = {}
        for key, values in when.items():
            if key not in WHEN_KEYS:
                errors.append(f"{where}: 未知条件 {key!r}")
                continue
            valid = valid_values(key)
            if not isinstance(values, list) or not values:
                errors.append(f"{where}: when.{key} 应是非空列表")
            elif valid is not None and not set(values) <= valid:
                errors.append(f"{where}: when.{key} 有未知的值 {sorted(set(values) - valid)}")
        w = rule.get("weight", 1)
        if not isinstance(w, (int, float)) or not 0 < w <= 20:
            errors.append(f"{where}: weight 应在 (0, 20]")
        lines = rule.get("lines")
        if not isinstance(lines, list) or not lines:
            errors.append(f"{where}: lines 应是非空列表")
            continue
        for t in lines:
            if not isinstance(t, str) or not t.strip():
                errors.append(f"{where}: 有空台词")
                continue
            if len(t) > MAX_LINE_LEN:
                errors.append(f"{where}: 台词超过 {MAX_LINE_LEN} 字：{t[:20]}…")
            try:
                used = {f for _, f, _, _ in string.Formatter().parse(t) if f is not None}
            except ValueError:
                errors.append(f"{where}: 花括号不成对：{t}")
                continue
            if used - allowed_vars:
                errors.append(f"{where}: 有不允许的占位符 {sorted(used - allowed_vars)}（{scene} 只允许 {sorted(allowed_vars)}）：{t}")
    return errors


def validate_file(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"{path.name}: 不是合法 JSON（{e}）"]
    scene = data.get("scene")
    if scene not in SCENES:
        return [f"{path.name}: 未知场景 {scene!r}"]
    errors = [] if scene_of(path) == scene else [f"{path.name}: 文件名应以场景名 {scene} 开头"]
    return errors + validate_rules(data.get("rules"), scene, f"{path.name}: ")


def validate_all() -> list[str]:
    errors = []
    for path in sorted(DIR.glob("*.json")):
        errors += validate_file(path)
    seen = set()
    for path in DIR.glob("*.json"):
        try:
            seen.add(json.loads(path.read_text(encoding="utf-8")).get("scene"))
        except Exception:
            pass
    for scene in SCENES:
        if scene not in seen:
            errors.append(f"缺少场景 {scene} 的文件")
        elif not any(not r.get("when") for r in rules_of(scene)):
            errors.append(f"{scene}: 至少要有一条没有条件的兜底规则")
    return errors


def coverage() -> dict[str, dict]:
    """{场景: {"rules": 规则数, "lines": 台词数, "archetypes": 有专属规则的性格数, "fallback": 兜底规则数}}。"""
    out = {}
    for scene in SCENES:
        rules = rules_of(scene)
        arche = {a for r in rules for a in r.get("when", {}).get("archetype", [])}
        out[scene] = {"rules": len(rules), "lines": sum(len(r["lines"]) for r in rules), "archetypes": len(arche),
                      "fallback": sum(1 for r in rules if not r.get("when"))}
    return out


# ---- 挑选 -------------------------------------------------------------------

def matches(when: dict, ctx: dict) -> bool:
    for key, values in when.items():
        have = ctx.get(key)
        if key == "tags":
            if not set(values) & set(have or []):
                return False
        elif have not in values:
            return False
    return True


def pick(scene: str, ctx: dict, rng: random.Random | None = None) -> str | None:
    """按条件挑一句台词模板（占位符还没填）。越具体的规则权重越大（×2 每多一个条件）；没有任何规则匹配返回 None。"""
    rng = rng or random.Random()
    pool = [r for r in rules_of(scene) if matches(r.get("when", {}), ctx)]
    if not pool:
        return None
    rule = rng.choices(pool, weights=[r.get("weight", 1) * 2 ** len(r.get("when", {})) for r in pool])[0]
    return rng.choice(rule["lines"])


def tags_of(kindness: int, profile: dict | None) -> list[str]:
    return bot_profile.tags(kindness, profile)
