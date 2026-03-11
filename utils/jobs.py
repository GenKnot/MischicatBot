import random
from utils.realms import get_realm_index

JOBS = [
    {
        "id": "sweep",
        "name": "街头扫洒",
        "tier": 1,
        "speaker": "街坊",
        "desc": "在城市街道打扫，无需任何资质。",
        "req": {},
        "reward": {"spirit_stones": (30, 80)},
        "dialogues": [
            "「道友，这把扫帚用了三十年，今日就交给你了。」",
            "「修仙之人做这等粗活……唉，谁没有难处呢。」",
            "「扫得干净，掌柜多给两枚灵石。」",
            "「这条街每天都有人扔灵石碎屑，捡到算你的。」",
        ],
    },
    {
        "id": "porter",
        "name": "码头扛货",
        "tier": 1,
        "speaker": "码头管事",
        "desc": "在港口城市搬运货物，纯体力活。",
        "req": {},
        "city_tags": ["港口", "北冥港", "碧波城"],
        "reward": {"spirit_stones": (50, 120)},
        "dialogues": [
            "「这箱灵石矿少说三百斤，道友一个人扛？」",
            "「码头的活儿不好做，但胜在稳当。」",
            "「今日货多，多干一趟，多给二十灵石。」",
            "「听说上次来扛货的是个元婴修士……落魄成这样，唉。」",
        ],
    },
    {
        "id": "waiter",
        "name": "茶馆跑堂",
        "tier": 1,
        "speaker": "茶馆掌柜",
        "desc": "在茶馆端茶倒水，消息灵通。",
        "req": {},
        "reward": {"spirit_stones": (40, 100), "reputation": (0, 2)},
        "dialogues": [
            "「道友手脚麻利，这桌客人等了半天了，快去！」",
            "「跑堂的好处是能听到各种消息，说不定哪天就用上了。」",
            "「那桌的客人给了小费，算你的。」",
            "「修仙界的人喝茶，喝的是气氛，你懂吗？」",
        ],
    },
    {
        "id": "mine_labor",
        "name": "矿场苦力",
        "tier": 2,
        "speaker": "矿场监工",
        "desc": "在矿场挖掘灵石，体力消耗极大。",
        "req": {"realm_min": "炼气期5层", "physique": 5},
        "reward": {"spirit_stones": (80, 180), "items": [("铜矿石", 0.5), ("铁矿石", 0.4)]},
        "dialogues": [
            "「体魄不够的早就被压垮了，道友还算结实。」",
            "「矿脉深处有时候能挖到品质不错的灵石，运气好的话……」",
            "「今天矿洞有点不稳，小心点，别被压了。」",
            "「干了这么多年，我见过不少修士在这里攒够了突破的灵石。」",
        ],
    },
    {
        "id": "herb_garden",
        "name": "药圃除草",
        "tier": 2,
        "speaker": "老药农",
        "desc": "在药圃打理灵草，需要一定悟性辨别药材。",
        "req": {"comprehension": 5},
        "reward": {"spirit_stones": (60, 140), "items": [("灵芝草", 0.5), ("碧灵花", 0.3), ("九节菖蒲", 0.3)]},
        "dialogues": [
            "「这株是灵芝，那株是毒草，分不清楚的别乱碰。」",
            "「悟性好的人做这活儿事半功倍，你还不错。」",
            "「药圃里偶尔会长出野生灵草，发现了可以带走。」",
            "「老药农说，和灵草说话它们长得更好，你信吗？」",
        ],
    },
    {
        "id": "night_guard",
        "name": "守夜护院",
        "tier": 2,
        "speaker": "府上管家",
        "desc": "为富户守夜，需有一定修为震慑宵小。",
        "req": {"realm_min": "筑基期1层"},
        "reward": {"spirit_stones": (100, 200), "reputation": (1, 3)},
        "dialogues": [
            "「筑基修士守夜，那些毛贼看见你就跑了，省心。」",
            "「昨夜有人鬼鬼祟祟在附近转，被你吓跑了，主家很满意。」",
            "「守夜无聊，但灵石不少，道友可以打坐修炼。」",
            "「主家说了，若有贼人闯入，可以动手，但别出人命。」",
        ],
    },
    {
        "id": "escort",
        "name": "镖局护镖",
        "tier": 3,
        "speaker": "镖局掌柜",
        "desc": "护送货物前往他城，有遭遇妖兽的风险，但报酬丰厚。",
        "req": {"realm_min": "结丹期初期"},
        "reward": {"spirit_stones": (200, 450), "reputation": (2, 5)},
        "risk": {"lifespan_loss": (1, 3), "chance": 0.25},
        "dialogues": [
            "「这趟去落云城，听说路上有妖兽出没，道友可要小心。」",
            "「镖局的规矩：货到付款，货没了你赔。」",
            "「结丹修士护镖，这趟稳了，掌柜放心多了。」",
            "「上次护镖的道友遇上了妖兽，受了点伤，但货保住了。」",
        ],
    },
    {
        "id": "dange_assistant",
        "name": "丹阁杂役",
        "tier": 3,
        "speaker": "丹阁长老",
        "desc": "在丹阁打杂，协助炼丹师整理药材，可积累炼丹经验。",
        "req": {"alchemy_level": 1, "city": "丹阁"},
        "reward": {"spirit_stones": (120, 250), "alchemy_exp": (5, 15)},
        "dialogues": [
            "「一品炼丹师来打杂，长老说你有慧根，好好学。」",
            "「整理药材看似简单，实则大有学问，你慢慢体会。」",
            "「今天有位高品炼丹师开炉，你在旁边看着，别乱动。」",
            "「丹阁的杂役做好了，说不定哪天长老收你为徒。」",
        ],
    },
    {
        "id": "forge_apprentice",
        "name": "铸造铺学徒",
        "tier": 3,
        "speaker": "铸造师傅",
        "desc": "在铸造铺打下手，需要强健的根骨承受高温。",
        "req": {"bone": 7},
        "reward": {"spirit_stones": (100, 220), "items": [("铁矿石", 0.6), ("精铁矿", 0.3)]},
        "dialogues": [
            "「根骨不够的早就被炉火烤跑了，你还算耐得住。」",
            "「铸造的秘诀在于感受金属的纹理，用心去感受。」",
            "「今天打了一把不错的剑胚，师傅心情好，多给你一把矿料。」",
            "「学徒嘛，先从烧炉子开始，三年后再说其他。」",
        ],
    },
    {
        "id": "sect_guest",
        "name": "宗门客卿",
        "tier": 4,
        "speaker": "宗门执事",
        "desc": "以客卿身份为宗门办事，需有宗门背景与足够修为。",
        "req": {"realm_min": "元婴期初期", "has_sect": True},
        "reward": {"spirit_stones": (400, 800), "reputation": (5, 10)},
        "dialogues": [
            "「元婴修士屈尊为客卿，宗门上下都很重视。」",
            "「此次任务不难，但需要你的名望压场，懂吗？」",
            "「宗门给的报酬不算多，但人脉是无价的。」",
            "「长老说了，若你表现出色，可以考虑正式入门。」",
        ],
    },
    {
        "id": "storyteller",
        "name": "说书先生",
        "tier": 4,
        "speaker": "茶馆老板",
        "desc": "在茶馆说书，讲述修仙界的奇闻异事，需要极高声望。",
        "req": {"reputation": 500},
        "reward": {"spirit_stones": (200, 400), "reputation": (8, 15)},
        "dialogues": [
            "「道友见多识广，今日讲一段，茶馆包场！」",
            "「台下坐的都是修士，故事要够精彩，不然砸场子。」",
            "「讲到精彩处，有人往台上扔灵石，都是你的。」",
            "「说书先生的嘴，半真半假，但听者都信。」",
        ],
    },
    {
        "id": "forge_master_assistant",
        "name": "炼器助手",
        "tier": 4,
        "speaker": "炼器大师",
        "desc": "协助炼器大师完成高阶法器，需要极强的根骨与结丹修为。",
        "req": {"realm_min": "结丹期初期", "bone": 10},
        "reward": {"spirit_stones": (300, 600), "items": [("灵铁矿", 0.7), ("秘银矿", 0.3)]},
        "dialogues": [
            "「结丹修士，根骨又强，正是我需要的助手。」",
            "「今天炼的是地阶法器，你负责稳住炉温，不能有丝毫偏差。」",
            "「炼器失败了，材料没了，但经验是你的。」",
            "「大师说你有炼器天赋，可惜走了修炼这条路。」",
        ],
    },
    {
        "id": "dange_senior",
        "name": "丹阁座上宾",
        "tier": 5,
        "speaker": "丹阁首席长老",
        "desc": "以高品炼丹师身份坐镇丹阁，指导后辈，报酬极为丰厚。",
        "req": {"alchemy_level": 5, "city": "丹阁"},
        "reward": {"spirit_stones": (800, 1500), "alchemy_exp": (20, 40)},
        "dialogues": [
            "「五品炼丹师驾临，丹阁蓬荜生辉！」",
            "「长老请您上座，今日有几位弟子需要您指点迷津。」",
            "「您炼的丹，丹阁愿意以市价两倍收购。」",
            "「传说中的炼丹宗师，今日终于得见，幸甚。」",
        ],
    },
    {
        "id": "sect_elder_advisor",
        "name": "宗门长老顾问",
        "tier": 5,
        "speaker": "宗门大长老",
        "desc": "化神修士坐镇宗门，以顾问身份参与宗门决策。",
        "req": {"realm_min": "化神期初期", "has_sect": True},
        "reward": {"spirit_stones": (1200, 2500), "reputation": (15, 30)},
        "dialogues": [
            "「阁下修为已至化神，老夫有一事相求……」",
            "「宗门近来多事，需要您这等高人坐镇。」",
            "「顾问之位，宗门上下皆服，报酬自然不薄。」",
            "「化神境界，天下间已是凤毛麟角，宗门以您为荣。」",
        ],
    },
    {
        "id": "secret_guide",
        "name": "秘境向导",
        "tier": 5,
        "speaker": "雇主",
        "desc": "引导修士进入秘境，需要丰富的探索经验。",
        "req": {"reputation": 800, "realm_min": "元婴期初期"},
        "reward": {"spirit_stones": (600, 1200), "items": [("玄铁矿", 0.5), ("陨铁矿", 0.4)]},
        "dialogues": [
            "「听说道友走遍了天下秘地，正需要您这样的向导。」",
            "「秘境里的机关我都摸透了，跟着我走，保你平安。」",
            "「上次带进去的修士，出来时境界提升了一层，都说是我的功劳。」",
            "「向导的规矩：进去之前说好分成，出来之后不认账的，下次别来。」",
        ],
    },
]

COOLDOWN_SECONDS = 1800

JOB_DAILY_LIMIT = 3


def get_available_jobs(player: dict) -> list[dict]:
    available = []
    for job in JOBS:
        if _check_req(player, job["req"]):
            available.append(job)
    return available


def _check_req(player: dict, req: dict) -> bool:
    if not req:
        return True
    if "realm_min" in req:
        if get_realm_index(player.get("realm", "")) < get_realm_index(req["realm_min"]):
            return False
    for stat in ("physique", "bone", "comprehension", "soul", "fortune", "reputation", "alchemy_level"):
        if stat in req and player.get(stat, 0) < req[stat]:
            return False
    if req.get("has_sect") and not player.get("sect"):
        return False
    if "city" in req and player.get("current_city") != req["city"]:
        return False
    return True


def get_locked_jobs(player: dict) -> list[dict]:
    locked = []
    for job in JOBS:
        if not _check_req(player, job["req"]):
            locked.append(job)
    return locked


def _req_desc(req: dict) -> str:
    parts = []
    if "realm_min" in req:
        parts.append(f"境界≥{req['realm_min']}")
    if "physique" in req:
        parts.append(f"体魄≥{req['physique']}")
    if "bone" in req:
        parts.append(f"根骨≥{req['bone']}")
    if "comprehension" in req:
        parts.append(f"悟性≥{req['comprehension']}")
    if "soul" in req:
        parts.append(f"神识≥{req['soul']}")
    if "reputation" in req:
        parts.append(f"声望≥{req['reputation']}")
    if "alchemy_level" in req:
        parts.append(f"炼丹≥{req['alchemy_level']}品")
    if req.get("has_sect"):
        parts.append("已加入宗门")
    if "city" in req:
        parts.append(f"需在{req['city']}")
    return "、".join(parts) if parts else "无"


def do_job(player: dict, job: dict) -> dict:
    from utils.db import get_conn, add_item
    import time

    uid = player["discord_id"]
    now = time.time()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT job_cooldown_until, job_daily_count, job_daily_reset FROM players WHERE discord_id = ?",
            (uid,)
        ).fetchone()

    if row:
        cooldown_until = row["job_cooldown_until"] or 0
        daily_count = row["job_daily_count"] or 0
        daily_reset = row["job_daily_reset"] or 0

        if now < cooldown_until:
            remaining = int(cooldown_until - now)
            return {"ok": False, "reason": f"打工冷却中，还需 **{remaining // 60} 分 {remaining % 60} 秒**。"}

        reset_date = time.gmtime(daily_reset)
        now_date = time.gmtime(now)
        if (now_date.tm_year, now_date.tm_yday) != (reset_date.tm_year, reset_date.tm_yday):
            daily_count = 0

        if daily_count >= JOB_DAILY_LIMIT:
            return {"ok": False, "reason": f"今日打工次数已达上限（{JOB_DAILY_LIMIT}次），明日再来。"}

    stones_min, stones_max = job["reward"]["spirit_stones"]
    stones = random.randint(stones_min, stones_max)
    rep_gain = 0
    alchemy_exp_gain = 0
    items_gained = []

    if "reputation" in job["reward"]:
        rep_min, rep_max = job["reward"]["reputation"]
        rep_gain = random.randint(rep_min, rep_max)

    if "alchemy_exp" in job["reward"]:
        exp_min, exp_max = job["reward"]["alchemy_exp"]
        alchemy_exp_gain = random.randint(exp_min, exp_max)

    if "items" in job["reward"]:
        for item_name, chance in job["reward"]["items"]:
            if random.random() < chance:
                add_item(uid, item_name, 1)
                items_gained.append(item_name)

    risk_triggered = False
    lifespan_loss = 0
    if "risk" in job:
        if random.random() < job["risk"]["chance"]:
            risk_triggered = True
            loss_min, loss_max = job["risk"]["lifespan_loss"]
            lifespan_loss = random.randint(loss_min, loss_max)

    with get_conn() as conn:
        updates = [
            "spirit_stones = spirit_stones + ?",
            "job_cooldown_until = ?",
            "job_daily_count = COALESCE(job_daily_count, 0) + 1",
            "job_daily_reset = ?",
        ]
        vals = [stones, now + COOLDOWN_SECONDS, now]
        if rep_gain:
            updates.append("reputation = reputation + ?")
            vals.append(rep_gain)
        if alchemy_exp_gain:
            updates.append("alchemy_exp = alchemy_exp + ?")
            vals.append(alchemy_exp_gain)
        if risk_triggered and lifespan_loss:
            updates.append("lifespan = MAX(1, lifespan - ?)")
            vals.append(lifespan_loss)
        vals.append(uid)
        conn.execute(f"UPDATE players SET {', '.join(updates)} WHERE discord_id = ?", vals)
        conn.commit()

    dialogue = random.choice(job["dialogues"])

    return {
        "ok": True,
        "job_name": job["name"],
        "speaker": job.get("speaker", "路人"),
        "dialogue": dialogue,
        "spirit_stones": stones,
        "reputation": rep_gain,
        "alchemy_exp": alchemy_exp_gain,
        "items": items_gained,
        "risk_triggered": risk_triggered,
        "lifespan_loss": lifespan_loss,
    }
