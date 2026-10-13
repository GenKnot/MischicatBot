"""机器人台词的写作工具：让任何 AI 都能接着扩写（命令行入口：scripts/dialogue_tool.py）。

三件事：
· **看缺口**（`coverage_report` / `gaps`）：每个性格原型 × 场景 × 好感档位各有几句，哪些格子还没写够；
· **出提示词**（`build_prompt`）：把世界观、该原型的角色卡（data/bot_voices.json）、场景与档位的含义、占位符与约束、
  **已经写过的台词**（让新台词不重复、保持同一个声音）、要求的 JSON 输出格式，拼成一段可以直接粘贴给任意 AI 的文字；
· **收稿合并**（`merge_lines`）：AI 返回的 JSON 先校验（格式、场景 / 档位、占位符、长度），通过了才写入，
  已有的句子自动去重；可以写到主文件，也可以写到独立的『批次文件』`<原型>.<批次名>.json`（不同 AI 互不覆盖，查找时自动合并）。

校验不过一律不写文件。台词只是『说话』：给不给东西、好感涨多少由代码判定，提示词里也这么要求 AI。
"""

import json
import tempfile
from pathlib import Path

from utils import bot_dialogue as bd

VOICES = bd.DIR.parent / "bot_voices.json"
DEFAULT_TARGET = 4              # 每个格子至少有几句才算『写够了』
REQUIRED_CARD_FIELDS = ("summary", "voice", "habits", "values", "toward_player", "avoid", "examples")


def load_voices() -> dict:
    return json.loads(VOICES.read_text(encoding="utf-8"))


def archetype_names() -> list[str]:
    from utils.bot_social import load_archetypes
    return list(load_archetypes())


def validate_voices(data: dict) -> list[str]:
    """角色卡数据校验：场景 / 档位 / 原型要和代码里的清单一致，每张卡的字段齐全。"""
    errors = []
    if not data.get("world"):
        errors.append("缺少 world（世界观简介）")
    if set(data.get("scenes", {})) != set(bd.SCENES):
        errors.append(f"scenes 应与 bot_dialogue.SCENES 一致，差异：{set(data.get('scenes', {})) ^ set(bd.SCENES)}")
    for scene, info in data.get("scenes", {}).items():
        if not info.get("when") or not info.get("beat"):
            errors.append(f"scenes.{scene} 需要 when 和 beat")
    if set(data.get("tiers", {})) != set(bd.TIERS):
        errors.append("tiers 应与 bot_dialogue.TIERS 一致")
    if set(data.get("archetypes", {})) != set(archetype_names()):
        errors.append("archetypes 应与 data/bot_archetypes.json 的性格原型一致（新增原型要补角色卡）")
    for name, card in data.get("archetypes", {}).items():
        for field in REQUIRED_CARD_FIELDS:
            if not card.get(field):
                errors.append(f"archetypes.{name} 缺少 {field}")
        if set(card.get("toward_player", {})) != set(bd.TIERS):
            errors.append(f"archetypes.{name}.toward_player 应覆盖四个好感档位")
        for ex in card.get("examples", []):
            if len(ex) > bd.MAX_LINE_LEN:
                errors.append(f"archetypes.{name}.examples 有超长的示例")
    return errors


# ---- 缺口 -------------------------------------------------------------------

def gaps(archetype: str, target: int = DEFAULT_TARGET) -> list[tuple[str, str, int]]:
    """还没写够 `target` 句的格子 [(场景, 档位, 现有句数)]，按场景 / 档位顺序。"""
    cov = bd.coverage(archetype)
    return [(s, t, cov[s][t]) for s in bd.SCENES for t in bd.TIERS if cov[s][t] < target]


def coverage_report(archetypes: list[str] | None = None, target: int = DEFAULT_TARGET) -> str:
    """每个原型一行：写够的格子数 / 总格子数、句子总数，以及缺口最多的场景。"""
    names = archetypes or archetype_names()
    total_cells = len(bd.SCENES) * len(bd.TIERS)
    rows = ["| 原型 | 写够的格子 | 句子总数 | 缺口最多的场景 |", "|---|---|---|---|"]
    for name in names:
        g = gaps(name, target)
        lines = sum(sum(c.values()) for c in bd.coverage(name).values())
        per_scene = {}
        for s, _t, _n in g:
            per_scene[s] = per_scene.get(s, 0) + 1
        worst = "、".join(s for s, _ in sorted(per_scene.items(), key=lambda kv: -kv[1])[:3]) or "—"
        rows.append(f"| {name} | {total_cells - len(g)}/{total_cells} | {lines} | {worst} |")
    return "\n".join(rows)


# ---- 提示词 -----------------------------------------------------------------

def build_prompt(archetype: str, scenes: list[str] | None = None, tiers: list[str] | None = None,
                 n: int = DEFAULT_TARGET, target: int = DEFAULT_TARGET) -> str:
    """给『性格原型 archetype』扩写台词的完整提示词。
    `scenes` / `tiers` 不给就取缺口里涉及的场景 / 档位；`n` 是每个格子要写几句新的。"""
    voices = load_voices()
    if archetype not in voices["archetypes"]:
        raise ValueError(f"没有这个性格原型的角色卡：{archetype}")
    card = voices["archetypes"][archetype]
    if scenes is None:
        scenes = sorted({s for s, _t, _n in gaps(archetype, target)}, key=bd.SCENES.index)
    if tiers is None:
        tiers = [t for t in bd.TIERS if any(g[1] == t for g in gaps(archetype, target))] or list(bd.TIERS)
    unknown = [s for s in scenes if s not in bd.SCENES] + [t for t in tiers if t not in bd.TIERS]
    if unknown:
        raise ValueError(f"未知的场景 / 档位：{unknown}")
    existing = bd._load(archetype)
    out = [
        f"# 任务：为性格「{archetype}」扩写 NPC 台词",
        "",
        f"## 世界观\n{voices['world']}",
        "",
        f"## 角色卡 · {archetype}",
        f"- 定位：{card['summary']}",
        f"- 说话方式：{'；'.join(card['voice'])}",
        f"- 口头禅 / 习惯：{'；'.join(card['habits'])}",
        f"- 价值观：{card['values']}",
        f"- 要避免：{'；'.join(card['avoid'])}",
        "- 示例（只用来感受声音，不要照抄）：" + " / ".join(f"「{e}」" for e in card["examples"]),
        "",
        "## 对玩家的态度（随好感档位变化，同一个人在不同档位语气要明显不同）",
    ]
    for t in tiers:
        out.append(f"- **{t}**（{voices['tiers'][t]}）：{card['toward_player'][t]}")
    out += ["", "## 要写的场景"]
    for s in scenes:
        info = voices["scenes"][s]
        out.append(f"- `{s}`：{info['when']}。要点：{info['beat']}")
    out += [
        "",
        f"## 已经写过的台词（保持同一个声音，**不要重复**这些句子）",
    ]
    for s in scenes:
        for t in tiers:
            have = existing.get(s, {}).get(t, [])
            if have:
                out.append(f"- {s}/{t}：" + " ｜ ".join(have))
    out += [
        "",
        "## 规则（程序会校验，不合格整份退回）",
        f"1. 对上面每个场景 × 每个档位（{'、'.join(tiers)}）各写 **{n}** 句新台词，每句一行话，不超过 40 字（硬上限 {bd.MAX_LINE_LEN}）。",
        "2. 占位符只能用 `{player}`（玩家道号）、`{bot}`（NPC 自己的道号）、`{item}`（礼物名，只用于 gift_* 场景），不要出现别的花括号。"
        + "".join(f" `{s}` 场景另有：{'、'.join('`{%s}`' % v for v in sorted(bd.SCENE_VARS[s]))}。"
                  for s in scenes if s in bd.SCENE_VARS),
        "3. 台词只负责『说』：**不要许诺任何游戏结果**（送宝物、涨好感、给灵石）；给不给、涨多少由代码判定。",
        "4. 玩家被称呼时可用 `{player}`，但不必每句都用；不要写旁白、动作描写或括号里的说明。",
        "5. 调侃可以，别羞辱玩家；不要出现真实人名、政治、成人内容；死亡 / 杀戮相关场景不要渲染血腥，用克制的语气。",
        "6. 同一格子里的几句风格要有变化（长短、语气、关注点），别只换几个词。",
        "7. 想想这个人此刻为什么这么说：它的性格、跟玩家的交情、当时发生了什么。让台词体现『思路』，而不是套话。",
        "",
        "## 输出格式（只输出 JSON，不要任何解释）",
        "```json",
        json.dumps({"lines": {scenes[0] if scenes else "greet": {tiers[0] if tiers else "陌生": ["台词1", "台词2"]}}},
                   ensure_ascii=False, indent=2),
        "```",
        "场景名、档位名必须与上面完全一致；可以只返回你写了的格子。",
    ]
    return "\n".join(out)


# ---- 收稿合并 ---------------------------------------------------------------

def _normalize(raw) -> dict:
    """AI 的输出可以是 {"lines": {...}}，也可以直接是 {场景: {档位: [...]}}。"""
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError("顶层应是 JSON 对象")
    return raw.get("lines", raw) if isinstance(raw.get("lines", raw), dict) else raw


def merge_lines(archetype: str, new, batch: str | None = None, dry_run: bool = False) -> dict:
    """把 AI 写的台词校验后并进去。返回 {"ok", "added", "duplicates", "errors", "path"}。

    · 校验不过：`ok=False`，什么都不写；
    · 已有的（主文件和所有批次文件里）完全相同的句子算重复，跳过；
    · `batch=None` 写主文件 `<原型>.json`，否则写独立的批次文件 `<原型>.<batch>.json`（建议每个 AI / 每次一个批次名）。
    """
    names = set(archetype_names()) | {bd.DEFAULT}
    if archetype not in names:
        return {"ok": False, "added": 0, "duplicates": 0, "errors": [f"未知的性格原型：{archetype}"], "path": None}
    if batch is not None and (not batch or any(c in batch for c in "./\\") or batch == "json"):
        return {"ok": False, "added": 0, "duplicates": 0, "errors": [f"批次名不合法：{batch!r}（不能含 . / \\）"], "path": None}
    try:
        lines = _normalize(new)
    except Exception as e:
        return {"ok": False, "added": 0, "duplicates": 0, "errors": [f"不是合法的台词 JSON：{e}"], "path": None}

    target = bd.DIR / (f"{archetype}.{batch}.json" if batch else f"{archetype}.json")
    doc = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"archetype": archetype, "lines": {}}
    existing = bd._load(archetype)
    added = dup = 0
    for scene, cells in lines.items():
        if not isinstance(cells, dict):
            return {"ok": False, "added": 0, "duplicates": 0, "errors": [f"{scene}: 应是 {{档位: [台词]}}"], "path": None}
        for tier, texts in cells.items():
            for text in texts if isinstance(texts, list) else [texts]:
                if isinstance(text, str) and text.strip() in existing.get(scene, {}).get(tier, []):
                    dup += 1
                    continue
                bucket = doc["lines"].setdefault(scene, {}).setdefault(tier, [])
                bucket.append(text.strip() if isinstance(text, str) else text)
                added += 1

    with tempfile.TemporaryDirectory() as tmp:                 # 用同名的临时文件校验，通过了才写真文件
        probe = Path(tmp) / target.name
        probe.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        errors = bd.validate_file(probe, require_complete=(archetype == bd.DEFAULT))
    if errors:
        return {"ok": False, "added": 0, "duplicates": dup, "errors": errors, "path": None}

    # 按场景 / 档位的规定顺序落盘，diff 好看
    doc["lines"] = {s: {t: doc["lines"][s][t] for t in bd.TIERS if t in doc["lines"][s]}
                    for s in bd.SCENES if s in doc["lines"]}
    if added and not dry_run:
        target.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        bd.reload()
    return {"ok": True, "added": added, "duplicates": dup, "errors": [], "path": str(target)}


# ---- 条件化文案库（机器人主动搭话，utils/bot_chatter_lines.py）的扩写 --------------

def chatter_report() -> str:
    """文案库覆盖表：每个场景有多少条规则 / 台词、几个性格有专属规则、有没有兜底。"""
    from utils import bot_chatter_lines as cl
    rows = ["| 场景 | 规则 | 台词 | 有专属规则的性格 | 兜底规则 |", "|---|---|---|---|---|"]
    for scene, c in cl.coverage().items():
        rows.append(f"| {scene} | {c['rules']} | {c['lines']} | {c['archetypes']}/{len(archetype_names())} | {c['fallback']} |")
    return "\n".join(rows)


def chatter_prompt(scene: str, n: int = 8, archetypes: list[str] | None = None) -> str:
    """给『条件化文案库』某个场景扩写规则的提示词：场景说明、可用条件及合法取值、占位符、角色卡、已有台词（避免重复）、输出格式。"""
    from utils import bot_chatter_lines as cl
    if scene not in cl.SCENES:
        raise ValueError(f"未知场景：{scene}（可选：{'、'.join(cl.SCENES)}）")
    voices = load_voices()
    names = archetypes or archetype_names()
    when, beat = cl.SCENE_INFO[scene]
    allowed = ["{player}", "{bot}"] + sorted("{%s}" % v for v in cl.SCENES[scene])
    conds = []
    for key in sorted(cl.WHEN_KEYS):
        vals = cl.valid_values(key)
        conds.append(f"- `{key}`：{'、'.join(sorted(vals, key=str))}")
    out = [f"# 任务：为场景「{scene}」扩写 {n} 条新规则", "", f"## 世界观\n{voices['world']}", "",
           f"## 场景\n- 什么时候：{when}\n- 要做什么：{beat}\n- 台词是 NPC 对玩家说的一句话（Discord 消息里的一行），不是旁白。", "",
           "## 规则的结构",
           "每条规则 = `when`（适用条件，可省略 = 兜底）+ `weight`（可省略，默认 1）+ `lines`（1~3 句台词）。",
           "`when` 里每个键的值是列表：键之间是『且』，列表里是『或』。条件越多，这条规则越具体、被抽到的权重越大。",
           "要的是**有辨识度的组合**，例如『性格=阴鸷 且 好感=陌生 且 境界差=higher』，而不是把所有性格都写一遍。", "",
           "## 可用的条件和合法取值"] + conds + [
           "", "（`tier` 是好感档位；`relation` 是它和玩家的关系；`realm_gap` 是它的大境界相对玩家；`tags` 是阵营 / 行为标签，满足任意一个即可。）", "",
           f"## 占位符\n只能用：{'、'.join(allowed)}，不要出现别的花括号。", ""]
    out += ["## 要覆盖的性格角色卡（保持各自的声音）"]
    for a in names:
        card = voices["archetypes"][a]
        out.append(f"- **{a}**：{card['summary']} 口吻：{'；'.join(card['voice'])}。例：" + " / ".join(f"「{e}」" for e in card["examples"][:2]))
    existing = [t for r in cl.rules_of(scene) for t in r["lines"]]
    out += ["", f"## 已有的台词（共 {len(existing)} 句，不要重复这些）", "；".join(existing[:60]) + ("……" if len(existing) > 60 else ""), "",
            "## 规则（程序会校验，不合格整份退回）",
            f"1. 每句不超过 40 字（硬上限 {cl.MAX_LINE_LEN}），一句话，不要旁白 / 动作描写 / 括号说明。",
            "2. 台词只负责『说』：不要许诺任何游戏结果（给钱、涨好感、送东西）。",
            "3. 调侃可以，别羞辱玩家；不要真实人名、政治、成人内容；涉及打斗的不要渲染血腥。",
            "4. 同一条规则里的几句要有变化；不同规则之间风格拉开。", "",
            "## 输出格式（只输出 JSON）", "```json",
            json.dumps({"rules": [{"when": {"archetype": ["阴鸷"], "tier": ["陌生"]}, "weight": 1, "lines": ["台词1", "台词2"]}]}, ensure_ascii=False, indent=2),
            "```"]
    return "\n".join(out)


def chatter_merge(scene: str, new, batch: str | None = None, dry_run: bool = False) -> dict:
    """校验并合并 AI 写的规则。返回 {"ok", "added_rules", "added_lines", "duplicates", "errors", "path"}；校验不过什么都不写。
    台词已存在的跳过（整条规则的台词都重复就丢掉这条规则）；写到批次文件 <场景>.<批次>.json 自动合并。"""
    from utils import bot_chatter_lines as cl
    fail = lambda errs: {"ok": False, "added_rules": 0, "added_lines": 0, "duplicates": 0, "errors": errs, "path": None}      # noqa: E731
    if scene not in cl.SCENES:
        return fail([f"未知场景：{scene}"])
    if batch is not None and (not batch or any(c in batch for c in "./\\") or batch == "json"):
        return fail([f"批次名不合法：{batch!r}"])
    try:
        data = json.loads(new) if isinstance(new, str) else new
        rules = data.get("rules") if isinstance(data, dict) else data
    except Exception as e:
        return fail([f"不是合法的 JSON：{e}"])
    errors = cl.validate_rules(rules, scene)
    if errors:
        return fail(errors)
    have = {t for r in cl.rules_of(scene) for t in r["lines"]}
    fresh, dup = [], 0
    for r in rules:
        keep = [t.strip() for t in r["lines"] if t.strip() not in have]
        dup += len(r["lines"]) - len(keep)
        if keep:
            have.update(keep)
            fresh.append({**{k: v for k, v in r.items() if k != "lines"}, "lines": keep})
    target = cl.DIR / (f"{scene}.{batch}.json" if batch else f"{scene}.json")
    doc = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {"scene": scene, "rules": []}
    doc["rules"] = doc.get("rules", []) + fresh
    if fresh and not dry_run:
        target.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        cl.reload()
    return {"ok": True, "added_rules": len(fresh), "added_lines": sum(len(r["lines"]) for r in fresh), "duplicates": dup, "errors": [], "path": str(target)}


# ---- 特质池（出身 / 星座 / 习惯 / 口头禅 / 嗜好 / 往事）的扩写 ------------------

TRAIT_POOLS = ("origins", "habits", "zodiac", "hobbies", "pasts", "catchphrases")
RULE_DOC = """改写规则（rules 里每一项）可用这些键，全部可选；规则只改『占位符之外』的文字：
- swap: {"原词": "替换词"}，swap_p: 概率（默认 1）—— 称呼 / 词汇替换，最能体现出身和习惯（例：{"道友": "老哥"}）
- punct: {"！": "。"}，punct_p —— 标点替换（冷淡的人去掉感叹号，冲动的人把句号换成感叹号）
- end_particles: ["啦", "嘛"]（每个必须是一个字），end_p —— 在句末标点前加语气词
- prefix: ["说起来，"]，prefix_p —— 句首补话；suffix: ["你说是不是？"]，suffix_p —— 句尾补话（每条 ≤ 14 字，不含花括号）
- max_clauses: 1 —— 只留前几句（话少的人）；ellipsis_p —— 把第一个逗号换成省略号（话说一半）
- tiers: ["熟识", "至交"] —— 只在这些好感档位生效；scenes: ["greet"] —— 只在这些场景生效
一个条目可以有多条规则；不同条目的规则会叠加，所以每条规则要『轻』：概率别太高，别把整句话换掉。"""


def _pool_key(pool: str) -> str:
    from utils import bot_traits as bt
    return bt.POOLS.get(pool, pool)


def traits_prompt(pool: str, n: int = 8) -> str:
    """给『特质池 pool』扩写新条目的提示词（附带已有条目名、一个完整示例、规则说明、输出格式）。"""
    from utils import bot_traits as bt
    if pool not in TRAIT_POOLS:
        raise ValueError(f"未知的特质池：{pool}（可选：{'、'.join(TRAIT_POOLS)}）")
    voices = load_voices()
    arche = "、".join(archetype_names())
    head = [f"# 任务：为「{pool}」扩写 {n} 个新条目", "", f"## 世界观\n{voices['world']}", "",
            f"## 背景\n每个机器人出生时会从各个特质池里各抽一份，说话时按这些特质改写 NPC 的台词，让上百个 NPC 说话方式都不一样。"
            f"性格原型有：{arche}。"]
    if pool == "catchphrases":
        existing = bt.pool("catchphrases")
        out = head + [
            "", "## 要写的内容", f"口头禅：每个口头禅是一小段话，≤ {bt.MAX_PHRASE_LEN} 字，不含花括号。"
            "以『，』『——』『…』结尾的会放在句首（如『说实话，』），其余放在句尾（如『你说怪不怪。』）。",
            "池分『通用』和各性格原型；原型池里的口头禅要体现那个性格。", "",
            "## 已有的（不要重复）"] + [f"- {a}：{'、'.join(v)}" for a, v in existing.items()] + [
            "", f"## 输出格式（只输出 JSON）", "```json", json.dumps({"通用": ["新口头禅1，", "新口头禅2。"], "阴鸷": ["…"]}, ensure_ascii=False, indent=2), "```",
            f"一共约 {n} 条，可以分到不同的池里；键只能是『通用』或性格原型名。"]
        return "\n".join(out)
    entries = bt.pool(pool)
    key = next(iter(entries))
    example = {key: entries[key]}
    spec = {"origins": "出身：决定称呼 / 词汇 / 口吻，例如『渔村』『商贾』『宗门弃徒』。",
            "habits": "说话习惯：一种说话的『方式』，例如爱用语气词、文言腔、话说一半。每个机器人带 1~2 个。",
            "zodiac": "星座：只做文案倾向（不影响数值）。",
            "hobbies": "嗜好：偶尔被提到的一句话（remarks，≤40 字，不含花括号），没有 rules 也可以。",
            "pasts": "往事：一件定义性的经历，偶尔被提起（remarks，≤40 字，不含花括号）。"}[pool]
    out = head + ["", "## 要写的内容", spec,
                  "- `desc`：一句话说明；`weights`：{性格原型: 权重}，哪些性格更可能抽到（没写 = 1，0 = 不会抽到）。"]
    if pool not in ("hobbies", "pasts"):
        out += ["", "## 改写规则", RULE_DOC]
    out += ["", "## 已有条目（不要重复名字）", "、".join(entries), "", "## 一个完整示例",
            "```json", json.dumps(example, ensure_ascii=False, indent=2), "```", "",
            "## 输出格式（只输出 JSON：{条目名: 条目}）", "新条目名必须与已有的不同；风格尽量彼此拉开差距。"]
    return "\n".join(out)


def traits_merge(pool: str, new, batch: str | None = None, dry_run: bool = False) -> dict:
    """校验并合并 AI 写的特质条目。返回 {"ok", "added", "skipped", "errors", "path"}；校验不过什么都不写。
    已存在同名条目的跳过（改已有条目请直接编辑文件）；口头禅按池追加并去重。"""
    from utils import bot_traits as bt
    fail = lambda errs: {"ok": False, "added": 0, "skipped": 0, "errors": errs, "path": None}      # noqa: E731
    if pool not in TRAIT_POOLS:
        return fail([f"未知的特质池：{pool}"])
    if batch is not None and (not batch or any(c in batch for c in "./\\") or batch == "json"):
        return fail([f"批次名不合法：{batch!r}"])
    try:
        data = json.loads(new) if isinstance(new, str) else new
        if not isinstance(data, dict):
            raise ValueError("顶层应是 JSON 对象")
    except Exception as e:
        return fail([f"不是合法的 JSON：{e}"])
    if pool != "catchphrases":
        data = data.get(_pool_key(pool), data)
    key = _pool_key(pool)
    existing = bt.pool(pool)
    fresh, skipped = {}, 0
    for name, entry in data.items():
        if pool == "catchphrases":
            if not isinstance(entry, list):
                return fail([f"catchphrases.{name}: 应是列表"])
            items = [t for t in entry if t not in existing.get(name, [])]
            skipped += len(entry) - len(items)
            if items:
                fresh[name] = items
        elif name in existing:
            skipped += 1
        else:
            fresh[name] = entry
    target = bt.DIR / (f"{pool}.{batch}.json" if batch else f"{pool}.json")
    doc = json.loads(target.read_text(encoding="utf-8")) if target.exists() else ({} if pool == "catchphrases" else {key: {}})
    if pool == "catchphrases":
        for arche, items in fresh.items():
            doc.setdefault(arche, []).extend(items)
    else:
        doc.setdefault(key, {}).update(fresh)

    before = set(_trait_errors())
    with tempfile.TemporaryDirectory() as tmp:                 # 在一个临时副本里校验：目录换过去、缓存清掉、校验完再换回来
        for f in bt.DIR.glob("*.json"):
            (Path(tmp) / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        (Path(tmp) / target.name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        original = bt.DIR
        bt.DIR = Path(tmp)
        bt.reload()
        try:
            errors = [e for e in _trait_errors() if e not in before]
        finally:
            bt.DIR = original
            bt.reload()
    if errors:
        return fail(errors)
    count = sum(len(v) for v in fresh.values()) if pool == "catchphrases" else len(fresh)
    if count and not dry_run:
        target.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        bt.reload()
    return {"ok": True, "added": count, "skipped": skipped, "errors": [], "path": str(target)}


def _trait_errors() -> list[str]:
    from utils import bot_traits as bt
    return bt.validate_pools()


def sample_lines(archetype: str, scene: str, tier: str, n: int = 12, seed: int = 1) -> list[str]:
    """抽 n 个『该原型、该场景、该档位』的机器人，看他们各自会怎么说（检验多样性用）。"""
    import random
    from utils import bot_traits as bt
    from utils import bot_voice as bv
    from utils.bot_social import load_archetypes
    lo, hi = load_archetypes()[archetype]["talk"]
    out = []
    for i in range(n):
        rng = random.Random(f"{seed}:{i}")
        traits = bt.roll_traits(archetype, rng.randint(lo, hi), rng)
        template = bd.pick_template(archetype, scene, tier, rng)
        out.append(f"[{bt.describe(traits)}] " + bd.fill(bv.style(template, traits, scene, tier, rng), player="玩家", bot="我", item="某物"))
    return out
