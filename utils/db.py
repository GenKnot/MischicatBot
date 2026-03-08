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
        ("discovered_sects",     "TEXT NOT NULL DEFAULT '[]'"),
        ("escape_rate",          "INTEGER NOT NULL DEFAULT 0"),
        ("has_bahongchen",       "INTEGER NOT NULL DEFAULT 0"),
        ("active_quest",         "TEXT"),
        ("quest_due",            "REAL"),
        ("party_id",             "TEXT"),
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
            PRIMARY KEY (event_id, discord_id)
        )
    """)
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
                explore_reset_year    REAL NOT NULL DEFAULT 0,
                escape_rate           INTEGER NOT NULL DEFAULT 0,
                has_bahongchen        INTEGER NOT NULL DEFAULT 0
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


def get_inventory(discord_id: str) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT item_id, quantity FROM inventory WHERE discord_id = ?", (discord_id,)
        ).fetchall()
    return {r["item_id"]: r["quantity"] for r in rows}


def add_item(discord_id: str, item_id: str, quantity: int = 1):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO inventory (discord_id, item_id, quantity)
            VALUES (?, ?, ?)
            ON CONFLICT(discord_id, item_id) DO UPDATE SET quantity = quantity + ?
        """, (discord_id, item_id, quantity, quantity))
        conn.commit()


def remove_item(discord_id: str, item_id: str, quantity: int = 1) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT quantity FROM inventory WHERE discord_id = ? AND item_id = ?",
            (discord_id, item_id)
        ).fetchone()
        if not row or row["quantity"] < quantity:
            return False
        new_qty = row["quantity"] - quantity
        if new_qty <= 0:
            conn.execute(
                "DELETE FROM inventory WHERE discord_id = ? AND item_id = ?",
                (discord_id, item_id)
            )
        else:
            conn.execute(
                "UPDATE inventory SET quantity = ? WHERE discord_id = ? AND item_id = ?",
                (new_qty, discord_id, item_id)
            )
        conn.commit()
    return True


def has_item(discord_id: str, item_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT quantity FROM inventory WHERE discord_id = ? AND item_id = ? AND quantity > 0",
            (discord_id, item_id)
        ).fetchone()
    return row is not None


def give_equipment(discord_id: str, eq: dict):
    import json
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO equipment (equip_id, discord_id, name, slot, quality, tier, tier_req, stats, flavor, equipped)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            eq["equip_id"], discord_id, eq["name"], eq["slot"],
            eq["quality"], eq["tier"], eq["tier_req"],
            json.dumps(eq["stats"], ensure_ascii=False), eq["flavor"]
        ))
        conn.commit()


def get_equipment_list(discord_id: str) -> list[dict]:
    import json
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM equipment WHERE discord_id = ? ORDER BY equipped DESC, tier DESC, quality DESC",
            (discord_id,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["stats"] = json.loads(d["stats"])
        result.append(d)
    return result


def get_equipped(discord_id: str) -> list[dict]:
    import json
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM equipment WHERE discord_id = ? AND equipped = 1",
            (discord_id,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["stats"] = json.loads(d["stats"])
        result.append(d)
    return result


def equip_item(discord_id: str, equip_id: str, player_tier: int) -> tuple[bool, str]:
    import json
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM equipment WHERE equip_id = ? AND discord_id = ?",
            (equip_id, discord_id)
        ).fetchone()
        if not row:
            return False, "装备不存在。"
        eq = dict(row)
        eq["stats"] = json.loads(eq["stats"])
        if player_tier < eq["tier_req"]:
            from utils.equipment import TIER_NAMES
            req_name = TIER_NAMES[min(eq["tier_req"], len(TIER_NAMES) - 1)]
            return False, f"需要达到 **{req_name}期** 才能装备此物。"
        already_equipped = conn.execute(
            "SELECT equip_id FROM equipment WHERE discord_id = ? AND slot = ? AND equipped = 1",
            (discord_id, eq["slot"])
        ).fetchone()
        if already_equipped:
            conn.execute(
                "UPDATE equipment SET equipped = 0 WHERE equip_id = ?",
                (already_equipped["equip_id"],)
            )
        conn.execute(
            "UPDATE equipment SET equipped = 1 WHERE equip_id = ?",
            (equip_id,)
        )
        conn.commit()
    return True, f"已装备 **{eq['name']}**。"


def unequip_item(discord_id: str, equip_id: str) -> tuple[bool, str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM equipment WHERE equip_id = ? AND discord_id = ? AND equipped = 1",
            (equip_id, discord_id)
        ).fetchone()
        if not row:
            return False, "该装备未装备或不存在。"
        conn.execute(
            "UPDATE equipment SET equipped = 0 WHERE equip_id = ?",
            (equip_id,)
        )
        conn.commit()
    return True, f"已卸下 **{row['name']}**。"


def discard_equipment(discord_id: str, equip_id: str) -> tuple[bool, str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT name, equipped FROM equipment WHERE equip_id = ? AND discord_id = ?",
            (equip_id, discord_id)
        ).fetchone()
        if not row:
            return False, "装备不存在。"
        if row["equipped"]:
            return False, "请先卸下装备再丢弃。"
        conn.execute("DELETE FROM equipment WHERE equip_id = ?", (equip_id,))
        conn.commit()
    return True, f"已丢弃 **{row['name']}**。"
