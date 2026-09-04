import sqlite3
import os

from utils.config import DB_PATH


def get_conn():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn):
    """遗留迁移。**已冻结，不要再往这里加东西。**

    从 alembic/versions/0001_baseline.py 之后，所有 schema 变更都写成
    alembic revision。这里留着只是为了让还没升级过的老库能补齐字段，
    等确认线上没有老库了就可以整个删掉。
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
    migrations = [
        ("rebirth_count",        "INTEGER NOT NULL DEFAULT 0"),
        ("is_virgin",            "INTEGER NOT NULL DEFAULT 1"),
        ("sect",                 "TEXT"),
        ("sect_rank",            "TEXT"),
        ("last_dual_cultivate",  "REAL"),
        ("dual_partner_id",      "TEXT"),
        ("techniques",           "TEXT NOT NULL DEFAULT '[]'"),
        ("cultivation_overflow", "INTEGER NOT NULL DEFAULT 0"),
        ("current_city",         "TEXT NOT NULL DEFAULT '灵虚城'"),
        ("explore_count",        "INTEGER NOT NULL DEFAULT 0"),
        ("explore_reset_year",   "REAL NOT NULL DEFAULT 0"),
        ("cave",                 "TEXT"),
        ("discovered_sects",     "TEXT NOT NULL DEFAULT '[]'"),
        ("escape_rate",          "INTEGER NOT NULL DEFAULT 0"),
        ("has_bahongchen",       "INTEGER NOT NULL DEFAULT 0"),
        ("active_quest",         "TEXT"),
        ("quest_due",            "REAL"),
        ("party_id",             "TEXT"),
        ("gathering_until",      "REAL"),
        ("gathering_type",       "TEXT"),
        ("pill_buff_until",      "REAL"),
        ("alchemy_level",        "INTEGER NOT NULL DEFAULT 0"),
        ("alchemy_exp",          "INTEGER NOT NULL DEFAULT 0"),
        ("alchemy_daily_count",  "INTEGER NOT NULL DEFAULT 0"),
        ("alchemy_daily_reset",  "REAL NOT NULL DEFAULT 0"),
        ("active_buffs",         "TEXT NOT NULL DEFAULT '{}'"),
        ("gathering_bonus",      "REAL NOT NULL DEFAULT 0"),
        ("job_cooldown_until",   "REAL"),
        ("job_daily_count",      "INTEGER NOT NULL DEFAULT 0"),
        ("job_daily_reset",      "REAL NOT NULL DEFAULT 0"),
        ("checkin_last_date",    "TEXT"),
        ("gamble_daily_count",   "INTEGER NOT NULL DEFAULT 0"),
        ("gamble_daily_reset",   "REAL NOT NULL DEFAULT 0"),
        ("forging_level",        "INTEGER NOT NULL DEFAULT 0"),
        ("forging_exp",          "INTEGER NOT NULL DEFAULT 0"),
        ("forging_daily_count",  "INTEGER NOT NULL DEFAULT 0"),
        ("forging_daily_reset",  "REAL NOT NULL DEFAULT 0"),
        ("forging_mastery_count","INTEGER NOT NULL DEFAULT 0"),
        ("roulette_daily_count", "INTEGER NOT NULL DEFAULT 0"),
        ("roulette_daily_reset", "REAL NOT NULL DEFAULT 0"),
        ("forging_exam_paid",     "INTEGER NOT NULL DEFAULT 0"),
    ]
    for col, definition in migrations:
        if col not in existing:
            conn.execute(f"ALTER TABLE players ADD COLUMN {col} {definition}")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS residences (
            discord_id  TEXT NOT NULL,
            city        TEXT NOT NULL,
            purchased_at REAL NOT NULL,
            PRIMARY KEY (discord_id, city)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parties (
            party_id    TEXT PRIMARY KEY,
            leader_id   TEXT NOT NULL,
            city        TEXT NOT NULL,
            created_at  REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            discord_id  TEXT NOT NULL,
            item_id     TEXT NOT NULL,
            quantity    INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (discord_id, item_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS public_events (
            event_id    TEXT PRIMARY KEY,
            event_type  TEXT NOT NULL,
            title       TEXT NOT NULL,
            started_at  REAL NOT NULL,
            ends_at     REAL NOT NULL,
            channel_id  TEXT,
            message_id  TEXT,
            status      TEXT NOT NULL DEFAULT 'active',
            data        TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS public_event_participants (
            event_id    TEXT NOT NULL,
            discord_id  TEXT NOT NULL,
            joined_at   REAL NOT NULL,
            contribution INTEGER NOT NULL DEFAULT 0,
            activity    TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (event_id, discord_id, activity)
        )
    """)
    existing_ep = {row[1] for row in conn.execute("PRAGMA table_info(public_event_participants)")}
    if "activity" not in existing_ep:
        conn.execute("ALTER TABLE public_event_participants ADD COLUMN activity TEXT")
    pk_info = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='public_event_participants'").fetchone()
    if pk_info and "activity" not in (pk_info["sql"] or "").split("PRIMARY KEY")[1]:
        conn.execute("ALTER TABLE public_event_participants RENAME TO public_event_participants_old")
        conn.execute("""
            CREATE TABLE public_event_participants (
                event_id     TEXT NOT NULL,
                discord_id   TEXT NOT NULL,
                joined_at    REAL NOT NULL,
                contribution INTEGER NOT NULL DEFAULT 0,
                activity     TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (event_id, discord_id, activity)
            )
        """)
        conn.execute("INSERT INTO public_event_participants SELECT event_id, discord_id, joined_at, contribution, activity FROM public_event_participants_old")
        conn.execute("DROP TABLE public_event_participants_old")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS equipment (
            equip_id    TEXT PRIMARY KEY,
            discord_id  TEXT NOT NULL,
            name        TEXT NOT NULL,
            slot        TEXT NOT NULL,
            quality     TEXT NOT NULL,
            tier        INTEGER NOT NULL DEFAULT 0,
            tier_req    INTEGER NOT NULL DEFAULT 0,
            stats       TEXT NOT NULL DEFAULT '{}',
            flavor      TEXT NOT NULL DEFAULT '',
            equipped    INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wanbao_auctions (
            auction_id   TEXT PRIMARY KEY,
            date_str     TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'pending',
            started_at   REAL,
            ends_at      REAL,
            current_lot  INTEGER NOT NULL DEFAULT 0,
            data         TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wanbao_lots (
            lot_id       TEXT PRIMARY KEY,
            auction_id   TEXT NOT NULL,
            lot_index    INTEGER NOT NULL,
            seller_id    TEXT,
            item_name    TEXT NOT NULL,
            quantity     INTEGER NOT NULL DEFAULT 1,
            item_type    TEXT NOT NULL DEFAULT 'item',
            start_price  INTEGER NOT NULL,
            current_bid  INTEGER NOT NULL DEFAULT 0,
            bidder_id    TEXT,
            status       TEXT NOT NULL DEFAULT 'pending',
            frozen_ids   TEXT NOT NULL DEFAULT '[]',
            eq_data      TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wanbao_frozen (
            discord_id   TEXT NOT NULL,
            auction_id   TEXT NOT NULL,
            amount       INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (discord_id, auction_id)
        )
    """)
    existing_wl = {row[1] for row in conn.execute("PRAGMA table_info(wanbao_lots)")}
    if "eq_data" not in existing_wl:
        conn.execute("ALTER TABLE wanbao_lots ADD COLUMN eq_data TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alchemy_mastery (
            discord_id  TEXT NOT NULL,
            pill_name   TEXT NOT NULL,
            count       INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (discord_id, pill_name)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS known_recipes (
            discord_id  TEXT NOT NULL,
            recipe_id   TEXT NOT NULL,
            PRIMARY KEY (discord_id, recipe_id)
        )
    """)
    existing_kr = {row[1] for row in conn.execute("PRAGMA table_info(known_recipes)")}
    if "aux_choices" not in existing_kr:
        conn.execute("ALTER TABLE known_recipes ADD COLUMN aux_choices TEXT DEFAULT '[]'")
    existing_p = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
    if "exam_attempts_left" not in existing_p:
        conn.execute("ALTER TABLE players ADD COLUMN exam_attempts_left INTEGER NOT NULL DEFAULT 0")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS adventure_progress (
            discord_id  TEXT PRIMARY KEY,
            progress    TEXT NOT NULL DEFAULT '{}',
            updated_at  REAL NOT NULL DEFAULT 0
        )
    """)
    # 一次性数据订正：早期新建的角色境界写成了"炼气期一层"（中文数字），
    # 不在 utils/realms.py::REALMS 里。幂等，跑多少次都一样。
    conn.execute("UPDATE players SET realm = '炼气期1层' WHERE realm = '炼气期一层'")

    conn.commit()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                discord_id   TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                gender       TEXT NOT NULL,
                spirit_root  TEXT NOT NULL,
                spirit_root_type TEXT NOT NULL,
                comprehension INTEGER NOT NULL,
                physique      INTEGER NOT NULL,
                fortune       INTEGER NOT NULL,
                bone          INTEGER NOT NULL,
                soul          INTEGER NOT NULL,
                lifespan      INTEGER NOT NULL,
                lifespan_max  INTEGER NOT NULL,
                cultivation   INTEGER NOT NULL DEFAULT 0,
                realm         TEXT NOT NULL DEFAULT '炼气期1层',
                spirit_stones INTEGER NOT NULL DEFAULT 0,
                reputation    INTEGER NOT NULL DEFAULT 0,
                created_at    REAL NOT NULL,
                last_active           REAL NOT NULL,
                cultivating_until     REAL,
                cultivating_years     INTEGER,
                is_dead               INTEGER NOT NULL DEFAULT 0,
                rebirth_count         INTEGER NOT NULL DEFAULT 0,
                is_virgin             INTEGER NOT NULL DEFAULT 1,
                sect                  TEXT,
                sect_rank             TEXT,
                last_dual_cultivate   REAL,
                dual_partner_id       TEXT,
                techniques            TEXT NOT NULL DEFAULT '[]',
                cultivation_overflow  INTEGER NOT NULL DEFAULT 0,
                current_city          TEXT NOT NULL DEFAULT '灵虚城',
                explore_count         INTEGER NOT NULL DEFAULT 0,
                explore_reset_year    REAL NOT NULL DEFAULT 0,
                escape_rate           INTEGER NOT NULL DEFAULT 0,
                has_bahongchen        INTEGER NOT NULL DEFAULT 0
            )
        """)
        _migrate(conn)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bank_accounts (
                discord_id          TEXT PRIMARY KEY,
                demand_balance      INTEGER NOT NULL DEFAULT 0,
                demand_deposited_at REAL NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bank_deposits (
                deposit_id   TEXT PRIMARY KEY,
                discord_id   TEXT NOT NULL,
                principal    INTEGER NOT NULL,
                term_years   INTEGER NOT NULL,
                rate         REAL NOT NULL,
                interest     INTEGER NOT NULL,
                deposited_at REAL NOT NULL,
                due_at       REAL NOT NULL,
                status       TEXT NOT NULL DEFAULT 'active'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_listings (
                listing_id  TEXT PRIMARY KEY,
                seller_id   TEXT NOT NULL,
                item_type   TEXT NOT NULL,
                item_id     TEXT NOT NULL,
                item_name   TEXT NOT NULL,
                quantity    INTEGER NOT NULL DEFAULT 1,
                price       INTEGER NOT NULL,
                listed_at   REAL NOT NULL,
                expires_at  REAL NOT NULL,
                status      TEXT NOT NULL DEFAULT 'active',
                eq_data     TEXT
            )
        """)
        conn.commit()
