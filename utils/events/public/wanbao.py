import json
import random
import time
import uuid

from utils.db import get_conn

WANBAO_CITY = "万宝楼"
AUCTION_COMMISSION = 0.08
LISTING_FEE = 300
MAX_LOTS = 20
MAX_PLAYER_LOTS = 2
LOT_DURATION = 120
PREVIEW_BEFORE = 7200

GRADE_WEIGHTS = {
    "黄级下品": 40, "黄级中品": 30, "黄级上品": 20,
    "玄级下品": 6,  "玄级中品": 3,  "玄级上品": 1,
    "地级下品": 0.4,"地级中品": 0.2,"地级上品": 0.1,
    "天级下品": 0.05,"天级中品": 0.02,"天级上品": 0.01,
}

RARITY_WEIGHTS = {
    "普通": 50, "稀有": 30, "珍贵": 15, "绝世": 5,
}


def _weighted_choice(pool: list, weight_fn) -> object:
    weights = [weight_fn(x) for x in pool]
    total = sum(weights)
    if total <= 0:
        return random.choice(pool)
    r = random.uniform(0, total)
    acc = 0
    for item, w in zip(pool, weights):
        acc += w
        if r <= acc:
            return item
    return pool[-1]


def generate_house_lots() -> list[dict]:
    from utils.sects import TECHNIQUES
    from utils.items import ITEMS

    lots = []

    techs = list(TECHNIQUES.items())
    chosen_techs = []
    for _ in range(2):
        remaining = [t for t in techs if t[0] not in [x[0] for x in chosen_techs]]
        t = _weighted_choice(remaining, lambda x: GRADE_WEIGHTS.get(x[1].get("grade", "黄级中品"), 1))
        chosen_techs.append(t)

    for name, info in chosen_techs:
        grade = info.get("grade", "黄级中品")
        base = {
            "黄级下品": 500, "黄级中品": 1000, "黄级上品": 2000,
            "玄级下品": 5000, "玄级中品": 10000, "玄级上品": 20000,
            "地级下品": 50000, "地级中品": 100000, "地级上品": 200000,
            "天级下品": 500000, "天级中品": 1000000, "天级上品": 2000000,
        }.get(grade, 1000)
        lots.append({
            "lot_id": str(uuid.uuid4())[:8],
            "seller_id": None,
            "item_name": name,
            "quantity": 1,
            "item_type": "technique",
            "start_price": base,
        })

    pills = [(k, v) for k, v in ITEMS.items() if v.get("type") == "pill"]
    chosen_pills = random.sample(pills, min(2, len(pills)))
    for name, info in chosen_pills:
        rarity = info.get("rarity", "普通")
        base = {"普通": 100, "稀有": 500, "珍贵": 2000, "绝世": 8000}.get(rarity, 100)
        lots.append({
            "lot_id": str(uuid.uuid4())[:8],
            "seller_id": None,
            "item_name": name,
            "quantity": random.randint(1, 3),
            "item_type": "item",
            "start_price": base,
        })

    materials = [(k, v) for k, v in ITEMS.items() if v.get("type") in ("ore", "herb", "wood", "fish")]
    chosen_mats = []
    for _ in range(2):
        remaining = [m for m in materials if m[0] not in [x[0] for x in chosen_mats]]
        m = _weighted_choice(remaining, lambda x: RARITY_WEIGHTS.get(x[1].get("rarity", "普通"), 10))
        chosen_mats.append(m)
    for name, info in chosen_mats:
        rarity = info.get("rarity", "普通")
        base = {"普通": 50, "稀有": 300, "珍贵": 1200, "绝世": 5000}.get(rarity, 50)
        lots.append({
            "lot_id": str(uuid.uuid4())[:8],
            "seller_id": None,
            "item_name": name,
            "quantity": random.randint(1, 5),
            "item_type": "item",
            "start_price": base,
        })

    from utils.equipment import generate_equipment, QUALITY_ORDER
    eq_quality_weights = [40, 30, 20, 8, 2]
    for _ in range(2):
        tier = random.randint(1, 4)
        quality = random.choices(QUALITY_ORDER, weights=eq_quality_weights)[0]
        eq = generate_equipment(tier=tier, quality=quality)
        base = {"普通": 800, "精良": 2000, "稀有": 6000, "史诗": 20000, "传说": 80000}.get(quality, 1000)
        lots.append({
            "lot_id": str(uuid.uuid4())[:8],
            "seller_id": None,
            "item_name": eq["name"],
            "quantity": 1,
            "item_type": "equipment",
            "start_price": base,
            "_eq_data": eq,
        })

    return lots


def get_or_create_auction(date_str: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM wanbao_auctions WHERE date_str = ?", (date_str,)
        ).fetchone()
        if row:
            return dict(row)
        auction_id = str(uuid.uuid4())[:8]
        conn.execute(
            "INSERT INTO wanbao_auctions (auction_id, date_str, status) VALUES (?, ?, 'pending')",
            (auction_id, date_str)
        )
        conn.commit()
        house_lots = generate_house_lots()
        for i, lot in enumerate(house_lots):
            eq_data = lot.pop("_eq_data", None)
            conn.execute(
                "INSERT INTO wanbao_lots (lot_id, auction_id, lot_index, seller_id, item_name, quantity, item_type, start_price, eq_data) VALUES (?,?,?,?,?,?,?,?,?)",
                (lot["lot_id"], auction_id, i, lot["seller_id"], lot["item_name"], lot["quantity"], lot["item_type"], lot["start_price"], json.dumps(eq_data) if eq_data else None)
            )
        conn.commit()
        return dict(conn.execute("SELECT * FROM wanbao_auctions WHERE auction_id = ?", (auction_id,)).fetchone())


def get_active_auction() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM wanbao_auctions WHERE status IN ('active', 'pending') ORDER BY COALESCE(started_at, 0) DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def get_lots(auction_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM wanbao_lots WHERE auction_id = ? ORDER BY lot_index ASC",
            (auction_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_current_lot(auction_id: str) -> dict | None:
    with get_conn() as conn:
        auction = conn.execute("SELECT * FROM wanbao_auctions WHERE auction_id = ?", (auction_id,)).fetchone()
        if not auction:
            return None
        idx = auction["current_lot"]
        row = conn.execute(
            "SELECT * FROM wanbao_lots WHERE auction_id = ? AND lot_index = ? AND status = 'active'",
            (auction_id, idx)
        ).fetchone()
    return dict(row) if row else None


def can_list_item(discord_id: str, auction_id: str) -> tuple[bool, str]:
    with get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM wanbao_lots WHERE auction_id = ? AND seller_id = ?",
            (auction_id, discord_id)
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM wanbao_lots WHERE auction_id = ?",
            (auction_id,)
        ).fetchone()[0]
    if count >= MAX_PLAYER_LOTS:
        return False, f"每位道友最多上架 {MAX_PLAYER_LOTS} 件拍品。"
    if total >= MAX_LOTS:
        return False, f"本次拍卖已满 {MAX_LOTS} 件，无法继续上架。"
    return True, ""


def list_item(auction_id: str, discord_id: str, item_name: str, quantity: int, start_price: int) -> tuple[bool, str]:
    from utils.items import ITEMS

    ok, msg = can_list_item(discord_id, auction_id)
    if not ok:
        return False, msg

    with get_conn() as conn:
        player = conn.execute("SELECT * FROM players WHERE discord_id = ?", (discord_id,)).fetchone()
        if not player:
            return False, "角色不存在。"
        if player["spirit_stones"] < LISTING_FEE:
            return False, f"上架需支付 **{LISTING_FEE} 灵石** 手续费，当前灵石不足。"

    item_info = ITEMS.get(item_name)
    if not item_info:
        from utils.sects import TECHNIQUES
        if item_name not in TECHNIQUES:
            return False, f"未知物品「{item_name}」。"
        item_type = "technique"
    else:
        item_type = "item"

    with get_conn() as conn:
        row = conn.execute(
            "SELECT quantity FROM inventory WHERE discord_id = ? AND item_id = ?",
            (discord_id, item_name)
        ).fetchone()
        if not row or row["quantity"] < quantity:
            return False, f"背包中「{item_name}」数量不足。"
        conn.execute(
            "UPDATE inventory SET quantity = quantity - ? WHERE discord_id = ? AND item_id = ?",
            (quantity, discord_id, item_name)
        )
        conn.execute(
            "DELETE FROM inventory WHERE discord_id = ? AND item_id = ? AND quantity <= 0",
            (discord_id, item_name)
        )
        conn.execute(
            "UPDATE players SET spirit_stones = spirit_stones - ? WHERE discord_id = ?",
            (LISTING_FEE, discord_id)
        )
        lot_id = str(uuid.uuid4())[:8]
        total = conn.execute("SELECT COUNT(*) FROM wanbao_lots WHERE auction_id = ?", (auction_id,)).fetchone()[0]
        conn.execute(
            "INSERT INTO wanbao_lots (lot_id, auction_id, lot_index, seller_id, item_name, quantity, item_type, start_price) VALUES (?,?,?,?,?,?,?,?)",
            (lot_id, auction_id, total, discord_id, item_name, quantity, item_type, start_price)
        )
        conn.commit()
    return True, f"已上架「{item_name}」×{quantity}，起拍价 {start_price} 灵石。"


def place_bid(auction_id: str, discord_id: str, amount: int) -> tuple[bool, str]:
    with get_conn() as conn:
        auction = conn.execute("SELECT * FROM wanbao_auctions WHERE auction_id = ?", (auction_id,)).fetchone()
        if not auction or auction["status"] != "active":
            return False, "拍卖未进行中。"

        idx = auction["current_lot"]
        lot = conn.execute(
            "SELECT * FROM wanbao_lots WHERE auction_id = ? AND lot_index = ? AND status = 'active'",
            (auction_id, idx)
        ).fetchone()
        if not lot:
            return False, "当前无进行中的拍品。"

        lot = dict(lot)
        if lot["seller_id"] == discord_id:
            return False, "不能对自己的拍品出价。"

        min_bid = max(lot["start_price"], lot["current_bid"] + 1)
        if amount < min_bid:
            return False, f"出价不得低于 **{min_bid} 灵石**。"

        player = conn.execute("SELECT * FROM players WHERE discord_id = ?", (discord_id,)).fetchone()
        if not player:
            return False, "角色不存在。"

        frozen_row = conn.execute(
            "SELECT amount FROM wanbao_frozen WHERE discord_id = ? AND auction_id = ?",
            (discord_id, auction_id)
        ).fetchone()
        frozen = frozen_row["amount"] if frozen_row else 0
        if player["spirit_stones"] < amount:
            return False, f"可用灵石不足（当前 {player['spirit_stones']}，出价需 {amount}）。"

        prev_bidder = lot["bidder_id"]
        if prev_bidder and prev_bidder != discord_id:
            prev_bid = lot["current_bid"]
            prev_frozen = conn.execute(
                "SELECT amount FROM wanbao_frozen WHERE discord_id = ? AND auction_id = ?",
                (prev_bidder, auction_id)
            ).fetchone()
            if prev_frozen:
                new_frozen = max(0, prev_frozen["amount"] - prev_bid)
                conn.execute(
                    "INSERT INTO wanbao_frozen (discord_id, auction_id, amount) VALUES (?,?,?) ON CONFLICT(discord_id, auction_id) DO UPDATE SET amount = ?",
                    (prev_bidder, auction_id, new_frozen, new_frozen)
                )

        conn.execute(
            "INSERT INTO wanbao_frozen (discord_id, auction_id, amount) VALUES (?,?,?) ON CONFLICT(discord_id, auction_id) DO UPDATE SET amount = ?",
            (discord_id, auction_id, amount, amount)
        )
        conn.execute(
            "UPDATE wanbao_lots SET current_bid = ?, bidder_id = ? WHERE lot_id = ?",
            (amount, discord_id, lot["lot_id"])
        )
        conn.commit()
    return True, ""


def settle_lot(lot: dict) -> dict:
    result = {"lot": lot, "winner_id": None, "final_price": 0, "seller_income": 0}
    with get_conn() as conn:
        if not lot["bidder_id"]:
            conn.execute("UPDATE wanbao_lots SET status = 'unsold' WHERE lot_id = ?", (lot["lot_id"],))
            if lot["seller_id"]:
                conn.execute(
                    "UPDATE players SET spirit_stones = spirit_stones - ? WHERE discord_id = ?",
                    (LISTING_FEE, lot["seller_id"])
                )
            conn.commit()
            return result

        winner_id = lot["bidder_id"]
        final_price = lot["current_bid"]
        commission = int(final_price * AUCTION_COMMISSION)
        seller_income = final_price - commission

        player_row = conn.execute("SELECT spirit_stones FROM players WHERE discord_id = ?", (winner_id,)).fetchone()
        actual_deduct = min(final_price, player_row["spirit_stones"]) if player_row else final_price
        conn.execute(
            "UPDATE players SET spirit_stones = MAX(0, spirit_stones - ?) WHERE discord_id = ?",
            (final_price, winner_id)
        )
        frozen_row = conn.execute(
            "SELECT amount FROM wanbao_frozen WHERE discord_id = ? AND auction_id = ?",
            (winner_id, lot["auction_id"])
        ).fetchone()
        if frozen_row:
            new_frozen = max(0, frozen_row["amount"] - final_price)
            conn.execute(
                "INSERT INTO wanbao_frozen (discord_id, auction_id, amount) VALUES (?,?,?) ON CONFLICT(discord_id, auction_id) DO UPDATE SET amount = ?",
                (winner_id, lot["auction_id"], new_frozen, new_frozen)
            )

        if lot["item_type"] == "technique":
            conn.execute(
                "INSERT INTO inventory (discord_id, item_id, quantity) VALUES (?,?,1) ON CONFLICT(discord_id, item_id) DO UPDATE SET quantity = quantity + 1",
                (winner_id, lot["item_name"])
            )
        elif lot["item_type"] == "equipment":
            import json as _json
            eq_raw = lot.get("eq_data")
            eq_data = _json.loads(eq_raw) if eq_raw else None
            if eq_data:
                import json as _json2
                conn.execute("""
                    INSERT INTO equipment (equip_id, discord_id, name, slot, quality, tier, tier_req, stats, flavor, equipped)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (
                    eq_data["equip_id"], winner_id, eq_data["name"], eq_data["slot"],
                    eq_data["quality"], eq_data["tier"], eq_data["tier_req"],
                    _json2.dumps(eq_data["stats"], ensure_ascii=False), eq_data["flavor"]
                ))
        else:
            conn.execute(
                "INSERT INTO inventory (discord_id, item_id, quantity) VALUES (?,?,?) ON CONFLICT(discord_id, item_id) DO UPDATE SET quantity = quantity + ?",
                (winner_id, lot["item_name"], lot["quantity"], lot["quantity"])
            )

        if lot["seller_id"]:
            conn.execute(
                "UPDATE players SET spirit_stones = spirit_stones + ? WHERE discord_id = ?",
                (seller_income, lot["seller_id"])
            )

        conn.execute("UPDATE wanbao_lots SET status = 'sold' WHERE lot_id = ?", (lot["lot_id"],))
        conn.commit()

    result["winner_id"] = winner_id
    result["final_price"] = final_price
    result["seller_income"] = seller_income
    return result


def advance_lot(auction_id: str) -> dict | None:
    with get_conn() as conn:
        auction = conn.execute("SELECT * FROM wanbao_auctions WHERE auction_id = ?", (auction_id,)).fetchone()
        if not auction:
            return None
        next_idx = auction["current_lot"] + 1
        next_lot = conn.execute(
            "SELECT * FROM wanbao_lots WHERE auction_id = ? AND lot_index = ? AND status = 'pending'",
            (auction_id, next_idx)
        ).fetchone()
        if not next_lot:
            conn.execute("UPDATE wanbao_auctions SET status = 'ended' WHERE auction_id = ?", (auction_id,))
            conn.commit()
            return None
        now = time.time()
        conn.execute(
            "UPDATE wanbao_lots SET status = 'active' WHERE lot_id = ?",
            (next_lot["lot_id"],)
        )
        conn.execute(
            "UPDATE wanbao_auctions SET current_lot = ?, ends_at = ? WHERE auction_id = ?",
            (next_idx, now + LOT_DURATION, auction_id)
        )
        conn.commit()
    return dict(next_lot)


def start_auction(auction_id: str) -> dict | None:
    with get_conn() as conn:
        first_lot = conn.execute(
            "SELECT * FROM wanbao_lots WHERE auction_id = ? AND lot_index = 0",
            (auction_id,)
        ).fetchone()
        if not first_lot:
            return None
        now = time.time()
        conn.execute(
            "UPDATE wanbao_lots SET status = 'active' WHERE lot_id = ?",
            (first_lot["lot_id"],)
        )
        conn.execute(
            "UPDATE wanbao_auctions SET status = 'active', started_at = ?, ends_at = ?, current_lot = 0 WHERE auction_id = ?",
            (now, now + LOT_DURATION, auction_id)
        )
        conn.commit()
    return dict(first_lot)


def is_in_wanbao(discord_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT current_city FROM players WHERE discord_id = ?", (discord_id,)
        ).fetchone()
    return row and row["current_city"] == WANBAO_CITY


def is_auction_locked(discord_id: str) -> bool:
    auction = get_active_auction()
    if not auction or auction["status"] != "active":
        return False
    return is_in_wanbao(discord_id)
