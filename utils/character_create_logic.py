"""创建角色的落库：新玩家新建，或坐化的玩家重置（轮回）。

文字创建（cogs/character.py）与按钮创建（utils/views/character_create.py）共用这一份 ——
以前各抄了一大段，改一处忘另一处就会出现两种创建方式结果不同（ISSUES.md B31）。

提交是**原子的**：只有「没有这个玩家」或「玩家已坐化」时才会写入，否则返回 None。
以前先 `get_player` 检查再写，文字流程和按钮面板同时走完（或同一面板点两次）会两边都越过检查，
后一个新增同主键直接 IntegrityError（B32）。
"""

import random
import time

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from utils.character import REALM_LIFESPAN, calc_stats, roll_spirit_root
from utils.death_rebirth_logic import calculate_rebirth_bonus
from utils.db_async import AsyncSessionLocal, Player
from utils.world import CITIES

_STATS = ("comprehension", "physique", "fortune", "bone", "soul")


async def commit_character(uid: str, name: str, gender: str, answers: dict) -> dict | None:
    """创建（或轮回重置）角色。成功返回结果摘要，玩家已存活则返回 None（什么都没写）。"""
    stats = calc_stats(dict(answers))
    spirit_root, root_type = roll_spirit_root()
    lifespan = REALM_LIFESPAN["炼气期"]
    now = time.time()
    city = random.choice(CITIES)["name"]

    async with AsyncSessionLocal() as session:
        old = await session.get(Player, uid)
        if old is not None and not old.is_dead:
            return None

        bonus: dict = {}
        if old is not None:
            if old.sect == "仙葬谷" or old.has_bahongchen:
                bonus = calculate_rebirth_bonus({c.key: getattr(old, c.key) for c in old.__table__.columns})
            values = {k: stats[k] + bonus.get(k, 0) for k in _STATS}
            values.update(
                name=name, gender=gender, spirit_root=spirit_root, spirit_root_type=root_type,
                lifespan=lifespan, lifespan_max=lifespan, spirit_stones=stats["spirit_stones"],
                cultivation=0, realm="炼气期1层", cultivating_until=None, cultivating_years=None,
                is_dead=False, is_virgin=True, sect=None, sect_rank=None, techniques="[]",
                dual_partner_id=None, cultivation_overflow=0, current_city=city,
                explore_count=0, explore_reset_year=0, reputation=0, cave=None,
                active_quest=None, quest_due=None, gathering_until=None, gathering_type=None,
                created_at=now, last_active=now,
            )
            # 条件 UPDATE：并发时只有一个提交能把「已坐化」改成「存活」
            res = await session.execute(
                update(Player).where(Player.discord_id == uid, Player.is_dead == True).values(**values)  # noqa: E712
            )
            if res.rowcount != 1:
                await session.rollback()
                return None
        else:
            session.add(Player(
                discord_id=uid, name=name, gender=gender,
                spirit_root=spirit_root, spirit_root_type=root_type,
                lifespan=lifespan, lifespan_max=lifespan, spirit_stones=stats["spirit_stones"],
                created_at=now, last_active=now, current_city=city,
                **{k: stats[k] for k in _STATS},
            ))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            # 只有「并发的另一次提交先插入了同一个玩家」才算被抢先；别的约束错误（NOT NULL 等）是真 bug，不能吞掉
            if await session.get(Player, uid) is not None:
                return None
            raise

    return {"name": name, "gender": gender, "starting_city": city, "spirit_root": spirit_root,
            "root_type": root_type, "lifespan": lifespan, "stats": stats, "rebirth_bonus": bonus}
