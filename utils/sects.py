from utils import rules
from utils.realms import get_realm_index
from utils.techniques import WORLD_TECHNIQUES

TECHNIQUE_STAGES = ["入门", "熟练", "精通", "小成", "大成", "圆满", "破限"]

# 各阶段的灵石 / 年数、品阶倍数、属性加成倍数在 data/game_rules.json 的 techniques（管理员可以调），用的时候读


def stat_multiplier(stage: str) -> float:
    """某阶段对属性加成（悟性、体魄……）的倍数。"""
    return rules.section("techniques")["stat_mult"].get(stage, 1)


def pct_multiplier(stage: str) -> float:
    """某阶段对百分比类加成（修炼速度、逃跑率、寿元）的倍数。"""
    return rules.section("techniques")["pct_mult"].get(stage, 1)


PCT_STATS = {"escape_rate", "cultivation_speed", "lifespan_bonus"}

TECHNIQUES = {
    "青云心法":   {"type": "修炼", "grade": "黄级上品", "stat_bonus": {"comprehension": 1, "cultivation_speed": 0.15}, "effect": {"cultivation_bonus": 0.15}, "desc": "青云宗镇宗心法，以悟性引导灵气，修炼速度与悟性同步提升。"},
    "御剑术":     {"type": "攻击", "grade": "黄级上品", "stat_bonus": {"comprehension": 1}, "effect": {"attack_scale": "comprehension"}, "desc": "以意驭剑，悟性越高剑意越锋，青云宗弟子人手必修。"},
    "凌云步":     {"type": "辅助", "grade": "黄级上品", "stat_bonus": {"escape_rate": 10}, "effect": {"escape_bonus": 0.3}, "desc": "踏云而行的轻功，身形飘逸难以捉摸，逃跑成功率显著提升。"},

    "天玄真经":   {"type": "修炼", "grade": "黄级上品", "stat_bonus": {"cultivation_speed": 0.10}, "effect": {"cultivation_bonus": 0.10}, "desc": "天玄门传承心法，无灵根限制，稳步提升修炼速度。"},
    "玄门护体":   {"type": "防御", "grade": "黄级上品", "stat_bonus": {"physique": 1}, "effect": {"defense_scale": "physique"}, "desc": "以体魄为盾，天玄门弟子的基础防御功法，体魄小幅强化。"},
    "天玄剑诀":   {"type": "攻击", "grade": "黄级上品", "stat_bonus": {"comprehension": 1}, "effect": {"attack_scale": "comprehension", "multiplier": 0.8}, "desc": "天玄门剑法入门，以悟性驱动剑势，攻击稳健。"},

    "百草心经":   {"type": "修炼", "grade": "黄级上品", "stat_bonus": {"soul": 1, "cultivation_speed": 0.10}, "effect": {"cultivation_bonus": 0.10, "herb_bonus": 2.0}, "desc": "灵药宗传承，以神识感应草木灵气，修炼速度与神识同步提升。"},
    "木灵诀":     {"type": "辅助", "grade": "黄级上品", "stat_bonus": {"lifespan_bonus": 5}, "effect": {"lifespan_restore": 5}, "desc": "以木属灵气滋养肉身，延缓衰老，寿元上限小幅提升。"},
    "丹火术":     {"type": "攻击", "grade": "黄级上品", "stat_bonus": {"soul": 1}, "effect": {"attack_scale": "soul", "dot": True}, "desc": "以神识控制丹火灼烧对手，神识越强火焰越炽。"},

    "御剑心法":   {"type": "修炼", "grade": "黄级上品", "stat_bonus": {"comprehension": 2}, "effect": {"cultivation_bonus_scale": "comprehension"}, "desc": "御剑阁核心心法，悟性越高修炼效率越强，天才专属。"},
    "万剑归宗":   {"type": "攻击", "grade": "黄级上品", "stat_bonus": {"comprehension": 2}, "effect": {"attack_scale": "comprehension", "multiplier": 2.0}, "desc": "御剑阁绝学，万剑齐发归于一点，悟性大幅强化，威力惊人。"},
    "剑盾":       {"type": "防御", "grade": "黄级上品", "stat_bonus": {"comprehension": 1}, "effect": {"defense_scale": "comprehension"}, "desc": "以剑意凝聚护盾，悟性越高防御越强。"},

    "玄冰心法":   {"type": "修炼", "grade": "黄级上品", "stat_bonus": {"physique": 1, "cultivation_speed": 0.20}, "effect": {"cultivation_bonus": 0.20, "element_restrict": ["水", "冰"]}, "desc": "玄冰派镇派心法，冰属灵根修炼效率极高，体魄与修炼速度同步提升。"},
    "寒冰掌":     {"type": "攻击", "grade": "黄级上品", "stat_bonus": {"physique": 2}, "effect": {"attack_scale": "physique", "freeze": True}, "desc": "以寒冰之力凝固对手，体魄大幅强化，攻击附带冰冻效果。"},
    "冰甲术":     {"type": "防御", "grade": "黄级上品", "stat_bonus": {"physique": 2}, "effect": {"defense_scale": "physique", "cost": "high"}, "desc": "以冰气包裹全身形成冰甲，防御极强但消耗灵力较高。"},

    "血煞功":     {"type": "修炼", "grade": "黄级上品", "stat_bonus": {"physique": 2}, "effect": {"cultivation_bonus_scale": "physique", "kill_bonus": True}, "desc": "血煞门镇宗功法，以杀戮之气淬炼体魄，每次战斗胜利后修炼效率提升。"},
    "血煞刀法":   {"type": "攻击", "grade": "黄级上品", "stat_bonus": {"physique": 2}, "effect": {"attack_scale": "physique", "multiplier": 1.8}, "desc": "嗜血的刀法，体魄越强刀势越猛，血煞门弟子的看家本领。"},
    "铁布衫":     {"type": "防御", "grade": "黄级上品", "stat_bonus": {"physique": 3}, "effect": {"defense_scale": "physique", "no_spirit": True}, "desc": "以肉身硬抗一切，不借助灵力的纯粹体魄防御，体魄大幅强化。"},

    "幽冥心法":   {"type": "修炼", "grade": "黄级上品", "stat_bonus": {"soul": 2, "cultivation_speed": 0.15}, "effect": {"cultivation_bonus": 0.15, "night_bonus": 2.0}, "desc": "鬼修宗传承，以阴冥之气修炼，神识与修炼速度同步提升。"},
    "鬼影步":     {"type": "辅助", "grade": "黄级上品", "stat_bonus": {"escape_rate": 15}, "effect": {"stealth_bonus": 0.4}, "desc": "如鬼魂般游走的步法，难以被感知，逃跑成功率大幅提升。"},
    "摄魂术":     {"type": "攻击", "grade": "黄级上品", "stat_bonus": {"soul": 2}, "effect": {"attack_scale": "soul", "ignore_defense": True}, "desc": "直接攻击对手神识，无视肉身防御，神识大幅强化。"},

    "魔焰心法":   {"type": "修炼", "grade": "黄级上品", "stat_bonus": {"physique": 1, "cultivation_speed": 0.25}, "effect": {"cultivation_bonus": 0.25, "element_restrict": ["火"], "lifespan_cost": 1}, "desc": "魔焰教禁忌功法，修炼速度极快但每次闭关额外消耗寿元，体魄提升。"},
    "魔焰掌":     {"type": "攻击", "grade": "黄级上品", "stat_bonus": {"physique": 3}, "effect": {"attack_scale": "physique", "multiplier": 2.2, "self_damage": True}, "desc": "以自身精血催动魔焰，威力惊人但会反噬自身，体魄大幅强化。"},
    "火云护体":   {"type": "防御", "grade": "黄级上品", "stat_bonus": {"physique": 2}, "effect": {"defense_scale": "physique", "reflect": True}, "desc": "以火云包裹全身，可将部分伤害反弹给攻击者，体魄强化。"},

    "合欢心法":   {"type": "修炼", "grade": "黄级上品", "stat_bonus": {"fortune": 1, "cultivation_speed": 0.05}, "effect": {"cultivation_bonus": 0.05, "dual_bonus": True}, "desc": "合欢宗入门心法，双修时效果翻倍，机缘与修炼速度小幅提升。"},
    "双修功法":   {"type": "特殊", "grade": "黄级上品", "stat_bonus": {"fortune": 2}, "effect": {"dual_cultivate": True, "cooldown_years": 2}, "desc": "合欢宗绝学，与他人双修可大幅获得修为，机缘大幅提升，冷却2年。"},
    "媚术":       {"type": "辅助", "grade": "黄级上品", "stat_bonus": {"fortune": 2}, "effect": {"debuff_scale": "fortune"}, "desc": "以机缘之力迷惑对手，机缘越高效果越强，令敌人判断失误。"},

    "噬魂心法":   {"type": "修炼", "grade": "黄级上品", "stat_bonus": {"soul": 3}, "effect": {"cultivation_bonus_scale": "soul"}, "desc": "噬魂阁镇宗功法，以神识吞噬天地灵气，神识越强修炼效率越高。"},
    "神识冲击":   {"type": "攻击", "grade": "黄级上品", "stat_bonus": {"soul": 2}, "effect": {"attack_scale": "soul", "ignore_defense": True, "multiplier": 2.0}, "desc": "以强大神识直接冲击对手意识，无视防御，神识大幅强化。"},
    "神识壁垒":   {"type": "防御", "grade": "黄级上品", "stat_bonus": {"soul": 2}, "effect": {"defense_scale": "soul", "anti_mental": True}, "desc": "以神识构筑防御壁垒，专门克制神识类攻击，神识大幅强化。"},

    "太虚真经":   {"type": "修炼", "grade": "玄级上品", "stat_bonus": {"comprehension": 3, "cultivation_speed": 0.50}, "effect": {"cultivation_bonus": 0.50, "single_root_only": True, "realm_scale": True}, "desc": "太虚阁镇阁之宝，单灵根专属，修炼速度冠绝天下，悟性大幅提升。"},
    "太虚剑意":   {"type": "攻击", "grade": "玄级上品", "stat_bonus": {"comprehension": 4}, "effect": {"attack_scale": "comprehension", "multiplier": 3.0}, "desc": "太虚阁绝学，以纯粹剑意斩断一切，悟性极大强化，威力恐怖。"},
    "虚空遁形":   {"type": "辅助", "grade": "玄级上品", "stat_bonus": {"escape_rate": 30}, "effect": {"invincible": True, "cost": "extreme"}, "desc": "融入虚空的极致身法，逃跑成功率极高，几乎无法被追踪。"},

    "混沌心法":   {"type": "修炼", "grade": "地级下品", "stat_bonus": {"comprehension": 2, "physique": 2, "cultivation_speed": 0.60}, "effect": {"cultivation_bonus": 0.60, "variant_only": True, "dual_element": True}, "desc": "混沌宗传承，变异灵根专属，融合多种属性之力，修炼速度极高。"},
    "混沌气团":   {"type": "攻击", "grade": "地级下品", "stat_bonus": {"comprehension": 3, "physique": 3}, "effect": {"multi_element": True, "ignore_single_defense": True}, "desc": "以混沌之力凝聚气团，多属性融合攻击，无视单一属性防御。"},
    "混沌护体":   {"type": "防御", "grade": "地级下品", "stat_bonus": {"physique": 4}, "effect": {"random_element_shield": True}, "desc": "以混沌之气护体，随机生成不同属性护盾，体魄极大强化。"},

    "天机心法":   {"type": "修炼", "grade": "玄级中品", "stat_bonus": {"fortune": 3, "cultivation_speed": 0.30}, "effect": {"cultivation_bonus_scale": "fortune", "enlighten_chance": True}, "desc": "天机门传承，以机缘感应天道，机缘越高修炼效率越强，偶有顿悟。"},
    "天机预演":   {"type": "辅助", "grade": "玄级中品", "stat_bonus": {"fortune": 3, "escape_rate": 20}, "effect": {"dodge_bonus_scale": "fortune"}, "desc": "预演天机推算危险，机缘大幅提升，逃跑成功率显著提升。"},
    "因果斩":     {"type": "攻击", "grade": "玄级中品", "stat_bonus": {"soul": 3, "comprehension": 2}, "effect": {"ignore_realm": True, "lifespan_cost": 10}, "desc": "斩断因果的禁忌刀法，可无视境界差距攻击，但每次使用消耗寿元。"},

    "无极心法":   {"type": "修炼", "grade": "玄级下品", "stat_bonus": {"comprehension": 1, "physique": 1, "fortune": 1, "bone": 1, "soul": 1, "cultivation_speed": 0.40}, "effect": {"cultivation_bonus": 0.40, "all_stat_bonus": True}, "desc": "无极道传承，五维属性全面提升，无任何限制，修炼速度大幅提升。"},
    "无极拳":     {"type": "攻击", "grade": "玄级下品", "stat_bonus": {"physique": 2, "bone": 2}, "effect": {"attack_scale": "all_stats"}, "desc": "以无极之力驱动拳意，体魄与根骨大幅强化，攻击融合全属性。"},
    "无极护体":   {"type": "防御", "grade": "玄级下品", "stat_bonus": {"physique": 2, "soul": 2}, "effect": {"defense_scale": "all_stats"}, "desc": "以无极之气护体，体魄与神识大幅强化，防御融合全属性。"},

    "轮回心法":   {"type": "修炼", "grade": "玄级上品", "stat_bonus": {"bone": 3, "cultivation_speed": 0.20}, "effect": {"cultivation_bonus_per_death": 0.20}, "desc": "仙葬谷传承，每次坐化重生后修炼效率递增，根骨大幅强化。"},
    "死亡凝视":   {"type": "攻击", "grade": "玄级上品", "stat_bonus": {"soul": 3}, "effect": {"ignore_defense_chance": 0.3, "attack_scale": "soul"}, "desc": "以死亡之眼凝视对手，有概率无视全部防御，神识极大强化。"},
    "不死之身":   {"type": "防御", "grade": "玄级上品", "stat_bonus": {"bone": 3, "physique": 2}, "effect": {"revive_chance": 0.3, "once_per_realm": True}, "desc": "仙葬谷绝学，每个境界有一次死而复生的机会，根骨与体魄极大强化。"},
}


TECHNIQUES = {**TECHNIQUES, **WORLD_TECHNIQUES}


def get_technique_cost(name: str, current_stage: str) -> tuple[int, int]:
    info = TECHNIQUES.get(name, {})
    grade = info.get("grade", "黄级上品")
    t = rules.section("techniques")
    mult = t["grade_cost"].get(grade, 1.0)
    stones = int(t["stage_cost"].get(current_stage, 500) * mult)
    years = t["stage_years"].get(current_stage, 1)
    return stones, years


def next_stage(stage: str) -> str | None:
    idx = TECHNIQUE_STAGES.index(stage) if stage in TECHNIQUE_STAGES else -1
    if idx < 0 or idx >= len(TECHNIQUE_STAGES) - 1:
        return None
    return TECHNIQUE_STAGES[idx + 1]


def calc_technique_stat_bonus(techniques_json: list) -> dict:
    total = {}
    for t in techniques_json:
        if isinstance(t, str):
            t = {"name": t, "stage": "入门", "equipped": True}
        if not t.get("equipped"):
            continue
        name = t.get("name", "")
        stage = t.get("stage", "入门")
        info = TECHNIQUES.get(name, {})
        base_bonus = info.get("stat_bonus", {})
        for stat, val in base_bonus.items():
            mult = pct_multiplier(stage) if stat in PCT_STATS else stat_multiplier(stage)
            total[stat] = total.get(stat, 0) + val * mult
    return total


def _req(min_realm=None, spirit_roots=None, min_stat=None, min_fortune=None,
         single_root=False, variant_root=False, hidden=False, needs_adventure=False,
         rebirth_only=False):
    return {
        "min_realm": min_realm,
        "spirit_roots": spirit_roots,
        "min_stat": min_stat,
        "min_fortune": min_fortune,
        "single_root": single_root,
        "variant_root": variant_root,
        "hidden": hidden,
        "needs_adventure": needs_adventure,
        "rebirth_only": rebirth_only,
    }


SECTS = {
    "青云宗": {
        "alignment": "正道",
        "location": "御剑城",
        "desc": "剑修圣地，灵根越纯阶位越高，以御剑术闻名天下。",
        "techniques": ["青云心法", "御剑术", "凌云步"],
        "req": _req(min_realm="炼气期5层", spirit_roots=["单灵根", "双灵根"], min_stat={"comprehension": 7}),
    },
    "天玄门": {
        "alignment": "正道",
        "location": "天京城",
        "desc": "中州第一大正道宗门，无灵根限制，晋升全靠实力。",
        "techniques": ["天玄真经", "玄门护体", "天玄剑诀"],
        "req": _req(min_realm="筑基期1层"),
    },
    "灵药宗": {
        "alignment": "正道",
        "location": "丹霞谷",
        "desc": "丹修圣地，百草谷与翠微城是其药材产地。",
        "techniques": ["百草心经", "木灵诀", "丹火术"],
        "req": _req(min_realm="炼气期3层", spirit_roots=["木", "火"], min_stat={"soul": 6}),
    },
    "御剑阁": {
        "alignment": "正道",
        "location": "凌霄城",
        "desc": "只看天赋不看境界，悟性不够免谈。",
        "techniques": ["御剑心法", "万剑归宗", "剑盾"],
        "req": _req(min_stat={"comprehension": 8}),
    },
    "玄冰派": {
        "alignment": "正道",
        "location": "寒冰城",
        "desc": "冰属专精，玄冰谷是其核心修炼地。",
        "techniques": ["玄冰心法", "寒冰掌", "冰甲术"],
        "req": _req(min_realm="炼气期3层", spirit_roots=["单灵根·水", "冰", "水"], min_stat={"physique": 6}),
    },
    "血煞门": {
        "alignment": "邪道",
        "location": "铁甲城",
        "desc": "以战养修，入门即要参加擂台生死战。",
        "techniques": ["血煞功", "血煞刀法", "铁布衫"],
        "req": _req(min_realm="炼气期5层", min_stat={"physique": 8}),
    },
    "鬼修宗": {
        "alignment": "邪道",
        "location": "幽冥镇",
        "desc": "阴修一脉，幽冥海是其秘密修炼地。",
        "techniques": ["幽冥心法", "鬼影步", "摄魂术"],
        "req": _req(min_realm="炼气期3层", min_stat={"soul": 7}),
    },
    "魔焰教": {
        "alignment": "邪道",
        "location": "赤炎城",
        "desc": "火属邪修，火云洞是其核心修炼场。",
        "techniques": ["魔焰心法", "魔焰掌", "火云护体"],
        "req": _req(min_realm="炼气期3层", spirit_roots=["火"]),
    },
    "合欢宗": {
        "alignment": "邪道",
        "location": "望月楼",
        "desc": "男女皆收，双修功法天下无双，但战斗功法匮乏。",
        "techniques": ["合欢心法", "双修功法", "媚术"],
        "req": _req(min_realm="炼气期1层", min_fortune=7),
    },
    "噬魂阁": {
        "alignment": "邪道",
        "location": "幽冥海",
        "desc": "神识修炼为主，可吞噬他人神识获得修为。",
        "techniques": ["噬魂心法", "神识冲击", "神识壁垒"],
        "req": _req(min_realm="筑基期1层", min_stat={"soul": 8}),
    },
    "太虚阁": {
        "alignment": "隐世",
        "location": "太虚城地脉之下",
        "desc": "只收单灵根天才，修炼效率冠绝天下。",
        "techniques": ["太虚真经", "太虚剑意", "虚空遁形"],
        "req": _req(min_realm="结丹期初期", single_root=True, hidden=True, needs_adventure=True),
    },
    "混沌宗": {
        "alignment": "隐世",
        "location": "虚空裂缝深处",
        "desc": "变异灵根者的归宿，混沌功法融合多种属性之力。",
        "techniques": ["混沌心法", "混沌气团", "混沌护体"],
        "req": _req(min_realm="元婴期初期", variant_root=True, hidden=True, needs_adventure=True),
    },
    "天机门": {
        "alignment": "隐世",
        "location": "望月楼隐藏入口",
        "desc": "机缘足够才能发现入口，天机心法上限无穷。",
        "techniques": ["天机心法", "天机预演", "因果斩"],
        "req": _req(min_fortune=10, hidden=True, needs_adventure=True),
    },
    "无极道": {
        "alignment": "隐世",
        "location": "古战场遗迹",
        "desc": "无任何属性要求，但考核是在古战场独自生存。",
        "techniques": ["无极心法", "无极拳", "无极护体"],
        "req": _req(hidden=True, needs_adventure=True),
    },
    "仙葬谷": {
        "alignment": "隐世",
        "location": "昆仑秘境最深处",
        "desc": "只有坐化重生的修士才能感应到入口，越死越强。",
        "techniques": ["轮回心法", "死亡凝视", "不死之身"],
        "req": _req(hidden=True, needs_adventure=True, rebirth_only=True),
    },
}


def check_requirements(player: dict, sect_name: str) -> tuple[bool, str]:
    sect = SECTS.get(sect_name)
    if not sect:
        return False, "宗门不存在。"

    req = sect["req"]

    if req["rebirth_only"] and not player.get("rebirth_count", 0):
        return False, "此宗门只接纳曾经坐化重生之人。"

    if req["needs_adventure"]:
        import json
        discovered = json.loads(player.get("discovered_sects") or "[]")
        if sect_name not in discovered:
            return False, "此宗门入口隐秘，需通过特殊奇遇方可发现。"

    if req["min_realm"]:
        if get_realm_index(player["realm"]) < get_realm_index(req["min_realm"]):
            return False, f"境界不足，需达到 {req['min_realm']}。"

    if req["single_root"] and player["spirit_root_type"] != "单灵根":
        return False, "此宗门只收单灵根修士。"

    if req["variant_root"] and player["spirit_root_type"] != "变异灵根":
        return False, "此宗门只收变异灵根修士。"

    if req["spirit_roots"]:
        root = player["spirit_root"]
        if not any(r in root for r in req["spirit_roots"]):
            return False, f"灵根不符，需含有 {'或'.join(req['spirit_roots'])} 属性。"

    if req["min_stat"]:
        for stat, val in req["min_stat"].items():
            if player.get(stat, 0) < val:
                stat_names = {
                    "comprehension": "悟性", "physique": "体魄",
                    "fortune": "机缘", "bone": "根骨", "soul": "神识"
                }
                return False, f"{stat_names.get(stat, stat)} 不足，需达到 {val}。"

    if req["min_fortune"] and player.get("fortune", 0) < req["min_fortune"]:
        return False, f"机缘不足，需达到 {req['min_fortune']}。"

    return True, "符合入门要求。"
