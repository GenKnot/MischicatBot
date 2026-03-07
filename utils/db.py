import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "game.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(players)")}
    migrations = [
        ("rebirth_count",        "INTEGER NOT NULL DEFAULT 0"),
        ("is_virgin",            "INTEGER NOT NULL DEFAULT 1"),
        ("sect",                 "TEXT"),
        ("sect_rank",            "TEXT"),
        ("last_dual_cultivate",  "REAL"),
        ("techniques",           "TEXT NOT NULL DEFAULT '[]'"),
        ("cultivation_overflow", "INTEGER NOT NULL DEFAULT 0"),
        ("current_city",         "TEXT NOT NULL DEFAULT '灵虚城'"),
        ("explore_count",        "INTEGER NOT NULL DEFAULT 0"),
        ("explore_reset_year",   "REAL NOT NULL DEFAULT 0"),
        ("cave",                 "TEXT"),
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
                realm         TEXT NOT NULL DEFAULT '炼气期一层',
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
                techniques            TEXT NOT NULL DEFAULT '[]',
                cultivation_overflow  INTEGER NOT NULL DEFAULT 0,
                current_city          TEXT NOT NULL DEFAULT '灵虚城',
                explore_count         INTEGER NOT NULL DEFAULT 0,
                explore_reset_year    REAL NOT NULL DEFAULT 0
            )
        """)
        _migrate(conn)
        conn.commit()


def get_residences(discord_id: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT city FROM residences WHERE discord_id = ?", (discord_id,)
        ).fetchall()
    return [r["city"] for r in rows]


def has_residence(discord_id: str, city: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM residences WHERE discord_id = ? AND city = ?", (discord_id, city)
        ).fetchone()
    return row is not None
