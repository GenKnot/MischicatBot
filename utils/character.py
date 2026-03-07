import random

SPIRIT_ROOT_TYPES = ["金", "木", "水", "火", "土"]
VARIANT_TYPES = ["雷", "冰", "风", "暗", "光"]

SPIRIT_ROOT_SPEED = {
    "单灵根": 2.0,
    "双灵根": 1.5,
    "三灵根": 1.2,
    "四灵根": 0.9,
    "五灵根": 0.7,
    "变异灵根": 1.8,
}

REALM_LIFESPAN = {
    "炼气期": 100,
    "筑基期": 200,
    "结丹期": 450,
    "元婴期": 1000,
    "化神期": 2000,
    "炼虚期": 3000,
    "合体期": 5000,
    "大乘期": 10000,
}

HOURS_PER_YEAR = 2
AUTO_CULTIVATE_THRESHOLD_YEARS = 2

QUESTIONS = [
    {
        "text": "你出身于？",
        "options": {
            "A": ("名门世家", {"spirit_stones": 100, "comprehension": -1, "bone": 1}),
            "B": ("书香门第", {"comprehension": 1, "soul": 1}),
            "C": ("贫寒草莽", {"physique": 1, "fortune": 1}),
        },
    },
    {
        "text": "幼年时，令你印象最深的记忆是？",
        "options": {
            "A": ("偶得一本残缺的古老功法", {"comprehension": 2}),
            "B": ("曾被一位神秘高人驻足打量", {"fortune": 2}),
            "C": ("与同龄人争斗从未落败", {"physique": 2}),
        },
    },
    {
        "text": "是什么让你踏上修仙之路？",
        "options": {
            "A": ("亲眼目睹仙人御剑飞升", {"comprehension": 1, "fortune": 1}),
            "B": ("血海深仇，必须变强", {"physique": 1, "bone": 1}),
            "C": ("不甘老死，渴望长生", {"soul": 1, "comprehension": 1}),
        },
    },
    {
        "text": "旁人眼中，你是个怎样的人？",
        "options": {
            "A": ("沉默寡言，深不可测", {"soul": 1, "comprehension": 1}),
            "B": ("豪爽直率，快意恩仇", {"physique": 1, "fortune": 1}),
            "C": ("八面玲珑，左右逢源", {"fortune": 1, "bone": 1}),
        },
    },
    {
        "text": "面对突如其来的危险，你会？",
        "options": {
            "A": ("冷静观察，寻找破绽", {"comprehension": 1, "soul": 1}),
            "B": ("挺身而出，正面迎敌", {"physique": 2}),
            "C": ("隐匿气息，伺机而动", {"fortune": 2}),
        },
    },
    {
        "text": "若有一日空闲，你最愿意做什么？",
        "options": {
            "A": ("研读典籍，参悟道理", {"comprehension": 2}),
            "B": ("锤炼肉身，强化根基", {"physique": 1, "bone": 1}),
            "C": ("游历山川，广结善缘", {"fortune": 1, "soul": 1}),
        },
    },
    {
        "text": "得到一笔意外之财，你会？",
        "options": {
            "A": ("悉数存下，以备不时之需", {"spirit_stones": 80}),
            "B": ("购置丹药典籍，提升自身", {"comprehension": 1, "bone": 1}),
            "C": ("接济同道，广结善缘", {"fortune": 1, "soul": 1}),
        },
    },
    {
        "text": "遭遇远超自身的强敌，你会？",
        "options": {
            "A": ("忍辱负重，徐徐图之", {"fortune": 1, "soul": 1}),
            "B": ("拼死一搏，以命换命", {"physique": 1, "bone": 1}),
            "C": ("广结盟友，借力打力", {"comprehension": 1, "fortune": 1}),
        },
    },
    {
        "text": "在你心中，长生意味着什么？",
        "options": {
            "A": ("守护所珍视之人", {"physique": 1, "bone": 1}),
            "B": ("追求天地大道的尽头", {"comprehension": 2}),
            "C": ("长生本身便是意义", {"soul": 2}),
        },
    },
    {
        "text": "踏入修仙界前的最后一夜，你？",
        "options": {
            "A": ("彻夜苦读，不敢懈怠", {"comprehension": 2}),
            "B": ("打坐冥想，平息心神", {"soul": 1, "bone": 1}),
            "C": ("倒头便睡，天命自有安排", {"physique": 1, "fortune": 1}),
        },
    },
]

BASE_STATS = {
    "comprehension": 5,
    "physique": 5,
    "fortune": 5,
    "bone": 5,
    "soul": 5,
    "spirit_stones": 50,
}


def roll_spirit_root():
    roll = random.random() * 100
    if roll < 1:
        root_type = "单灵根"
        elements = [random.choice(SPIRIT_ROOT_TYPES)]
    elif roll < 10:
        root_type = "双灵根"
        elements = random.sample(SPIRIT_ROOT_TYPES, 2)
    elif roll < 30:
        root_type = "三灵根"
        elements = random.sample(SPIRIT_ROOT_TYPES, 3)
    elif roll < 65:
        root_type = "四灵根"
        elements = random.sample(SPIRIT_ROOT_TYPES, 4)
    elif roll < 95:
        root_type = "五灵根"
        elements = SPIRIT_ROOT_TYPES[:]
    else:
        root_type = "变异灵根"
        elements = [random.choice(VARIANT_TYPES)]
    return "·".join(elements), root_type


def calc_stats(answers: dict) -> dict:
    stats = dict(BASE_STATS)
    for q_idx, choice in answers.items():
        _, bonuses = QUESTIONS[q_idx]["options"][choice]
        for key, val in bonuses.items():
            stats[key] = stats.get(key, 0) + val
    return stats


def calc_cultivation_gain(years: int, comprehension: int, root_type: str) -> int:
    base = years * 10
    comp_bonus = 1 + (comprehension - 5) * 0.05
    speed_bonus = SPIRIT_ROOT_SPEED.get(root_type, 1.0)
    return int(base * comp_bonus * speed_bonus)


def years_to_seconds(years: float) -> float:
    return years * HOURS_PER_YEAR * 3600


def seconds_to_years(seconds: float) -> float:
    return seconds / (HOURS_PER_YEAR * 3600)
