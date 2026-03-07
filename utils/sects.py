from utils.realms import get_realm_index

TECHNIQUES = {
    "青云心法":   {"type": "修炼", "effect": {"cultivation_bonus": 0.15, "comprehension_bonus": 1}},
    "御剑术":     {"type": "攻击", "effect": {"attack_scale": "comprehension"}},
    "凌云步":     {"type": "辅助", "effect": {"escape_bonus": 0.3}},

    "天玄真经":   {"type": "修炼", "effect": {"cultivation_bonus": 0.10}},
    "玄门护体":   {"type": "防御", "effect": {"defense_scale": "physique"}},
    "天玄剑诀":   {"type": "攻击", "effect": {"attack_scale": "comprehension", "multiplier": 0.8}},

    "百草心经":   {"type": "修炼", "effect": {"cultivation_bonus": 0.10, "soul_bonus": 1, "herb_bonus": 2.0}},
    "木灵诀":     {"type": "辅助", "effect": {"lifespan_restore": 5}},
    "丹火术":     {"type": "攻击", "effect": {"attack_scale": "soul", "dot": True}},

    "御剑心法":   {"type": "修炼", "effect": {"cultivation_bonus_scale": "comprehension"}},
    "万剑归宗":   {"type": "攻击", "effect": {"attack_scale": "comprehension", "multiplier": 2.0}},
    "剑盾":       {"type": "防御", "effect": {"defense_scale": "comprehension"}},

    "玄冰心法":   {"type": "修炼", "effect": {"cultivation_bonus": 0.20, "element_restrict": ["水", "冰"]}},
    "寒冰掌":     {"type": "攻击", "effect": {"attack_scale": "physique", "freeze": True}},
    "冰甲术":     {"type": "防御", "effect": {"defense_scale": "physique", "cost": "high"}},

    "血煞功":     {"type": "修炼", "effect": {"cultivation_bonus_scale": "physique", "kill_bonus": True}},
    "血煞刀法":   {"type": "攻击", "effect": {"attack_scale": "physique", "multiplier": 1.8}},
    "铁布衫":     {"type": "防御", "effect": {"defense_scale": "physique", "no_spirit": True}},

    "幽冥心法":   {"type": "修炼", "effect": {"cultivation_bonus": 0.15, "soul_bonus": 1, "night_bonus": 2.0}},
    "鬼影步":     {"type": "辅助", "effect": {"stealth_bonus": 0.4}},
    "摄魂术":     {"type": "攻击", "effect": {"attack_scale": "soul", "ignore_defense": True}},

    "魔焰心法":   {"type": "修炼", "effect": {"cultivation_bonus": 0.25, "element_restrict": ["火"], "lifespan_cost": 1}},
    "魔焰掌":     {"type": "攻击", "effect": {"attack_scale": "physique", "multiplier": 2.2, "self_damage": True}},
    "火云护体":   {"type": "防御", "effect": {"defense_scale": "physique", "reflect": True}},

    "合欢心法":   {"type": "修炼", "effect": {"cultivation_bonus": 0.05, "dual_bonus": True}},
    "双修功法":   {"type": "特殊", "effect": {"dual_cultivate": True, "cooldown_years": 5}},
    "媚术":       {"type": "辅助", "effect": {"debuff_scale": "fortune"}},

    "噬魂心法":   {"type": "修炼", "effect": {"cultivation_bonus_scale": "soul"}},
    "神识冲击":   {"type": "攻击", "effect": {"attack_scale": "soul", "ignore_defense": True, "multiplier": 2.0}},
    "神识壁垒":   {"type": "防御", "effect": {"defense_scale": "soul", "anti_mental": True}},

    "太虚真经":   {"type": "修炼", "effect": {"cultivation_bonus": 0.50, "single_root_only": True, "realm_scale": True}},
    "太虚剑意":   {"type": "攻击", "effect": {"attack_scale": "comprehension", "multiplier": 3.0}},
    "虚空遁形":   {"type": "辅助", "effect": {"invincible": True, "cost": "extreme"}},

    "混沌心法":   {"type": "修炼", "effect": {"cultivation_bonus": 0.60, "variant_only": True, "dual_element": True}},
    "混沌气团":   {"type": "攻击", "effect": {"multi_element": True, "ignore_single_defense": True}},
    "混沌护体":   {"type": "防御", "effect": {"random_element_shield": True}},

    "天机心法":   {"type": "修炼", "effect": {"cultivation_bonus_scale": "fortune", "enlighten_chance": True}},
    "天机预演":   {"type": "辅助", "effect": {"dodge_bonus_scale": "fortune"}},
    "因果斩":     {"type": "攻击", "effect": {"ignore_realm": True, "lifespan_cost": 10}},

    "无极心法":   {"type": "修炼", "effect": {"cultivation_bonus": 0.40, "all_stat_bonus": True}},
    "无极拳":     {"type": "攻击", "effect": {"attack_scale": "all_stats"}},
    "无极护体":   {"type": "防御", "effect": {"defense_scale": "all_stats"}},

    "轮回心法":   {"type": "修炼", "effect": {"cultivation_bonus_per_death": 0.20}},
    "死亡凝视":   {"type": "攻击", "effect": {"ignore_defense_chance": 0.3, "attack_scale": "soul"}},
    "不死之身":   {"type": "防御", "effect": {"revive_chance": 0.3, "once_per_realm": True}},
}


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
