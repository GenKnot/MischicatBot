import random
import time
from sqlalchemy import update
from utils.atomic import consume_item
from utils.db_async import AsyncSessionLocal, Player
from utils.realms import (
    cultivation_needed, lifespan_max_for_realm, next_realm,
    roll_breakthrough, roll_failure_outcome, apply_failure
)
from utils.adventure_chain import try_fox_charm

STALE_MESSAGE = "状态已变化，请重新尝试突破。"


async def can_breakthrough(discord_id: str) -> tuple[bool, dict | None]:
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return False, None

        needed = cultivation_needed(player.realm)
        can_bt = player.cultivation >= needed

        player_dict = {c.key: getattr(player, c.key) for c in player.__table__.columns}

        return can_bt, player_dict


async def _cas_update(session, discord_id: str, player_dict: dict, values: dict) -> str | None:
    """以「读到的境界 + 修为」为条件写回；条件不再成立返回原因，成立返回 None。

    这是突破的防重复结算：连点两次，两次都读到同一份状态，第一次写完后第二次就
    匹配不到行 —— 否则同一份状态会被判定两遍（可能连升两级，或失败惩罚扣两次）。
    不成立时已经 rollback，连带同一事务里的扣丹一并退回。
    """
    result = await session.execute(
        update(Player)
        .where(
            Player.discord_id == discord_id,
            Player.realm == player_dict["realm"],
            Player.cultivation == player_dict["cultivation"],
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 1:
        return None
    await session.rollback()
    if await session.get(Player, discord_id) is None:
        return "角色不存在"
    return STALE_MESSAGE


async def _settle_success(session, discord_id: str, player_dict: dict, nxt: str) -> tuple[int, int, int] | str:
    """突破成功的落库：晋级、结转溢出修为、补寿元上限的增量。**不 commit**。

    返回 (新寿元, 新寿元上限, 寿元增量)；失败时返回原因字符串。
    """
    needed = cultivation_needed(player_dict["realm"])
    overflow = max(0, player_dict["cultivation"] - needed)
    new_lifespan_max = lifespan_max_for_realm(nxt)
    lifespan_gain = max(0, new_lifespan_max - player_dict["lifespan_max"])
    new_lifespan = player_dict["lifespan"] + lifespan_gain

    error = await _cas_update(session, discord_id, player_dict, {
        "realm": nxt,
        "lifespan": new_lifespan,
        "lifespan_max": new_lifespan_max,
        "cultivation": overflow,
        "last_active": time.time(),
    })
    if error:
        return error
    return new_lifespan, new_lifespan_max, lifespan_gain


async def _settle_failure(session, discord_id: str, player_dict: dict,
                          new_cultivation: int, new_lifespan: int) -> dict | str:
    """突破失败的落库。寿元耗尽时先看狐符能不能续命，不能才标记死亡。**不 commit**。

    返回的 lifespan / is_dead 是**结算之后**的真实状态 —— 狐符会把寿元救回 1 年，
    调用方据此出提示，不能再拿 `new_lifespan <= 0` 去猜死没死。
    失败时返回原因字符串。
    """
    error = await _cas_update(session, discord_id, player_dict, {
        "cultivation": new_cultivation,
        "lifespan": new_lifespan,
        "last_active": time.time(),
    })
    if error:
        return error

    if new_lifespan > 0:
        return {"lifespan": new_lifespan, "is_dead": False, "saved_by_charm": False}

    player = await session.get(Player, discord_id)
    saved_by_charm = await try_fox_charm(discord_id, player)
    if not saved_by_charm:
        player.is_dead = True
    return {"lifespan": player.lifespan, "is_dead": not saved_by_charm, "saved_by_charm": saved_by_charm}


async def do_single_breakthrough(discord_id: str, player_dict: dict) -> dict:
    realm = player_dict["realm"]
    nxt = next_realm(realm)

    if not nxt:
        return {"success": False, "message": "已至大道巅峰"}

    success, outcome = roll_breakthrough(
        realm,
        player_dict["physique"],
        player_dict["bone"],
        player_dict["cultivation"]
    )

    if success:
        async with AsyncSessionLocal() as session:
            settled = await _settle_success(session, discord_id, player_dict, nxt)
            if isinstance(settled, str):
                return {"success": False, "message": settled}
            await session.commit()
        new_lifespan, new_lifespan_max, lifespan_gain = settled

        return {
            "success": True,
            "breakthrough": True,
            "old_realm": realm,
            "new_realm": nxt,
            "lifespan": new_lifespan,
            "lifespan_max": new_lifespan_max,
            "lifespan_gain": lifespan_gain
        }
    else:
        new_cultivation, new_lifespan, fail_msg = apply_failure(
            player_dict["cultivation"],
            player_dict["lifespan"],
            outcome
        )
        async with AsyncSessionLocal() as session:
            settled = await _settle_failure(session, discord_id, player_dict, new_cultivation, new_lifespan)
            if isinstance(settled, str):
                return {"success": False, "message": settled}
            await session.commit()

        return {
            "success": True,
            "breakthrough": False,
            "fail_msg": fail_msg,
            "cultivation": new_cultivation,
            "lifespan": settled["lifespan"],
            "needed": cultivation_needed(realm),
            "is_dead": settled["is_dead"],
            "saved_by_charm": settled["saved_by_charm"],
        }


async def do_breakthrough_chain(discord_id: str) -> dict:
    chain = []

    can_bt, player_dict = await can_breakthrough(discord_id)
    if not can_bt or not player_dict:
        return {"success": False, "message": "修为未圆满"}

    while True:
        result = await do_single_breakthrough(discord_id, player_dict)

        if not result["success"]:
            chain.append(result["message"])
            break

        if result["breakthrough"]:
            lifespan_line = (
                f"寿元上限→{result['lifespan_max']}年"
                if result["lifespan_gain"] > 0
                else f"寿元{result['lifespan']}年"
            )
            chain.append(f"**{result['old_realm']}** ➜ **{result['new_realm']}**（{lifespan_line}）")

            can_bt, player_dict = await can_breakthrough(discord_id)
            if not can_bt:
                break
        else:
            if result["is_dead"]:
                chain.append(f"突破失败，{result['fail_msg']}寿元耗尽，魂归天道。")
            elif result["saved_by_charm"]:
                chain.append(
                    f"突破失败，{result['fail_msg']}"
                    f"危急关头，狐符替你挡下一劫，寿元仅余{result['lifespan']}年。"
                )
            else:
                chain.append(
                    f"突破失败，{result['fail_msg']}"
                    f"修为：{result['cultivation']}/{result['needed']}　"
                    f"寿元：{result['lifespan']}年"
                )
            break

    successes = [c for c in chain if "➜" in c]
    fail_line = next((c for c in chain if "➜" not in c), "")

    return {
        "success": True,
        "chain": chain,
        "successes": successes,
        "fail_line": fail_line
    }


async def _pill_breakthrough(
    discord_id: str, use_pill: bool, *,
    pill: str, rate_fn, from_realm: str, target_realm: str,
) -> dict:
    """筑基 / 凝丹 / 化婴三道大关共用的「可吃丹」突破。

    顺序遵循 CONVENTIONS #7：校验 → 扣丹 → 掷骰 → 落库，且**扣丹与落库在同一个事务**：
    落库时发现状态已变（连点），整体回滚，丹药一并退回，不会白吞。
    丹药用 `consume_item` 的返回值判断有没有 —— 它本身是条件写；
    不要先 has_item 再扣，两步之间丹药可能已被另一次点击拿走。

    失败的惩罚与普通突破一致（`roll_failure_outcome` + `apply_failure`）。
    """
    async with AsyncSessionLocal() as session:
        player = await session.get(Player, discord_id)
        if not player:
            return {"success": False, "message": "角色不存在"}

        player_dict = {c.key: getattr(player, c.key) for c in player.__table__.columns}

    if player_dict["realm"] != from_realm:
        return {"success": False, "message": f"当前境界无需此关（{player_dict['realm']}）"}
    if player_dict["cultivation"] < cultivation_needed(from_realm):
        return {"success": False, "message": "修为未圆满"}

    async with AsyncSessionLocal() as session:
        if use_pill and not await consume_item(session, discord_id, pill, 1):
            await session.rollback()
            return {"success": False, "message": f"背包中无{pill}"}

        rate = rate_fn(player_dict, use_pill=use_pill)
        success = random.random() * 100 < rate

        if success:
            settled = await _settle_success(session, discord_id, player_dict, target_realm)
            if isinstance(settled, str):
                return {"success": False, "message": settled}
            await session.commit()
            new_lifespan, new_lifespan_max, lifespan_gain = settled

            return {
                "success": True,
                "breakthrough": True,
                "name": player_dict["name"],
                "old_realm": from_realm,
                "new_realm": target_realm,
                "lifespan": new_lifespan,
                "lifespan_max": new_lifespan_max,
                "lifespan_gain": lifespan_gain,
            }

        new_cultivation, new_lifespan, fail_msg = apply_failure(
            player_dict["cultivation"], player_dict["lifespan"], roll_failure_outcome(from_realm)
        )
        settled = await _settle_failure(session, discord_id, player_dict, new_cultivation, new_lifespan)
        if isinstance(settled, str):
            return {"success": False, "message": settled}
        await session.commit()

    return {
        "success": True,
        "breakthrough": False,
        "name": player_dict["name"],
        "fail_msg": fail_msg,
        "cultivation": new_cultivation,
        "lifespan": settled["lifespan"],
        "needed": cultivation_needed(from_realm),
        "is_dead": settled["is_dead"],
        "saved_by_charm": settled["saved_by_charm"],
    }


async def handle_zhuji_breakthrough(discord_id: str, use_pill: bool) -> dict:
    from utils.items import calc_zhuji_breakthrough_rate
    return await _pill_breakthrough(
        discord_id, use_pill, pill="筑基丹", rate_fn=calc_zhuji_breakthrough_rate,
        from_realm="炼气期10层", target_realm="筑基期1层",
    )


async def handle_ningdan_breakthrough(discord_id: str, use_pill: bool) -> dict:
    from utils.items.breakthrough import calc_ningdan_breakthrough_rate
    return await _pill_breakthrough(
        discord_id, use_pill, pill="凝丹丹", rate_fn=calc_ningdan_breakthrough_rate,
        from_realm="筑基期10层", target_realm="结丹期初期",
    )


async def handle_huaying_breakthrough(discord_id: str, use_pill: bool) -> dict:
    from utils.items.breakthrough import calc_huaying_breakthrough_rate
    return await _pill_breakthrough(
        discord_id, use_pill, pill="化婴丹", rate_fn=calc_huaying_breakthrough_rate,
        from_realm="结丹期后期", target_realm="元婴期初期",
    )
