import random

from utils import rules

SPIRIT_ROOT_TYPES = ["金", "木", "水", "火", "土"]
VARIANT_TYPES = ["雷", "冰", "风", "暗", "光"]

HOURS_PER_YEAR = 2          # 1 游戏年 = 现实 2 小时（时间的基本刻度，写进了很多文案和刻度，不在调参里）

# 灵根修炼速度 / 抽中概率、各境界寿元、修炼公式、置业价格等数值在 data/game_rules.json 的 character（管理员可以调），用的时候读


def cfg() -> dict:
    return rules.section("character")


def spirit_root_speed(root_type: str) -> float:
    return cfg()["spirit_root_speed"].get(root_type, 1.0)


def realm_lifespan(major: str) -> int:
    """大境界（如「炼气期」）的寿元上限。"""
    return cfg()["realm_lifespan"][major]


def auto_cultivate_threshold_years() -> float:
    return cfg()["cultivation"]["auto_threshold_years"]

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

def base_stats() -> dict:
    return dict(cfg()["base_stats"])


def roll_spirit_root(rng=random):
    """`rng` 默认用全局 random；机器人生成传自己的 Random 以便复现。"""
    odds = cfg()["spirit_root_odds"]               # 相对权重（默认加起来 100）
    roll, edge = rng.random() * sum(odds.values()), 0.0
    root_type = "变异灵根"
    for name, p in odds.items():            # 按单 / 双 / 三 / 四 / 五 / 变异的顺序累加概率
        edge += p
        if roll < edge:
            root_type = name
            break
    if root_type == "单灵根":
        elements = [rng.choice(SPIRIT_ROOT_TYPES)]
    elif root_type == "双灵根":
        elements = rng.sample(SPIRIT_ROOT_TYPES, 2)
    elif root_type == "三灵根":
        elements = rng.sample(SPIRIT_ROOT_TYPES, 3)
    elif root_type == "四灵根":
        elements = rng.sample(SPIRIT_ROOT_TYPES, 4)
    elif root_type == "五灵根":
        elements = SPIRIT_ROOT_TYPES[:]
    else:
        elements = [rng.choice(VARIANT_TYPES)]
    return "·".join(elements), root_type


def calc_stats(answers: dict) -> dict:
    stats = base_stats()
    for q_idx, choice in answers.items():
        _, bonuses = QUESTIONS[q_idx]["options"][choice]
        for key, val in bonuses.items():
            stats[key] = stats.get(key, 0) + val
    return stats


def calc_cultivation_gain(years: int, comprehension: int, root_type: str) -> int:
    c = cfg()["cultivation"]
    base = years * c["base_per_year"]
    comp_bonus = 1 + (comprehension - c["comprehension_base"]) * c["comprehension_step"]
    speed_bonus = spirit_root_speed(root_type)
    return int(base * comp_bonus * speed_bonus)


def years_to_seconds(years: float) -> float:
    return years * HOURS_PER_YEAR * 3600


def seconds_to_years(seconds: float) -> float:
    return seconds / (HOURS_PER_YEAR * 3600)


# 置业 / 洞府的加成、价格、声望门槛：rules.section("character")["residence"] / ["cave"]


def get_effective_lifespan_max(player: dict) -> int:
    import json
    base = player.get("lifespan_max", 100)
    techniques_raw = player.get("techniques")
    if not techniques_raw:
        return base
    from utils.sects import TECHNIQUES, pct_multiplier
    try:
        techs = json.loads(techniques_raw)
    except Exception:
        return base
    bonus = 0
    for t in techs:
        if isinstance(t, str):
            continue
        if not t.get("equipped"):
            continue
        info = TECHNIQUES.get(t.get("name", ""), {})
        lb = info.get("stat_bonus", {}).get("lifespan_bonus", 0)
        if lb:
            stage = t.get("stage", "入门")
            mult = pct_multiplier(stage)
            bonus += int(lb * mult)
    return base + bonus


def format_player_profile(player: dict) -> str:
    return player.get("name", "未知")


async def get_cultivation_bonus(discord_id: str, current_city: str, cave: str) -> float:
    from utils.residence import has_residence
    from sqlalchemy import text
    from utils.db_async import AsyncSessionLocal
    import json
    bonus = 0.0
    if await has_residence(discord_id, current_city):
        bonus += cfg()["residence"]["bonus"]
    if cave:
        bonus += cfg()["cave"]["bonus"]
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT techniques FROM players WHERE discord_id = :uid"),
            {"uid": discord_id}
        )
        row = result.fetchone()
    if row and row[0]:
        from utils.sects import calc_technique_stat_bonus
        techs = json.loads(row[0])
        stat_bonus = calc_technique_stat_bonus(techs)
        speed_val = stat_bonus.get("cultivation_speed", 0)
        bonus += speed_val
    return bonus


async def get_explore_limit_bonus(discord_id: str, current_city: str, cave: str) -> int:
    from utils.residence import has_residence
    bonus = 0
    if await has_residence(discord_id, current_city):
        bonus += cfg()["residence"]["explore_bonus"]
    if cave:
        bonus += cfg()["cave"]["explore_bonus"]
    return bonus
