import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, Boolean, Text

DB_PATH = os.getenv("DB_PATH", "game.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


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
    cultivation: Mapped[int] = mapped_column(Integer, default=0)
    realm: Mapped[str] = mapped_column(String, default="炼气期一层")
    spirit_stones: Mapped[int] = mapped_column(Integer, default=0)
    reputation: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_active: Mapped[float] = mapped_column(Float, nullable=False)
    cultivating_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    cultivating_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_dead: Mapped[bool] = mapped_column(Boolean, default=False)
    rebirth_count: Mapped[int] = mapped_column(Integer, default=0)
    is_virgin: Mapped[bool] = mapped_column(Boolean, default=True)
    sect: Mapped[str | None] = mapped_column(String, nullable=True)
    sect_rank: Mapped[str | None] = mapped_column(String, nullable=True)
    last_dual_cultivate: Mapped[float | None] = mapped_column(Float, nullable=True)
    dual_partner_id: Mapped[str | None] = mapped_column(String, nullable=True)
    techniques: Mapped[str] = mapped_column(Text, default="[]")
    cultivation_overflow: Mapped[int] = mapped_column(Integer, default=0)
    current_city: Mapped[str] = mapped_column(String, default="灵虚城")
    explore_count: Mapped[int] = mapped_column(Integer, default=0)
    explore_reset_year: Mapped[float] = mapped_column(Float, default=0)
    cave: Mapped[str | None] = mapped_column(String, nullable=True)
    discovered_sects: Mapped[str] = mapped_column(Text, default="[]")
    escape_rate: Mapped[int] = mapped_column(Integer, default=0)
    has_bahongchen: Mapped[bool] = mapped_column(Boolean, default=False)
    active_quest: Mapped[str | None] = mapped_column(String, nullable=True)
    quest_due: Mapped[float | None] = mapped_column(Float, nullable=True)
    party_id: Mapped[str | None] = mapped_column(String, nullable=True)
    gathering_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    gathering_type: Mapped[str | None] = mapped_column(String, nullable=True)
    pill_buff_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    alchemy_level: Mapped[int] = mapped_column(Integer, default=0)
    alchemy_exp: Mapped[int] = mapped_column(Integer, default=0)
    alchemy_daily_count: Mapped[int] = mapped_column(Integer, default=0)
    alchemy_daily_reset: Mapped[float] = mapped_column(Float, default=0)
    exam_attempts_left: Mapped[int] = mapped_column(Integer, default=0)
    active_buffs: Mapped[str] = mapped_column(Text, default="{}")
    gathering_bonus: Mapped[float] = mapped_column(Float, default=0)
    job_cooldown_until: Mapped[float] = mapped_column(Float, nullable=True)
    job_daily_count: Mapped[int] = mapped_column(Integer, default=0)
    job_daily_reset: Mapped[float] = mapped_column(Float, default=0)
    gamble_daily_count: Mapped[int] = mapped_column(Integer, default=0)
    gamble_daily_reset: Mapped[float] = mapped_column(Float, default=0)
    checkin_last_date: Mapped[str | None] = mapped_column(String, nullable=True)
    forging_level: Mapped[int] = mapped_column(Integer, default=0)
    forging_exp: Mapped[int] = mapped_column(Integer, default=0)
    forging_daily_count: Mapped[int] = mapped_column(Integer, default=0)
    forging_daily_reset: Mapped[float] = mapped_column(Float, default=0)
    forging_mastery_count: Mapped[int] = mapped_column(Integer, default=0)
    roulette_daily_count: Mapped[int] = mapped_column(Integer, default=0)
    roulette_daily_reset: Mapped[float] = mapped_column(Float, default=0)


class Inventory(Base):
    __tablename__ = "inventory"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    item_id: Mapped[str] = mapped_column(String, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)


class Equipment(Base):
    __tablename__ = "equipment"

    equip_id: Mapped[str] = mapped_column(String, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slot: Mapped[str] = mapped_column(String, nullable=False)
    quality: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[int] = mapped_column(Integer, default=0)
    tier_req: Mapped[int] = mapped_column(Integer, default=0)
    stats: Mapped[str] = mapped_column(Text, default="{}")
    flavor: Mapped[str] = mapped_column(Text, default="")
    equipped: Mapped[bool] = mapped_column(Boolean, default=False)


class Residence(Base):
    __tablename__ = "residences"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    city: Mapped[str] = mapped_column(String, primary_key=True)
    purchased_at: Mapped[float] = mapped_column(Float, nullable=False)


class WanbaoAuction(Base):
    __tablename__ = "wanbao_auctions"

    auction_id: Mapped[str] = mapped_column(String, primary_key=True)
    date_str: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending")
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    ends_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_lot: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[str] = mapped_column(Text, default="{}")


class WanbaoLot(Base):
    __tablename__ = "wanbao_lots"

    lot_id: Mapped[str] = mapped_column(String, primary_key=True)
    auction_id: Mapped[str] = mapped_column(String, nullable=False)
    lot_index: Mapped[int] = mapped_column(Integer, nullable=False)
    seller_id: Mapped[str | None] = mapped_column(String, nullable=True)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    item_type: Mapped[str] = mapped_column(String, default="item")
    start_price: Mapped[int] = mapped_column(Integer, nullable=False)
    current_bid: Mapped[int] = mapped_column(Integer, default=0)
    bidder_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    frozen_ids: Mapped[str] = mapped_column(Text, default="[]")
    eq_data: Mapped[str | None] = mapped_column(Text, nullable=True)


class WanbaoFrozen(Base):
    __tablename__ = "wanbao_frozen"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    auction_id: Mapped[str] = mapped_column(String, primary_key=True)
    amount: Mapped[int] = mapped_column(Integer, default=0)


class AlchemyMastery(Base):
    __tablename__ = "alchemy_mastery"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    pill_name: Mapped[str] = mapped_column(String, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class KnownRecipe(Base):
    __tablename__ = "known_recipes"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    recipe_id: Mapped[str] = mapped_column(String, primary_key=True)
    aux_choices: Mapped[str] = mapped_column(String, default="[]")


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
    status: Mapped[str] = mapped_column(String, default="active")
    data: Mapped[str] = mapped_column(Text, default="{}")


class PublicEventParticipant(Base):
    __tablename__ = "public_event_participants"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    activity: Mapped[str | None] = mapped_column(String, primary_key=True, nullable=True)
    joined_at: Mapped[float] = mapped_column(Float, nullable=False)
    contribution: Mapped[int] = mapped_column(Integer, default=0)


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    discord_id: Mapped[str] = mapped_column(String, primary_key=True)
    demand_balance: Mapped[int] = mapped_column(Integer, default=0)
    demand_deposited_at: Mapped[float] = mapped_column(Float, default=0)


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
    status: Mapped[str] = mapped_column(String, default="active")


class MarketListing(Base):
    __tablename__ = "market_listings"

    listing_id: Mapped[str] = mapped_column(String, primary_key=True)
    seller_id: Mapped[str] = mapped_column(String, nullable=False)
    item_type: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    listed_at: Mapped[float] = mapped_column(Float, nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active")
    eq_data: Mapped[str | None] = mapped_column(Text, nullable=True)
