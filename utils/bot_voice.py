"""把『骨架台词』按机器人的特质改写成它自己的口吻（U1·让每个机器人说话都不一样）。

骨架台词来自 utils/bot_dialogue（场景 × 档位 × 性格原型）。这里再按特质（utils/bot_traits）逐层改写：

  1. **长短**：所有生效规则里最小的 `max_clauses` 先截一次（内向的人只说第一句）；
  2. **规则**（内向外向 → 出身 → 说话习惯 → 星座）依次：词语替换（称呼 / 词汇）→ 标点 → 省略号 → 句末语气词 → 句首 / 句尾补话；
  3. **口头禅**：按内向外向决定带不带，带在句首还是句尾；
  4. **插话**：偶尔提一句嗜好或往事（熟识以上才会，仇视档从不）。

规则全是数据（见 data/bot_traits/*.json），改写只作用在占位符之外的文字，`{player}` `{bot}` `{item}` 原样保留。
改写后太长、或者变空，就退回骨架台词——改写永远不能把一句话弄坏。**纯文案，不影响任何数值。**
"""

import random
import re

from utils import bot_traits as bt

PLACEHOLDER = re.compile(r"(\{[^{}]*\})")
SENTENCE_END = "。！？"
PARTICLES = set("啦嘛呢哟喽吧啊呀哩嘞")
PREFIX_ENDINGS = ("，", "——", "…", "、")           # 以这些结尾的口头禅放句首，其余放句尾
MAX_STYLED_LEN = 100
REMARK_SCENES = {"greet", "chat_again", "gift_neutral", "gift_like", "gift_love", "gift_limit",
                 "party_accept", "party_refuse", "dual_refuse"}
REMARK_TIER_FACTOR = {"仇视": 0.0, "陌生": 0.4, "熟识": 1.0, "至交": 1.3}


def _on_text(text: str, fn) -> str:
    """只对占位符之外的文字做替换。"""
    return "".join(part if PLACEHOLDER.fullmatch(part) else fn(part) for part in PLACEHOLDER.split(text))


def _sentences(text: str) -> list[str]:
    return re.findall(r"[^。！？]+[。！？]?", text)


def _truncate(text: str, n: int) -> str:
    parts = _sentences(text)
    return "".join(parts[:n]) if len(parts) > n else text


def _apply(text: str, rule: dict, rng: random.Random) -> str:
    """一条规则（max_clauses 已经在外面统一处理过）。顺序固定：替换 → 标点 → 省略号 → 语气词 → 前缀 → 后缀。"""
    if "swap" in rule and rng.random() < rule.get("swap_p", 1.0):
        for a in sorted(rule["swap"], key=len, reverse=True):
            text = _on_text(text, lambda s, a=a: s.replace(a, rule["swap"][a]))
    if "punct" in rule and rng.random() < rule.get("punct_p", 1.0):
        for a, b in rule["punct"].items():
            text = _on_text(text, lambda s, a=a, b=b: s.replace(a, b))
    if rule.get("ellipsis_p") and rng.random() < rule["ellipsis_p"] and "，" in text:
        text = _on_text(text, lambda s: s.replace("，", "……", 1))
    if "end_particles" in rule and rng.random() < rule.get("end_p", 0.0):
        m = re.search(r"([。！？]?)$", text)
        body = text[:m.start()]
        if body and body[-1] not in PARTICLES and not PLACEHOLDER.search(body[-3:] or ""):
            text = body + rng.choice(rule["end_particles"]) + m.group(1)
    if "prefix" in rule and rng.random() < rule.get("prefix_p", 0.0):
        pre = rng.choice(rule["prefix"])
        if not text.startswith(pre):
            text = pre + text
    if "suffix" in rule and rng.random() < rule.get("suffix_p", 0.0):
        suf = rng.choice(rule["suffix"])
        if suf not in text:
            text = text + suf
    return text


def active_rules(traits: dict, scene: str, tier: str) -> list[dict]:
    """这个机器人在此场景 / 档位下生效的全部规则，按『内向外向 → 出身 → 习惯 → 星座』排序。"""
    sources = [bt.pool("introversion").get(traits.get("introversion"), {}).get("rules", []),
               bt.pool("origins").get(traits.get("origin"), {}).get("rules", [])]
    sources += [bt.pool("habits").get(h, {}).get("rules", []) for h in traits.get("habits", [])]
    sources.append(bt.pool("zodiac").get(traits.get("zodiac"), {}).get("rules", []))
    return [r for src in sources for r in src
            if tier in r.get("tiers", [tier]) and scene in r.get("scenes", [scene])]


def style(template: str, traits: dict | None, scene: str, tier: str, rng: random.Random | None = None) -> str:
    """把骨架台词改写成这个机器人的口吻。没有特质、或改写后不合格，原样返回。"""
    if not traits or not template:
        return template
    rng = rng or random.Random()
    rules = active_rules(traits, scene, tier)
    text = template
    limits = [r["max_clauses"] for r in rules if "max_clauses" in r]
    if limits:
        text = _truncate(text, min(limits))
    for rule in rules:
        text = _apply(text, rule, rng)

    level = bt.pool("introversion").get(traits.get("introversion"), {})
    phrases = traits.get("catchphrases", [])
    if phrases and rng.random() < level.get("catch_p", 0.0):
        phrase = rng.choice(phrases)
        if phrase not in text:
            text = phrase + text if phrase.endswith(PREFIX_ENDINGS) else text + phrase

    if scene in REMARK_SCENES and rng.random() < level.get("remark_p", 0.0) * REMARK_TIER_FACTOR.get(tier, 0.0):
        hobby = bt.pool("hobbies").get(traits.get("hobby"), {}).get("remarks", [])
        past = bt.pool("pasts").get(traits.get("past"), {}).get("remarks", [])
        remarks = hobby + past
        if remarks:
            text = text + rng.choice(remarks)

    if not text.strip() or len(text) > MAX_STYLED_LEN:
        return template
    return text
