"""players.is_bot：标记机器人修士（U1「江湖百态」的前置）

老玩家全部是真人，默认 0。机器人的 discord_id 以 `bot_` 开头（见 utils/bots.py）。

全新库的基线（0001）是按**当前**ORM 模型建表的，已经带这一列，所以这里先看列在不在，
不在才加 —— 否则全新库会撞 duplicate column。

Revision ID: 3a1f0c5be7d2
Revises: 2bc9369e4fc7
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa


revision = "3a1f0c5be7d2"
down_revision = "2bc9369e4fc7"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("players")}
    return "is_bot" in cols


def upgrade() -> None:
    if _has_column():
        return
    with op.batch_alter_table("players") as batch:
        batch.add_column(sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    if not _has_column():
        return
    with op.batch_alter_table("players") as batch:
        batch.drop_column("is_bot")
