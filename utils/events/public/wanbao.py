import json
import random
import time
import uuid

from utils.atomic import consume_item, spend_stones
from utils.db_async import AsyncSessionLocal
from sqlalchemy import text

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


async def get_or_create_auction(date_str: str) -> dict:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM wanbao_auctions WHERE date_str = :ds"), {"ds": date_str}
        )
        row = result.fetchone()
        if row:
            return dict(row._mapping)
        auction_id = str(uuid.uuid4())[:8]
        await session.execute(
            text("INSERT INTO wanbao_auctions (auction_id, date_str, status) VALUES (:aid, :ds, 'pending')"),
            {"aid": auction_id, "ds": date_str}
        )
        await session.commit()
        house_lots = generate_house_lots()
        for i, lot in enumerate(house_lots):
            eq_data = lot.pop("_eq_data", None)
            await session.execute(
                text("INSERT INTO wanbao_lots (lot_id, auction_id, lot_index, seller_id, item_name, quantity, item_type, start_price, eq_data) VALUES (:lid,:aid,:idx,:sid,:iname,:qty,:itype,:sp,:eq)"),
                {
                    "lid": lot["lot_id"], "aid": auction_id, "idx": i,
                    "sid": lot["seller_id"], "iname": lot["item_name"],
                    "qty": lot["quantity"], "itype": lot["item_type"],
                    "sp": lot["start_price"],
                    "eq": json.dumps(eq_data) if eq_data else None
                }
            )
        await session.commit()
        result2 = await session.execute(
            text("SELECT * FROM wanbao_auctions WHERE auction_id = :aid"), {"aid": auction_id}
        )
        return dict(result2.fetchone()._mapping)


async def get_active_auction() -> dict | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM wanbao_auctions WHERE status IN ('active', 'pending') ORDER BY COALESCE(started_at, 0) DESC LIMIT 1")
        )
        row = result.fetchone()
    return dict(row._mapping) if row else None


async def get_lots(auction_id: str) -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM wanbao_lots WHERE auction_id = :aid ORDER BY lot_index ASC"),
            {"aid": auction_id}
        )
        rows = result.fetchall()
    return [dict(r._mapping) for r in rows]


async def get_current_lot(auction_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM wanbao_auctions WHERE auction_id = :aid"), {"aid": auction_id}
        )
        auction = result.fetchone()
        if not auction:
            return None
        idx = auction._mapping["current_lot"]
        result2 = await session.execute(
            text("SELECT * FROM wanbao_lots WHERE auction_id = :aid AND lot_index = :idx AND status = 'active'"),
            {"aid": auction_id, "idx": idx}
        )
        row = result2.fetchone()
    return dict(row._mapping) if row else None


async def can_list_item(discord_id: str, auction_id: str) -> tuple[bool, str]:
    async with AsyncSessionLocal() as session:
        r1 = await session.execute(
            text("SELECT COUNT(*) FROM wanbao_lots WHERE auction_id = :aid AND seller_id = :uid"),
            {"aid": auction_id, "uid": discord_id}
        )
        count = r1.scalar()
        r2 = await session.execute(
            text("SELECT COUNT(*) FROM wanbao_lots WHERE auction_id = :aid"),
            {"aid": auction_id}
        )
        total = r2.scalar()
    if count >= MAX_PLAYER_LOTS:
        return False, f"每位道友最多上架 {MAX_PLAYER_LOTS} 件拍品。"
    if total >= MAX_LOTS:
        return False, f"本次拍卖已满 {MAX_LOTS} 件，无法继续上架。"
    return True, ""


async def list_item(auction_id: str, discord_id: str, item_name: str, quantity: int, start_price: int) -> tuple[bool, str]:
    from utils.items import ITEMS

    ok, msg = await can_list_item(discord_id, auction_id)
    if not ok:
        return False, msg

    async with AsyncSessionLocal() as session:
        pr = await session.execute(
            text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": discord_id}
        )
        player = pr.fetchone()
        if not player:
            return False, "角色不存在。"
        if player._mapping["spirit_stones"] < LISTING_FEE:
            return False, f"上架需支付 **{LISTING_FEE} 灵石** 手续费，当前灵石不足。"

    item_info = ITEMS.get(item_name)
    if not item_info:
        from utils.sects import TECHNIQUES
        if item_name not in TECHNIQUES:
            return False, f"未知物品「{item_name}」。"
        item_type = "technique"
    else:
        item_type = "item"

    async with AsyncSessionLocal() as session:
        inv_r = await session.execute(
            text("SELECT quantity FROM inventory WHERE discord_id = :uid AND item_id = :iid"),
            {"uid": discord_id, "iid": item_name}
        )
        row = inv_r.fetchone()
        if not row or row[0] < quantity:
            return False, f"背包中「{item_name}」数量不足。"
        # 物品与手续费一起原子扣：原先两条裸 UPDATE 都没有"够不够"的条件，
        # 能把库存和灵石都扣成负数。
        if not await consume_item(session, discord_id, item_name, quantity):
            await session.rollback()
            return False, f"「{item_name}」数量不足。"
        if not await spend_stones(session, discord_id, LISTING_FEE):
            await session.rollback()
            return False, f"灵石不足，寄售需缴纳 {LISTING_FEE} 灵石手续费。"
        lot_id = str(uuid.uuid4())[:8]
        total_r = await session.execute(
            text("SELECT COUNT(*) FROM wanbao_lots WHERE auction_id = :aid"), {"aid": auction_id}
        )
        total = total_r.scalar()
        await session.execute(
            text("INSERT INTO wanbao_lots (lot_id, auction_id, lot_index, seller_id, item_name, quantity, item_type, start_price) VALUES (:lid,:aid,:idx,:sid,:iname,:qty,:itype,:sp)"),
            {"lid": lot_id, "aid": auction_id, "idx": total, "sid": discord_id,
             "iname": item_name, "qty": quantity, "itype": item_type, "sp": start_price}
        )
        await session.commit()
    return True, f"已上架「{item_name}」×{quantity}，起拍价 {start_price} 灵石。"



async def claim_highest_bid(session, lot_id: str, seen_bid: int,
                            amount: int, bidder_id: str) -> bool:
    """原子抢占最高价。current_bid 仍等于 seen_bid 时才生效，否则本次出价作废。

    单抽出来是为了能直接测：走 place_bid 整条路去撞时序很难稳定复现，
    这里传个过期的 seen_bid 就行。
    """
    result = await session.execute(
        text(
            "UPDATE wanbao_lots SET current_bid = :amt, bidder_id = :uid "
            "WHERE lot_id = :lid AND status = 'active' "
            "AND COALESCE(current_bid, 0) = :seen"
        ),
        {"amt": amount, "uid": bidder_id, "lid": lot_id, "seen": seen_bid},
    )
    return result.rowcount == 1


async def place_bid(auction_id: str, discord_id: str, amount: int) -> tuple[bool, str]:
    async with AsyncSessionLocal() as session:
        ar = await session.execute(
            text("SELECT * FROM wanbao_auctions WHERE auction_id = :aid"), {"aid": auction_id}
        )
        auction = ar.fetchone()
        if not auction or auction._mapping["status"] != "active":
            return False, "拍卖未进行中。"

        idx = auction._mapping["current_lot"]
        lr = await session.execute(
            text("SELECT * FROM wanbao_lots WHERE auction_id = :aid AND lot_index = :idx AND status = 'active'"),
            {"aid": auction_id, "idx": idx}
        )
        lot_row = lr.fetchone()
        if not lot_row:
            return False, "当前无进行中的拍品。"

        lot = dict(lot_row._mapping)
        if lot["seller_id"] == discord_id:
            return False, "不能对自己的拍品出价。"

        min_bid = max(lot["start_price"], (lot["current_bid"] or 0) + 1)
        if amount < min_bid:
            return False, f"出价不得低于 **{min_bid} 灵石**。"

        pr = await session.execute(
            text("SELECT * FROM players WHERE discord_id = :uid"), {"uid": discord_id}
        )
        player = pr.fetchone()
        if not player:
            return False, "角色不存在。"

        if player._mapping["spirit_stones"] < amount:
            return False, f"可用灵石不足（当前 {player._mapping['spirit_stones']}，出价需 {amount}）。"

        # 原子抢占最高价，此时尚未动过任何冻结额度，失败可以直接返回
        if not await claim_highest_bid(
            session, lot["lot_id"], lot["current_bid"] or 0, amount, discord_id
        ):
            return False, "已有更高出价，请重新出价。"

        prev_bidder = lot["bidder_id"]
        if prev_bidder and prev_bidder != discord_id:
            prev_bid = lot["current_bid"]
            pfr = await session.execute(
                text("SELECT amount FROM wanbao_frozen WHERE discord_id = :uid AND auction_id = :aid"),
                {"uid": prev_bidder, "aid": auction_id}
            )
            prev_frozen = pfr.fetchone()
            if prev_frozen:
                new_frozen = max(0, prev_frozen[0] - prev_bid)
                await session.execute(
                    text("INSERT INTO wanbao_frozen (discord_id, auction_id, amount) VALUES (:uid,:aid,:amt) ON CONFLICT(discord_id, auction_id) DO UPDATE SET amount = :amt"),
                    {"uid": prev_bidder, "aid": auction_id, "amt": new_frozen}
                )

        await session.execute(
            text("INSERT INTO wanbao_frozen (discord_id, auction_id, amount) VALUES (:uid,:aid,:amt) ON CONFLICT(discord_id, auction_id) DO UPDATE SET amount = :amt"),
            {"uid": discord_id, "aid": auction_id, "amt": amount}
        )
        await session.commit()
    return True, ""


async def settle_lot(lot: dict) -> dict:
    result = {"lot": lot, "winner_id": None, "final_price": 0, "seller_income": 0}
    async with AsyncSessionLocal() as session:
        if not lot["bidder_id"]:
            await session.execute(
                text("UPDATE wanbao_lots SET status = 'unsold' WHERE lot_id = :lid"),
                {"lid": lot["lot_id"]}
            )
            if lot["seller_id"]:
                # 流拍罚金：扣到 0 为止，不允许把灵石扣成负数
                await session.execute(
                    text("UPDATE players SET spirit_stones = MAX(0, spirit_stones - :fee) "
                         "WHERE discord_id = :uid"),
                    {"fee": LISTING_FEE, "uid": lot["seller_id"]}
                )
            await session.commit()
            return result

        winner_id = lot["bidder_id"]
        final_price = lot["current_bid"]
        commission = int(final_price * AUCTION_COMMISSION)
        seller_income = final_price - commission

        await session.execute(
            text("UPDATE players SET spirit_stones = MAX(0, spirit_stones - :fp) WHERE discord_id = :uid"),
            {"fp": final_price, "uid": winner_id}
        )
        fr = await session.execute(
            text("SELECT amount FROM wanbao_frozen WHERE discord_id = :uid AND auction_id = :aid"),
            {"uid": winner_id, "aid": lot["auction_id"]}
        )
        frozen_row = fr.fetchone()
        if frozen_row:
            new_frozen = max(0, frozen_row[0] - final_price)
            await session.execute(
                text("INSERT INTO wanbao_frozen (discord_id, auction_id, amount) VALUES (:uid,:aid,:amt) ON CONFLICT(discord_id, auction_id) DO UPDATE SET amount = :amt"),
                {"uid": winner_id, "aid": lot["auction_id"], "amt": new_frozen}
            )

        if lot["item_type"] == "technique":
            await session.execute(
                text("INSERT INTO inventory (discord_id, item_id, quantity) VALUES (:uid,:iid,1) ON CONFLICT(discord_id, item_id) DO UPDATE SET quantity = quantity + 1"),
                {"uid": winner_id, "iid": lot["item_name"]}
            )
        elif lot["item_type"] == "equipment":
            eq_raw = lot.get("eq_data")
            eq_data = json.loads(eq_raw) if eq_raw else None
            if eq_data:
                await session.execute(
                    text("""
                        INSERT INTO equipment (equip_id, discord_id, name, slot, quality, tier, tier_req, stats, flavor, equipped)
                        VALUES (:eid, :uid, :name, :slot, :qual, :tier, :treq, :stats, :flavor, 0)
                    """),
                    {
                        "eid": eq_data["equip_id"], "uid": winner_id, "name": eq_data["name"],
                        "slot": eq_data["slot"], "qual": eq_data["quality"], "tier": eq_data["tier"],
                        "treq": eq_data["tier_req"],
                        "stats": json.dumps(eq_data["stats"], ensure_ascii=False),
                        "flavor": eq_data["flavor"]
                    }
                )
        else:
            await session.execute(
                text("INSERT INTO inventory (discord_id, item_id, quantity) VALUES (:uid,:iid,:qty) ON CONFLICT(discord_id, item_id) DO UPDATE SET quantity = quantity + :qty"),
                {"uid": winner_id, "iid": lot["item_name"], "qty": lot["quantity"]}
            )

        if lot["seller_id"]:
            await session.execute(
                text("UPDATE players SET spirit_stones = spirit_stones + :inc WHERE discord_id = :uid"),
                {"inc": seller_income, "uid": lot["seller_id"]}
            )

        await session.execute(
            text("UPDATE wanbao_lots SET status = 'sold' WHERE lot_id = :lid"),
            {"lid": lot["lot_id"]}
        )
        await session.commit()

    result["winner_id"] = winner_id
    result["final_price"] = final_price
    result["seller_income"] = seller_income
    return result


async def advance_lot(auction_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        ar = await session.execute(
            text("SELECT * FROM wanbao_auctions WHERE auction_id = :aid"), {"aid": auction_id}
        )
        auction = ar.fetchone()
        if not auction:
            return None
        next_idx = auction._mapping["current_lot"] + 1
        nlr = await session.execute(
            text("SELECT * FROM wanbao_lots WHERE auction_id = :aid AND lot_index = :idx AND status = 'pending'"),
            {"aid": auction_id, "idx": next_idx}
        )
        next_lot = nlr.fetchone()
        if not next_lot:
            await session.execute(
                text("UPDATE wanbao_auctions SET status = 'ended' WHERE auction_id = :aid"),
                {"aid": auction_id}
            )
            await session.commit()
            return None
        now = time.time()
        await session.execute(
            text("UPDATE wanbao_lots SET status = 'active' WHERE lot_id = :lid"),
            {"lid": next_lot._mapping["lot_id"]}
        )
        await session.execute(
            text("UPDATE wanbao_auctions SET current_lot = :idx, ends_at = :ea WHERE auction_id = :aid"),
            {"idx": next_idx, "ea": now + LOT_DURATION, "aid": auction_id}
        )
        await session.commit()
    return dict(next_lot._mapping)


async def start_auction(auction_id: str) -> dict | None:
    async with AsyncSessionLocal() as session:
        flr = await session.execute(
            text("SELECT * FROM wanbao_lots WHERE auction_id = :aid AND lot_index = 0"),
            {"aid": auction_id}
        )
        first_lot = flr.fetchone()
        if not first_lot:
            return None
        now = time.time()
        await session.execute(
            text("UPDATE wanbao_lots SET status = 'active' WHERE lot_id = :lid"),
            {"lid": first_lot._mapping["lot_id"]}
        )
        await session.execute(
            text("UPDATE wanbao_auctions SET status = 'active', started_at = :sa, ends_at = :ea, current_lot = 0 WHERE auction_id = :aid"),
            {"sa": now, "ea": now + LOT_DURATION, "aid": auction_id}
        )
        await session.commit()
    return dict(first_lot._mapping)


async def get_last_ended_auction() -> dict | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT * FROM wanbao_auctions WHERE status = 'ended' ORDER BY started_at DESC LIMIT 1")
        )
        row = result.fetchone()
    return dict(row._mapping) if row else None


async def is_in_wanbao(discord_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT current_city FROM players WHERE discord_id = :uid"), {"uid": discord_id}
        )
        row = result.fetchone()
    return row is not None and row[0] == WANBAO_CITY


async def is_auction_locked(discord_id: str) -> bool:
    auction = await get_active_auction()
    if not auction or auction["status"] != "active":
        return False
    return await is_in_wanbao(discord_id)


class WanbaoAuctionEvent:
    pass
