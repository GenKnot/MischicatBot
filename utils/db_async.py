"""异步数据库引擎与 ORM 模型。

两条约定，改之前先看 .gk/CONVENTIONS.md：

1. 不要给引擎加全局 BEGIN IMMEDIATE。看着能一劳永逸解决并发丢更新，
   但项目里十来处「外层 session 开着、内层再开一个」的写法会当场自锁。
   并发正确性靠 utils/atomic.py 把条件写进 UPDATE。
2. 有 default= 的列必须一起给 server_default=，否则 create_all 建出来的
   新库没有 SQL 默认值，裸 INSERT 会撞 NOT NULL。
"""

from sqlalchemy import String, Integer, Float, Boolean, Text, event, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from utils.config import DB_PATH

DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

# 抢不到写锁时的等待上限（毫秒）。SQLite 单写者，冲突靠等待化解而非报错。
SQLITE_BUSY_TIMEOUT_MS = 5000

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_on_connect(dbapi_conn, _record):
    """新连接建立时设好 PRAGMA。须在事务之外执行（WAL 无法在事务内切换）。

    注意：这里刻意不动 `isolation_level`。保留驱动默认的隐式事务行为，
    嵌套 session 的调用点才不会自锁，理由见模块文档。
    """
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    cur.execute("PRAGMA synchronous=NORMAL")  # WAL 下的安全/性能平衡点
    cur.close()


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    gender: Mapped[str] = mapped_column(String, nullable=False)
    spirit_root: Mapped[str] = mapped_column(String, nullable=False)
    spirit_root_type: Mapped[str] = mapped_column(String, nullable=False)
    comprehension: Mapped[int] = mapped_column(Integer, nullable=False)
    physique: Mapped[int] = mapped_column(Integer, nullable=False)
    fortune: Mapped[int] = mapped_column(Integer, nullable=False)
    bone: Mapped[int] = mapped_column(Integer, nullable=False)
    soul: Mapped[int] = mapped_column(Integer, nullable=False)
    lifespan: Mapped[int] = mapped_column(Integer, nullable=False)
    lifespan_max: Mapped[int] = mapped_column(Integer, nullable=False)
    cultivation: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # 必须是 REALMS 里的字面量。原先是"炼气期一层"，不在表里，
    # get_realm_index() 会兜底返回 0。
    realm: Mapped[str] = mapped_column(String, default="炼气期1层", server_default=text("'炼气期1层'"))
    spirit_stones: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    reputation: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # 知名度（和 reputation 道德声望分开）：决定一件事传多远，见 utils/fame.py
    fame: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_active: Mapped[float] = mapped_column(Float, nullable=False)
    cultivating_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    cultivating_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_dead: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # 机器人修士（U1「江湖百态」）。discord_id 以 `bot_` 开头，不是真实 Discord 用户：
    # 发私信、通知、公共事件报名等真人专属逻辑必须排除（见 utils/bots.py）
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    rebirth_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    is_virgin: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    sect: Mapped[str | None] = mapped_column(String, nullable=True)
    sect_rank: Mapped[str | None] = mapped_column(String, nullable=True)
    last_dual_cultivate: Mapped[float | None] = mapped_column(Float, nullable=True)
    dual_partner_id: Mapped[str | None] = mapped_column(String, nullable=True)
    techniques: Mapped[str] = mapped_column(Text, default="[]", server_default=text("'[]'"))
    cultivation_overflow: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    current_city: Mapped[str] = mapped_column(String, default="灵虚城", server_default=text("'灵虚城'"))
    explore_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    explore_reset_year: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    cave: Mapped[str | None] = mapped_column(String, nullable=True)
    discovered_sects: Mapped[str] = mapped_column(Text, default="[]", server_default=text("'[]'"))
    escape_rate: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    has_bahongchen: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    active_quest: Mapped[str | None] = mapped_column(String, nullable=True)
    quest_due: Mapped[float | None] = mapped_column(Float, nullable=True)
    party_id: Mapped[str | None] = mapped_column(String, nullable=True)
    gathering_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    gathering_type: Mapped[str | None] = mapped_column(String, nullable=True)
    pill_buff_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    alchemy_level: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    alchemy_exp: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    alchemy_daily_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    alchemy_daily_reset: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    exam_attempts_left: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    active_buffs: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))
    gathering_bonus: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    job_cooldown_until: Mapped[float] = mapped_column(Float, nullable=True)
    job_daily_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    job_daily_reset: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    gamble_daily_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    gamble_daily_reset: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    checkin_last_date: Mapped[str | None] = mapped_column(String, nullable=True)
    forging_level: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    forging_exp: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    forging_daily_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    forging_daily_reset: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    forging_mastery_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # 炼器考核是否已缴费。原先看"背包里有没有考核材料"，玩家自己挖到铜矿石
    # 就会被误判。
    forging_exam_paid: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    roulette_daily_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    roulette_daily_reset: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))


class Inventory(Base):
    __tablename__ = "inventory"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(String, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))


class Equipment(Base):
    __tablename__ = "equipment"

    equip_id: Mapped[str] = mapped_column(String, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slot: Mapped[str] = mapped_column(String, nullable=False)
    quality: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    tier_req: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    stats: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))
    flavor: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    equipped: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))


class Residence(Base):
    __tablename__ = "residences"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    city: Mapped[str] = mapped_column(String, primary_key=True)
    purchased_at: Mapped[float] = mapped_column(Float, nullable=False)


class WanbaoAuction(Base):
    __tablename__ = "wanbao_auctions"

    auction_id: Mapped[str] = mapped_column(String, primary_key=True)
    date_str: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", server_default=text("'pending'"))
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    ends_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_lot: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    data: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))


class WanbaoLot(Base):
    __tablename__ = "wanbao_lots"

    lot_id: Mapped[str] = mapped_column(String, primary_key=True)
    auction_id: Mapped[str] = mapped_column(String, nullable=False)
    lot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    seller_id: Mapped[str | None] = mapped_column(String, nullable=True)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    item_type: Mapped[str] = mapped_column(String, default="item", server_default=text("'item'"))
    start_price: Mapped[int] = mapped_column(Integer, nullable=False)
    current_bid: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    bidder_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending", server_default=text("'pending'"))
    frozen_ids: Mapped[str] = mapped_column(Text, default="[]", server_default=text("'[]'"))
    eq_data: Mapped[str | None] = mapped_column(Text, nullable=True)


class WanbaoFrozen(Base):
    __tablename__ = "wanbao_frozen"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    auction_id: Mapped[str] = mapped_column(String, primary_key=True)
    amount: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class AlchemyMastery(Base):
    __tablename__ = "alchemy_mastery"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    pill_name: Mapped[str] = mapped_column(String, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class KnownRecipe(Base):
    __tablename__ = "known_recipes"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    recipe_id: Mapped[str] = mapped_column(String, primary_key=True)
    aux_choices: Mapped[str] = mapped_column(String, default="[]", server_default=text("'[]'"))


class Party(Base):
    __tablename__ = "parties"

    party_id: Mapped[str] = mapped_column(String, primary_key=True)
    leader_id: Mapped[str] = mapped_column(String, nullable=False)
    city: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)


class PublicEvent(Base):
    __tablename__ = "public_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[float] = mapped_column(Float, nullable=False)
    ends_at: Mapped[float] = mapped_column(Float, nullable=False)
    channel_id: Mapped[str | None] = mapped_column(String, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="active", server_default=text("'active'"))
    data: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))


class PublicEventParticipant(Base):
    __tablename__ = "public_event_participants"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    # 主键列不能可空：SQLite 里 NULL != NULL，activity 为 NULL 时能插进重复的
    # 参与记录。用空串表示"没有具体活动"。
    activity: Mapped[str] = mapped_column(
        String, primary_key=True, nullable=False, default="", server_default=text("''"))
    joined_at: Mapped[float] = mapped_column(Float, nullable=False)
    contribution: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    demand_balance: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    demand_deposited_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))


class BankDeposit(Base):
    __tablename__ = "bank_deposits"

    deposit_id: Mapped[str] = mapped_column(String, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String, nullable=False)
    principal: Mapped[int] = mapped_column(Integer, nullable=False)
    term_years: Mapped[int] = mapped_column(Integer, nullable=False)
    rate: Mapped[float] = mapped_column(Float, nullable=False)
    interest: Mapped[int] = mapped_column(Integer, nullable=False)
    deposited_at: Mapped[float] = mapped_column(Float, nullable=False)
    due_at: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active", server_default=text("'active'"))


class BotPersonality(Base):
    """机器人的性格与偏好（U1「江湖百态」）。一个机器人一行，随机生成后基本不变。

    性格数值 0~100：善意（影响肯不肯组队 / 双修）、贪婪、好胜、健谈。
    喜好 / 厌恶存成 JSON：{"categories": ["丹药", ...], "items": ["筑基丹", ...]}，
    送礼时按它加减好感（见 utils/bot_social.py）。
    """
    __tablename__ = "bot_personality"

    bot_id: Mapped[str] = mapped_column(String, primary_key=True)
    archetype: Mapped[str] = mapped_column(String, nullable=False)
    kindness: Mapped[int] = mapped_column(Integer, default=50, server_default=text("50"))
    greed: Mapped[int] = mapped_column(Integer, default=50, server_default=text("50"))
    pride: Mapped[int] = mapped_column(Integer, default=50, server_default=text("50"))
    talk: Mapped[int] = mapped_column(Integer, default=50, server_default=text("50"))
    likes: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))
    dislikes: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))
    tier: Mapped[str] = mapped_column(String, default="正常", server_default=text("'正常'"))   # 炮灰 / 正常 / 天骄
    settled_day: Mapped[str] = mapped_column(String, default="", server_default=text("''"))    # 最后一次每日结算的日期
    home_city: Mapped[str] = mapped_column(String, default="", server_default=text("''"))      # 常驻城市（去秘地历练后回这里）
    epithet: Mapped[str] = mapped_column(String, default="", server_default=text("''"))        # 天骄的称号
    backstory: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))        # 天骄的一句话背景
    capped_days: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))     # 连续顶在天花板上的天数
    traits: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))           # 说话特质（JSON，见 utils/bot_traits.py）
    profile: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))          # 行为画像（JSON，见 utils/bot_profile.py）


class BotTie(Base):
    """人与人之间的关系（U1·江湖百态 P2）：一对人一行（a_id < b_id），机器人 × 机器人，或真人 × 机器人。

    kind：相识 / 朋友 / 结拜 / 同门 / 仇敌；strength 0~100；bond_id 是结拜 / 同门的『团体』编号（多人结拜共用一个）；
    note 记当初怎么认识的（同城 / 组队 / 公共事件 / 出生）。
    """
    __tablename__ = "bot_ties"

    a_id: Mapped[str] = mapped_column(String, primary_key=True)
    b_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="相识", server_default=text("'相识'"))
    strength: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    since: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    last_event: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    bond_id: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    note: Mapped[str] = mapped_column(String, default="", server_default=text("''"))


class BotGrudge(Base):
    """仇恨账本（U1·江湖百态 P3）：holder 恨 target，为了 victim（被冒犯的人；holder 自己就是受害者时 victim == holder）。

    reason 是写给玩家看的具体原因（『王某杀害了你的结拜兄弟李某』）；severity 0~100 累加；
    state：active（蹲守中）/ dormant（窗口到期、没再续，但仇恨还在，新事件或相遇会重新激活）；
    known_at：holder 得知此事的时间（受害者没名气时朋友要过一阵才知道）；window_until：蹲守窗口结束时间；
    style：直接 / 隐忍 / 等待时机（性格决定的复仇方式）；stubborn：少数『执着』的人，窗口特别长。
    """
    __tablename__ = "bot_grudges"

    holder_id: Mapped[str] = mapped_column(String, primary_key=True)
    target_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    victim_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    reason: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    severity: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    events: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    state: Mapped[str] = mapped_column(String, default="active", server_default=text("'active'"))
    style: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    stubborn: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    created_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    known_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    window_until: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    renewals: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_ambush_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    last_apology: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))


class PlayerEnemy(Base):
    """玩家前世的仇人（转世 / 重建角色后还在）：玩家记得是谁杀了自己，机器人却不认识新的他。"""
    __tablename__ = "player_enemies"

    player_id: Mapped[str] = mapped_column(String, primary_key=True)
    enemy_id: Mapped[str] = mapped_column(String, primary_key=True)
    life: Mapped[int] = mapped_column(Integer, primary_key=True, default=1, server_default=text("1"))
    enemy_name: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    reason: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    since: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))


class BotEncounter(Base):
    """一次拦路遭遇（U1·江湖百态 P4）。stage：choose（等玩家选逃跑 / 迎战，超时算逃跑）→ bargain（玩家败了，交涉中，超时算拒绝）→ done。
    状态存库，bot 重启后由后台循环收尾，不会让玩家卡在半路。"""
    __tablename__ = "bot_encounters"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    target_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    leader_id: Mapped[str] = mapped_column(String, nullable=False)
    companions: Mapped[str] = mapped_column(Text, default="[]", server_default=text("'[]'"))
    rescuer_id: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    victim_id: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    reason: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    severity: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    context: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    stage: Mapped[str] = mapped_column(String, default="choose", server_default=text("'choose'"))
    created_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    expires_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    channel_id: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    message_id: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    price: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    result: Mapped[str] = mapped_column(String, default="", server_default=text("''"))


class PlayerAmbush(Base):
    """玩家最近一次被拦路的时间（全局冷却）和保护期（被废 / 被杀之后一段时间不再被拦）。"""
    __tablename__ = "player_ambush"

    player_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    protect_until: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class ChatterState(Base):
    """玩家收到机器人主动搭话的计数（每天上限）和屏蔽开关（U1·江湖百态 P5）。屏蔽只管搭话消息，不管仇恨 / 拦路。"""
    __tablename__ = "chatter_state"

    player_id: Mapped[str] = mapped_column(String, primary_key=True)
    day: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    muted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))


class ChatterPair(Base):
    """某机器人最近一次主动找某玩家说话的时间（同一对之间的冷却）。"""
    __tablename__ = "chatter_pair"

    player_id: Mapped[str] = mapped_column(String, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String, primary_key=True)
    last_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))


class ChatterQueue(Base):
    """延迟发送的搭话：突破道贺、公共事件前后、冲突后放话。到点由 cogs/chatter.py 的后台循环发（台词在发送时才生成）。"""
    __tablename__ = "chatter_queue"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    player_id: Mapped[str] = mapped_column(String, nullable=False)
    speaker_id: Mapped[str] = mapped_column(String, nullable=False)
    scene: Mapped[str] = mapped_column(String, nullable=False)
    fmt: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))
    due_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"), index=True)
    sent_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    outcome: Mapped[str] = mapped_column(String, default="", server_default=text("''"))


class BotRequest(Base):
    """机器人对熟人（真人）提的请求 / 委托：借灵石、借物品、送信、陪着采集……（数据驱动，模板在 data/bot_requests.json）。

    state：offered（刚提出，等玩家答复）→ active（答应了：借出去的钱 / 物品等着还，送信 / 陪采集等着办）→ done / defaulted（赖账）/ failed（没办成）/
    declined / expired。params 随模板不同：amount、item、target_bot、city、what……；due_at：到期时间（还钱 / 办完的期限）。
    """
    __tablename__ = "bot_requests"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String, nullable=False)
    player_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    template: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, default="offered", server_default=text("'offered'"))
    params: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))
    created_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    due_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    updated_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    note: Mapped[str] = mapped_column(String, default="", server_default=text("''"))


class BotMissing(Base):
    """机器人在打听失踪的朋友（U1·江湖百态）：没名气的机器人被杀，朋友不会立刻知道是谁干的，要自己去查。

    progress 0~100，到 100 就查清了（seeker 记仇）。每天自己涨一点（谨慎的涨得快）；碰到玩家会问『见过某某吗』，玩家的回答让它更接近真相或走错路；
    asked：{玩家ID: 上次问的时间}。state：active / resolved / gave_up。"""
    __tablename__ = "bot_missing"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    seeker_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    missing_id: Mapped[str] = mapped_column(String, nullable=False)
    missing_name: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    culprit_id: Mapped[str] = mapped_column(String, nullable=False)
    culprit_name: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    kind: Mapped[str] = mapped_column(String, default="kill", server_default=text("'kill'"))
    rel: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    severity: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    reason: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    city: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    started_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    progress: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    state: Mapped[str] = mapped_column(String, default="active", server_default=text("'active'"))
    asked: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))


class BotWorldState(Base):
    """机器人世界的全局状态（key/value）：目标人数 `target`、最后补员日 `refill_day`。"""
    __tablename__ = "bot_world_state"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False, default="", server_default=text("''"))


class Rumor(Base):
    """江湖传闻（茶馆可查、频道按分值挑最精彩的一条广播）。保留 7 天。见 utils/rumors.py。"""
    __tablename__ = "rumors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    subject_id: Mapped[str] = mapped_column(String, nullable=False)
    subject_name: Mapped[str] = mapped_column(String, nullable=False)
    is_human: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    negative: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    content: Mapped[str] = mapped_column(Text, nullable=False)       # 传闻正文（不叫 text：会盖掉 sqlalchemy.text）
    city: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    broadcast_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))   # 0 = 没广播过


class RumorOptout(Base):
    """关闭了『我的事迹进传闻』的真人。"""
    __tablename__ = "rumor_optout"

    player_id: Mapped[str] = mapped_column(String, primary_key=True)


class BotMemory(Base):
    """机器人对某个真人的记忆（U1·关系记忆）：送过的礼物、聊天、被打劫、一起组队双修、被你攻击失败……

    一个 (真人, 机器人, 种类, 细节) 一行：count 次数，extra 补充（礼物的反应 / 打劫的灵石 / 上次见面的城市……），
    prev_at 是『上一次』的时间（用来说『好久不见』），last_at 是最近一次。机器人没了，记忆也跟着没了。"""
    __tablename__ = "bot_memories"

    player_id: Mapped[str] = mapped_column(String, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    detail: Mapped[str] = mapped_column(String, primary_key=True, default="", server_default=text("''"))
    count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    extra: Mapped[str] = mapped_column(String, default="", server_default=text("''"))
    first_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    prev_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    last_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))


class BotRaid(Base):
    """真人每天打劫 / 击杀机器人的次数（按日），用来限制每人每天的次数。"""
    __tablename__ = "bot_raids"

    player_id: Mapped[str] = mapped_column(String, primary_key=True)
    day: Mapped[str] = mapped_column(String, primary_key=True)
    robs: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    kills: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class BotRelation(Base):
    """真人 × 机器人的关系：好感度（-100~100）与当日互动计数。"""
    __tablename__ = "bot_relations"

    player_id: Mapped[str] = mapped_column(String, primary_key=True)
    bot_id: Mapped[str] = mapped_column(String, primary_key=True)
    favor: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_interact: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    day: Mapped[str] = mapped_column(String, default="", server_default=text("''"))      # 下面三个计数属于哪一天
    gifts_today: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    gift_gain_today: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    chatted_today: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class AdventureProgress(Base):
    __tablename__ = "adventure_progress"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    progress: Mapped[str] = mapped_column(Text, default="{}", server_default=text("'{}'"))
    updated_at: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))


class MarketListing(Base):
    __tablename__ = "market_listings"

    listing_id: Mapped[str] = mapped_column(String, primary_key=True)
    seller_id: Mapped[str] = mapped_column(String, nullable=False)
    item_type: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    listed_at: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active", server_default=text("'active'"))
    eq_data: Mapped[str | None] = mapped_column(Text, nullable=True)
