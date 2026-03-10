import random
import uuid

QUALITY_ORDER = ["普通", "精良", "稀有", "史诗", "传说"]

QUALITY_COLOR = {
    "普通": "⬜",
    "精良": "🟩",
    "稀有": "🟦",
    "史诗": "🟪",
    "传说": "🟨",
}

QUALITY_STAT_MULT = {
    "普通": 1.0,
    "精良": 1.5,
    "稀有": 2.2,
    "史诗": 3.5,
    "传说": 6.0,
}

QUALITY_AFFIX_COUNT = {
    "普通": (0, 0),
    "精良": (1, 1),
    "稀有": (1, 2),
    "史诗": (2, 2),
    "传说": (2, 3),
}

SLOTS = ["武器", "防具", "饰品"]

REALM_TIER = {
    "炼气": 0, "筑基": 1, "结丹": 2, "元婴": 3, "化神": 4,
    "炼虚": 5, "合体": 6, "大乘": 7, "真仙": 8, "金仙": 9,
    "太乙": 10, "大罗": 11, "道祖": 12,
}

TIER_NAMES = [
    "炼气", "筑基", "结丹", "元婴", "化神",
    "炼虚", "合体", "大乘", "真仙", "金仙",
    "太乙", "大罗", "道祖",
]

STAT_NAMES = {
    "physique": "体魄",
    "bone": "根骨",
    "soul": "神识",
    "comprehension": "悟性",
    "fortune": "机缘",
    "escape_rate": "逃跑成功率",
}

EQUIP_TEMPLATES = {
    "武器": [
        {"name": "长剑", "stats": ["physique", "bone"], "flavor": "三尺青锋，斩妖除魔"},
        {"name": "飞剑", "stats": ["physique", "soul"], "flavor": "御剑千里，攻伐利器"},
        {"name": "短剑", "stats": ["physique", "fortune"], "flavor": "轻巧灵动，出其不意"},
        {"name": "重剑", "stats": ["physique", "physique"], "flavor": "重剑无锋，大巧不工"},
        {"name": "双刃剑", "stats": ["physique", "bone"], "flavor": "双刃齐出，攻守兼备"},
        {"name": "古剑", "stats": ["bone", "soul"], "flavor": "剑身古朴，暗藏锋芒"},
        {"name": "柳叶剑", "stats": ["fortune", "physique"], "flavor": "剑如柳叶，轻灵飘逸"},
        {"name": "霜寒剑", "stats": ["soul", "physique"], "flavor": "剑出霜寒，万物凋零"},
        {"name": "赤霄剑", "stats": ["physique", "comprehension"], "flavor": "赤光冲霄，帝王之剑"},
        {"name": "战刀", "stats": ["physique", "physique"], "flavor": "横扫千军，力劈山河"},
        {"name": "弯刀", "stats": ["physique", "fortune"], "flavor": "刀如弯月，诡谲难防"},
        {"name": "斩马刀", "stats": ["physique", "bone"], "flavor": "一刀断魂，势不可挡"},
        {"name": "鬼头刀", "stats": ["physique", "soul"], "flavor": "刀锋饮血，鬼神辟易"},
        {"name": "雁翎刀", "stats": ["fortune", "physique"], "flavor": "刀轻如羽，快若惊鸿"},
        {"name": "环首刀", "stats": ["bone", "physique"], "flavor": "百炼精钢，军中利刃"},
        {"name": "法杖", "stats": ["soul", "comprehension"], "flavor": "凝聚神识，催动法术"},
        {"name": "玉笛", "stats": ["soul", "fortune"], "flavor": "笛声悠扬，摄人心魄"},
        {"name": "拂尘", "stats": ["comprehension", "soul"], "flavor": "拂去尘埃，明心见性"},
        {"name": "铜铃", "stats": ["soul", "soul"], "flavor": "铃声清脆，震慑邪祟"},
        {"name": "幡旗", "stats": ["soul", "bone"], "flavor": "招魂引魄，驱使阴兵"},
        {"name": "玉如意", "stats": ["comprehension", "fortune"], "flavor": "如意随心，变化万千"},
        {"name": "七星灯", "stats": ["soul", "fortune"], "flavor": "七星排列，续命延寿"},
        {"name": "九节杖", "stats": ["bone", "soul"], "flavor": "九节连环，刚柔并济"},
        {"name": "浮屠塔", "stats": ["soul", "bone"], "flavor": "佛光普照，镇压万邪"},
        {"name": "灵弓", "stats": ["fortune", "soul"], "flavor": "百步穿杨，机缘加持"},
        {"name": "暗器匣", "stats": ["fortune", "physique"], "flavor": "暗器无形，防不胜防"},
        {"name": "袖箭", "stats": ["fortune", "fortune"], "flavor": "袖中乾坤，一击必杀"},
        {"name": "玄鞭", "stats": ["bone", "physique"], "flavor": "柔中带刚，缠绕敌身"},
        {"name": "锁链", "stats": ["physique", "soul"], "flavor": "锁天缚地，困敌于方寸"},
        {"name": "三叉戟", "stats": ["physique", "bone"], "flavor": "三尖两刃，水族至宝"},
        {"name": "量天尺", "stats": ["bone", "soul"], "flavor": "丈量天地，破界之器"},
        {"name": "判官笔", "stats": ["soul", "comprehension"], "flavor": "笔落生死，判定阴阳"},
        {"name": "流星锤", "stats": ["physique", "fortune"], "flavor": "流星赶月，势大力沉"},
        {"name": "月牙铲", "stats": ["bone", "comprehension"], "flavor": "铲除妖邪，佛门法器"},
        {"name": "钩镰枪", "stats": ["physique", "bone"], "flavor": "钩拉锁带，克制骑兵"},
        {"name": "阴阳扇", "stats": ["comprehension", "soul"], "flavor": "一扇阴阳，翻覆乾坤"},
        {"name": "天机伞", "stats": ["fortune", "soul"], "flavor": "伞开天机，攻守一体"},
        {"name": "琵琶", "stats": ["soul", "comprehension"], "flavor": "弦音杀伐，声震九霄"},
        {"name": "金刚杵", "stats": ["bone", "physique"], "flavor": "金刚不坏，降魔伏妖"},
        {"name": "缚妖索", "stats": ["soul", "fortune"], "flavor": "一索缚妖，万邪不侵"},
    ],
    "防具": [
        {"name": "玄铁甲", "stats": ["physique", "bone"], "flavor": "坚不可摧，铁壁铜墙"},
        {"name": "锁子甲", "stats": ["physique", "physique"], "flavor": "环环相扣，刀枪不入"},
        {"name": "鳞甲", "stats": ["physique", "fortune"], "flavor": "龙鳞覆体，水火不侵"},
        {"name": "骨甲", "stats": ["bone", "bone"], "flavor": "妖兽骨骼锻造，坚逾精钢"},
        {"name": "山纹甲", "stats": ["bone", "physique"], "flavor": "山岳纹路，厚重如岳"},
        {"name": "寒铁甲", "stats": ["physique", "soul"], "flavor": "寒铁铸就，冰寒刺骨"},
        {"name": "赤金甲", "stats": ["physique", "fortune"], "flavor": "赤金锻造，贵不可言"},
        {"name": "蛟皮甲", "stats": ["bone", "fortune"], "flavor": "蛟龙皮革，柔韧非凡"},
        {"name": "云纹袍", "stats": ["fortune", "comprehension"], "flavor": "轻盈如云，机缘护身"},
        {"name": "玄衣", "stats": ["soul", "fortune"], "flavor": "暗色玄衣，隐匿气息"},
        {"name": "道袍", "stats": ["comprehension", "bone"], "flavor": "道韵天成，修行之衣"},
        {"name": "战袍", "stats": ["physique", "soul"], "flavor": "战意凛然，激发斗志"},
        {"name": "霓裳", "stats": ["fortune", "soul"], "flavor": "霓裳羽衣，仙气飘飘"},
        {"name": "墨羽衣", "stats": ["soul", "soul"], "flavor": "墨羽如夜，神识如渊"},
        {"name": "星辰袍", "stats": ["comprehension", "fortune"], "flavor": "星辰点缀，天道加身"},
        {"name": "血衣", "stats": ["physique", "bone"], "flavor": "血染战衣，杀意冲天"},
        {"name": "青莲法衣", "stats": ["comprehension", "soul"], "flavor": "青莲绽放，心如止水"},
        {"name": "紫电袍", "stats": ["soul", "physique"], "flavor": "紫电缠身，雷霆之威"},
        {"name": "护身符", "stats": ["soul", "fortune"], "flavor": "神识护体，逢凶化吉"},
        {"name": "护心镜", "stats": ["bone", "soul"], "flavor": "铜镜护心，抵御暗算"},
        {"name": "龟甲盾", "stats": ["physique", "physique"], "flavor": "厚重如山，防御无双"},
        {"name": "灵纹盾", "stats": ["soul", "bone"], "flavor": "灵纹流转，法术减免"},
        {"name": "玄武盾", "stats": ["bone", "bone"], "flavor": "玄武之力，万法不侵"},
        {"name": "隐身斗篷", "stats": ["fortune", "soul"], "flavor": "遁入虚空，踪迹全无"},
        {"name": "兽皮披风", "stats": ["physique", "bone"], "flavor": "妖兽皮毛，御寒挡伤"},
        {"name": "鹤羽披风", "stats": ["fortune", "comprehension"], "flavor": "仙鹤羽翼，飘然若仙"},
        {"name": "火云披风", "stats": ["physique", "soul"], "flavor": "火云翻涌，灼烧万物"},
        {"name": "玄冰斗篷", "stats": ["soul", "bone"], "flavor": "玄冰覆体，寒气逼人"},
        {"name": "金丝软甲", "stats": ["fortune", "physique"], "flavor": "金丝编织，刀枪难入"},
        {"name": "天蛛丝衣", "stats": ["fortune", "soul"], "flavor": "天蛛吐丝，轻薄坚韧"},
    ],
    "饰品": [
        {"name": "聚灵戒", "stats": ["comprehension", "soul"], "flavor": "聚拢灵气，修炼加速"},
        {"name": "储物戒", "stats": ["fortune", "fortune"], "flavor": "纳须弥于芥子，空间法宝"},
        {"name": "噬魂戒", "stats": ["soul", "physique"], "flavor": "吞噬魂力，以战养战"},
        {"name": "血玉戒", "stats": ["physique", "bone"], "flavor": "血玉温养，气血旺盛"},
        {"name": "寒玉戒", "stats": ["soul", "comprehension"], "flavor": "寒玉清心，杂念不生"},
        {"name": "龙纹戒", "stats": ["bone", "physique"], "flavor": "龙纹刻印，霸气侧漏"},
        {"name": "神识镯", "stats": ["soul", "soul"], "flavor": "神识通明，感知万物"},
        {"name": "禁锢镯", "stats": ["bone", "physique"], "flavor": "封印之力，困敌于内"},
        {"name": "灵玉镯", "stats": ["comprehension", "fortune"], "flavor": "灵玉温润，心神宁静"},
        {"name": "金蚕丝镯", "stats": ["fortune", "bone"], "flavor": "金蚕吐丝，缠绵不断"},
        {"name": "九转镯", "stats": ["bone", "soul"], "flavor": "九转轮回，生生不息"},
        {"name": "根骨链", "stats": ["bone", "comprehension"], "flavor": "强化根骨，突破更易"},
        {"name": "辟邪坠", "stats": ["soul", "fortune"], "flavor": "辟邪挡灾，百邪不侵"},
        {"name": "龙骨坠", "stats": ["bone", "bone"], "flavor": "龙骨精华，根基深厚"},
        {"name": "凤血坠", "stats": ["fortune", "soul"], "flavor": "凤血淬炼，浴火重生"},
        {"name": "星陨坠", "stats": ["physique", "soul"], "flavor": "星辰陨落，天外之物"},
        {"name": "琉璃坠", "stats": ["comprehension", "comprehension"], "flavor": "琉璃通透，心明如镜"},
        {"name": "乾坤带", "stats": ["physique", "bone"], "flavor": "束腰提气，力贯周身"},
        {"name": "灵蛇腰带", "stats": ["fortune", "soul"], "flavor": "灵蛇缠腰，身法灵动"},
        {"name": "锁龙带", "stats": ["bone", "physique"], "flavor": "锁龙之力，镇压四方"},
        {"name": "血煞环", "stats": ["physique", "bone"], "flavor": "煞气凛然，战力大增"},
        {"name": "机缘珠", "stats": ["fortune", "fortune"], "flavor": "机缘加身，好运连连"},
        {"name": "天眼石", "stats": ["soul", "comprehension"], "flavor": "开天眼，观因果"},
        {"name": "命魂灯", "stats": ["soul", "fortune"], "flavor": "命魂不灭，死中求活"},
        {"name": "玲珑心", "stats": ["comprehension", "soul"], "flavor": "七窍玲珑，万法皆通"},
        {"name": "万兽牙", "stats": ["physique", "physique"], "flavor": "万兽之牙，凶威赫赫"},
        {"name": "天蚕珠", "stats": ["fortune", "bone"], "flavor": "天蚕化珠，蜕变新生"},
        {"name": "菩提子", "stats": ["comprehension", "fortune"], "flavor": "菩提明心，顿悟天道"},
        {"name": "太极玉", "stats": ["bone", "soul"], "flavor": "阴阳流转，生生不息"},
        {"name": "破军星", "stats": ["physique", "fortune"], "flavor": "破军星动，百战百胜"},
    ],
}

PREFIXES = {
    "武器": [
        {"name": "嗜血", "stats": {"physique": 1}, "weight": 10},
        {"name": "狂暴", "stats": {"physique": 2}, "weight": 6},
        {"name": "蛮荒", "stats": {"physique": 1, "bone": 1}, "weight": 7},
        {"name": "碎骨", "stats": {"physique": 2}, "weight": 5},
        {"name": "裂天", "stats": {"physique": 1, "soul": 1}, "weight": 5},
        {"name": "焚天", "stats": {"physique": 2, "soul": 1}, "weight": 3},
        {"name": "灭世", "stats": {"physique": 1, "bone": 1}, "weight": 4},
        {"name": "破军", "stats": {"physique": 1, "fortune": 1}, "weight": 5},
        {"name": "幽冥", "stats": {"soul": 2}, "weight": 7},
        {"name": "噬魂", "stats": {"soul": 1, "physique": 1}, "weight": 6},
        {"name": "梦魇", "stats": {"soul": 2}, "weight": 5},
        {"name": "摄心", "stats": {"soul": 1, "comprehension": 1}, "weight": 6},
        {"name": "夺魄", "stats": {"soul": 2, "fortune": 1}, "weight": 3},
        {"name": "冥府", "stats": {"soul": 1, "bone": 1}, "weight": 5},
        {"name": "不朽", "stats": {"bone": 2}, "weight": 5},
        {"name": "磐石", "stats": {"bone": 1, "physique": 1}, "weight": 7},
        {"name": "玄铁", "stats": {"bone": 2}, "weight": 6},
        {"name": "陨铁", "stats": {"bone": 1, "soul": 1}, "weight": 5},
        {"name": "九炼", "stats": {"bone": 2, "physique": 1}, "weight": 3},
        {"name": "悟道", "stats": {"comprehension": 2}, "weight": 5},
        {"name": "通灵", "stats": {"comprehension": 1, "soul": 1}, "weight": 6},
        {"name": "天启", "stats": {"comprehension": 2}, "weight": 4},
        {"name": "参悟", "stats": {"comprehension": 1, "bone": 1}, "weight": 5},
        {"name": "顿悟", "stats": {"comprehension": 2, "fortune": 1}, "weight": 3},
        {"name": "天命", "stats": {"fortune": 2}, "weight": 5},
        {"name": "造化", "stats": {"fortune": 1, "comprehension": 1}, "weight": 6},
        {"name": "逆天", "stats": {"fortune": 1, "bone": 1}, "weight": 4},
        {"name": "气运", "stats": {"fortune": 2}, "weight": 5},
        {"name": "紫气", "stats": {"fortune": 1, "soul": 1}, "weight": 5},
        {"name": "混沌", "stats": {"physique": 1, "soul": 1, "fortune": 1}, "weight": 3},
        {"name": "太古", "stats": {"bone": 1, "physique": 1, "soul": 1}, "weight": 3},
        {"name": "鸿蒙", "stats": {"comprehension": 1, "fortune": 1, "bone": 1}, "weight": 2},
        {"name": "开天", "stats": {"physique": 1, "bone": 1, "comprehension": 1}, "weight": 2},
        {"name": "无上", "stats": {"soul": 1, "comprehension": 1, "fortune": 1}, "weight": 2},
    ],
    "防具": [
        {"name": "坚韧", "stats": {"physique": 2}, "weight": 10},
        {"name": "不灭", "stats": {"physique": 1, "bone": 1}, "weight": 7},
        {"name": "铜墙", "stats": {"physique": 2}, "weight": 6},
        {"name": "万钧", "stats": {"physique": 1, "bone": 1}, "weight": 5},
        {"name": "铁壁", "stats": {"physique": 2, "bone": 1}, "weight": 3},
        {"name": "磐岩", "stats": {"physique": 1, "soul": 1}, "weight": 5},
        {"name": "固本", "stats": {"bone": 2}, "weight": 8},
        {"name": "培元", "stats": {"bone": 1, "comprehension": 1}, "weight": 6},
        {"name": "金刚", "stats": {"bone": 2}, "weight": 5},
        {"name": "不破", "stats": {"bone": 1, "physique": 1}, "weight": 5},
        {"name": "天罡", "stats": {"bone": 2, "soul": 1}, "weight": 3},
        {"name": "龙鳞", "stats": {"bone": 1, "fortune": 1}, "weight": 5},
        {"name": "静心", "stats": {"soul": 2}, "weight": 7},
        {"name": "凝神", "stats": {"soul": 1, "comprehension": 1}, "weight": 6},
        {"name": "定魂", "stats": {"soul": 1, "bone": 1}, "weight": 5},
        {"name": "清心", "stats": {"soul": 2}, "weight": 5},
        {"name": "镇魂", "stats": {"soul": 1, "physique": 1}, "weight": 5},
        {"name": "福泽", "stats": {"fortune": 2}, "weight": 6},
        {"name": "祥瑞", "stats": {"fortune": 1, "soul": 1}, "weight": 5},
        {"name": "天佑", "stats": {"fortune": 1, "bone": 1}, "weight": 5},
        {"name": "鸿运", "stats": {"fortune": 2}, "weight": 5},
        {"name": "紫微", "stats": {"fortune": 1, "comprehension": 1}, "weight": 4},
        {"name": "明悟", "stats": {"comprehension": 2}, "weight": 5},
        {"name": "灵犀", "stats": {"comprehension": 1, "fortune": 1}, "weight": 5},
        {"name": "悟真", "stats": {"comprehension": 1, "soul": 1}, "weight": 5},
        {"name": "太虚", "stats": {"soul": 1, "fortune": 1, "comprehension": 1}, "weight": 3},
        {"name": "洪荒", "stats": {"physique": 1, "bone": 1, "soul": 1}, "weight": 3},
        {"name": "无极", "stats": {"bone": 1, "comprehension": 1, "fortune": 1}, "weight": 2},
        {"name": "混元", "stats": {"physique": 1, "soul": 1, "fortune": 1}, "weight": 2},
        {"name": "先天", "stats": {"bone": 1, "comprehension": 1, "physique": 1}, "weight": 2},
    ],
    "饰品": [
        {"name": "开悟", "stats": {"comprehension": 2}, "weight": 8},
        {"name": "慧根", "stats": {"comprehension": 1, "bone": 1}, "weight": 7},
        {"name": "灵台", "stats": {"comprehension": 1, "soul": 1}, "weight": 6},
        {"name": "明心", "stats": {"comprehension": 2}, "weight": 5},
        {"name": "见性", "stats": {"comprehension": 1, "fortune": 1}, "weight": 5},
        {"name": "菩提", "stats": {"comprehension": 2, "soul": 1}, "weight": 3},
        {"name": "气运", "stats": {"fortune": 2}, "weight": 8},
        {"name": "紫微", "stats": {"fortune": 1, "soul": 1}, "weight": 6},
        {"name": "星辰", "stats": {"fortune": 1, "comprehension": 1}, "weight": 6},
        {"name": "天机", "stats": {"fortune": 2}, "weight": 5},
        {"name": "鸿福", "stats": {"fortune": 1, "bone": 1}, "weight": 5},
        {"name": "天赐", "stats": {"fortune": 2, "comprehension": 1}, "weight": 3},
        {"name": "灵觉", "stats": {"soul": 2}, "weight": 7},
        {"name": "天聪", "stats": {"soul": 1, "comprehension": 1}, "weight": 6},
        {"name": "洞察", "stats": {"soul": 1, "fortune": 1}, "weight": 5},
        {"name": "通幽", "stats": {"soul": 2}, "weight": 5},
        {"name": "玄感", "stats": {"soul": 1, "bone": 1}, "weight": 5},
        {"name": "淬体", "stats": {"bone": 2}, "weight": 6},
        {"name": "炼骨", "stats": {"bone": 1, "physique": 1}, "weight": 6},
        {"name": "铸基", "stats": {"bone": 2}, "weight": 5},
        {"name": "凝脉", "stats": {"bone": 1, "soul": 1}, "weight": 5},
        {"name": "蛮力", "stats": {"physique": 2}, "weight": 5},
        {"name": "铁血", "stats": {"physique": 1, "bone": 1}, "weight": 5},
        {"name": "战魂", "stats": {"physique": 1, "soul": 1}, "weight": 5},
        {"name": "先天", "stats": {"bone": 1, "comprehension": 1, "fortune": 1}, "weight": 3},
        {"name": "造物", "stats": {"soul": 1, "fortune": 1, "comprehension": 1}, "weight": 3},
        {"name": "永恒", "stats": {"physique": 1, "bone": 1, "soul": 1}, "weight": 2},
        {"name": "太初", "stats": {"comprehension": 1, "fortune": 1, "soul": 1}, "weight": 2},
        {"name": "归元", "stats": {"bone": 1, "physique": 1, "fortune": 1}, "weight": 2},
    ],
}

SUFFIXES = [
    {"name": "之力", "stats": {"physique": 1}, "weight": 10},
    {"name": "之坚", "stats": {"bone": 1}, "weight": 10},
    {"name": "之灵", "stats": {"soul": 1}, "weight": 10},
    {"name": "之悟", "stats": {"comprehension": 1}, "weight": 10},
    {"name": "之幸", "stats": {"fortune": 1}, "weight": 10},
    {"name": "之怒", "stats": {"physique": 2}, "weight": 5},
    {"name": "之魂", "stats": {"soul": 2}, "weight": 5},
    {"name": "之道", "stats": {"comprehension": 2}, "weight": 5},
    {"name": "之命", "stats": {"fortune": 2}, "weight": 5},
    {"name": "之根", "stats": {"bone": 2}, "weight": 5},
    {"name": "之守护", "stats": {"physique": 1, "bone": 1}, "weight": 6},
    {"name": "之洞察", "stats": {"soul": 1, "comprehension": 1}, "weight": 6},
    {"name": "之天命", "stats": {"fortune": 1, "soul": 1}, "weight": 5},
    {"name": "之不朽", "stats": {"bone": 1, "physique": 1}, "weight": 5},
    {"name": "之轮回", "stats": {"fortune": 1, "bone": 1}, "weight": 4},
    {"name": "之超脱", "stats": {"comprehension": 1, "fortune": 1}, "weight": 4},
    {"name": "之万象", "stats": {"physique": 1, "soul": 1, "fortune": 1}, "weight": 2},
    {"name": "之混元", "stats": {"bone": 1, "comprehension": 1, "soul": 1}, "weight": 2},
    {"name": "之天道", "stats": {"comprehension": 1, "fortune": 1, "bone": 1}, "weight": 2},
    {"name": "之霸", "stats": {"physique": 2, "bone": 1}, "weight": 3},
    {"name": "之仙", "stats": {"comprehension": 1, "fortune": 1, "soul": 1}, "weight": 2},
    {"name": "之殇", "stats": {"soul": 2, "physique": 1}, "weight": 3},
    {"name": "之劫", "stats": {"bone": 1, "fortune": 1}, "weight": 4},
    {"name": "之缘", "stats": {"fortune": 2, "comprehension": 1}, "weight": 3},
    {"name": "之誓", "stats": {"bone": 2, "soul": 1}, "weight": 3},
    {"name": "之渊", "stats": {"soul": 1, "physique": 1}, "weight": 5},
    {"name": "之巅", "stats": {"physique": 1, "bone": 1, "comprehension": 1}, "weight": 2},
    {"name": "之源", "stats": {"bone": 1, "soul": 1, "fortune": 1}, "weight": 2},
    {"name": "之极", "stats": {"physique": 1, "comprehension": 1}, "weight": 4},
    {"name": "之铭", "stats": {"soul": 1, "bone": 1}, "weight": 5},
]

LEGENDARY_NAMES = {
    "武器": [
        "弑神", "天罚", "诛仙", "屠龙", "轩辕",
        "干将", "莫邪", "承影", "纯钧", "太阿",
        "龙渊", "湛卢", "鱼肠", "巨阙", "赤霄",
        "含光", "宵练", "七杀", "贪狼", "破军",
        "天问", "无名", "绝云", "裂魂", "噬天",
    ],
    "防具": [
        "不灭金身", "天蚕宝衣", "混元法袍", "九龙神甲", "太极阴阳衣",
        "玄武真甲", "凤羽霓裳", "星辰战袍", "万劫不磨衣", "天罡护体",
        "昆仑镜甲", "盘古战甲", "女娲灵衣", "后土法袍", "伏羲八卦衣",
        "鲲鹏羽衣", "麒麟圣甲", "白泽灵袍", "朱雀火衣", "青龙鳞甲",
    ],
    "饰品": [
        "山河社稷图", "乾坤圈", "混天绫", "定海神珠", "紫金葫芦",
        "照妖镜", "八卦炉", "天机盘", "轮回珠", "造化玉碟",
        "河图洛书", "昆仑玉令", "封神榜", "天书残卷", "盘古斧印",
        "女娲石", "伏羲琴", "神农鼎", "轩辕印", "仓颉碑",
    ],
}


def get_player_tier(realm: str) -> int:
    for prefix, tier in REALM_TIER.items():
        if realm.startswith(prefix):
            return tier
    return 0


def _pick_weighted(pool: list[dict]) -> dict:
    weights = [item["weight"] for item in pool]
    return random.choices(pool, weights=weights, k=1)[0]


def _pick_affixes(slot: str, quality: str, tier: int) -> tuple[list[dict], dict | None]:
    lo, hi = QUALITY_AFFIX_COUNT[quality]
    count = random.randint(lo, hi)
    if count == 0:
        return [], None

    prefix_pool = PREFIXES[slot]
    prefixes = []
    used_names = set()

    if count >= 1:
        p = _pick_weighted(prefix_pool)
        prefixes.append(p)
        used_names.add(p["name"])

    suffix = None
    if count >= 2:
        if random.random() < 0.5:
            candidates = [p for p in prefix_pool if p["name"] not in used_names]
            if candidates:
                p = _pick_weighted(candidates)
                prefixes.append(p)
                used_names.add(p["name"])
            else:
                suffix = _pick_weighted(SUFFIXES)
        else:
            suffix = _pick_weighted(SUFFIXES)

    if count >= 3:
        if suffix is None:
            suffix = _pick_weighted(SUFFIXES)
        else:
            candidates = [p for p in prefix_pool if p["name"] not in used_names]
            if candidates:
                p = _pick_weighted(candidates)
                prefixes.append(p)

    return prefixes, suffix


def generate_equipment(tier: int = 0, quality: str = None, slot: str = None) -> dict:
    if slot is None:
        slot = random.choice(SLOTS)
    if quality is None:
        weights = [50, 30, 15, 4, 1]
        quality = random.choices(QUALITY_ORDER, weights=weights)[0]

    template = random.choice(EQUIP_TEMPLATES[slot])
    mult = QUALITY_STAT_MULT[quality]
    base = 1 + tier // 2

    stats = {}
    for stat in template["stats"]:
        val = max(1, int(base * mult * random.uniform(0.8, 1.2)))
        stats[stat] = stats.get(stat, 0) + val

    prefixes, suffix = _pick_affixes(slot, quality, tier)
    affix_mult = max(1, base * 0.6)

    for pfx in prefixes:
        for stat, val in pfx["stats"].items():
            bonus = max(1, int(val * affix_mult * random.uniform(0.8, 1.2)))
            stats[stat] = stats.get(stat, 0) + bonus

    if suffix:
        for stat, val in suffix["stats"].items():
            bonus = max(1, int(val * affix_mult * random.uniform(0.8, 1.2)))
            stats[stat] = stats.get(stat, 0) + bonus

    tier_name = TIER_NAMES[min(tier, len(TIER_NAMES) - 1)]

    if quality == "传说" and LEGENDARY_NAMES.get(slot):
        base_name = random.choice(LEGENDARY_NAMES[slot])
    else:
        base_name = template["name"]

    prefix_str = ""
    if prefixes:
        prefix_str = "·".join(p["name"] for p in prefixes) + "·"

    suffix_str = ""
    if suffix:
        suffix_str = suffix["name"]

    name = f"{tier_name}·{prefix_str}{base_name}{suffix_str}"

    return {
        "equip_id": str(uuid.uuid4())[:8],
        "name": name,
        "slot": slot,
        "quality": quality,
        "tier": tier,
        "tier_req": tier,
        "stats": stats,
        "flavor": template["flavor"],
    }


def equip_stat_bonus(equipped: list[dict]) -> dict:
    total = {}
    for eq in equipped:
        for stat, val in eq.get("stats", {}).items():
            total[stat] = total.get(stat, 0) + val
    return total


def format_equipment(eq: dict) -> str:
    icon = QUALITY_COLOR.get(eq["quality"], "⬜")
    stats_str = "  ".join(f"{STAT_NAMES.get(k, k)} +{v}" for k, v in eq["stats"].items())
    tier_name = TIER_NAMES[min(eq["tier"], len(TIER_NAMES) - 1)]
    return (
        f"{icon} **{eq['name']}**（{eq['slot']}）\n"
        f"　{eq['flavor']}\n"
        f"　需求：{tier_name}期　属性：{stats_str}"
    )
