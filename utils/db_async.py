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
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_active: Mapped[float] = mapped_column(Float, nullable=False)
    cultivating_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    cultivating_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_dead: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
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
