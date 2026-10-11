"""bot_personality / bot_relations：机器人的性格偏好与真人 × 机器人的好感度（U1「江湖百态」）

全新库的基线（0001）按当前 ORM 建表，已经带这两张表，所以先看表在不在，不在才建（同 3a1f0c5be7d2）。

Revision ID: 5d2e8a41c9b7
Revises: 3a1f0c5be7d2
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa


revision = "5d2e8a41c9b7"
down_revision = "3a1f0c5be7d2"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _tables()
    if "bot_personality" not in existing:
        op.create_table(
            "bot_personality",
            sa.Column("bot_id", sa.String(), primary_key=True),
            sa.Column("archetype", sa.String(), nullable=False),
            sa.Column("kindness", sa.Integer(), server_default=sa.text("50")),
            sa.Column("greed", sa.Integer(), server_default=sa.text("50")),
            sa.Column("pride", sa.Integer(), server_default=sa.text("50")),
            sa.Column("talk", sa.Integer(), server_default=sa.text("50")),
            sa.Column("likes", sa.Text(), server_default=sa.text("'{}'")),
            sa.Column("dislikes", sa.Text(), server_default=sa.text("'{}'")),
        )
    if "bot_relations" not in existing:
        op.create_table(
            "bot_relations",
            sa.Column("player_id", sa.String(), primary_key=True),
            sa.Column("bot_id", sa.String(), primary_key=True),
            sa.Column("favor", sa.Integer(), server_default=sa.text("0")),
            sa.Column("last_interact", sa.Float(), server_default=sa.text("0")),
            sa.Column("day", sa.String(), server_default=sa.text("''")),
            sa.Column("gifts_today", sa.Integer(), server_default=sa.text("0")),
            sa.Column("gift_gain_today", sa.Integer(), server_default=sa.text("0")),
            sa.Column("chatted_today", sa.Integer(), server_default=sa.text("0")),
        )


def downgrade() -> None:
    existing = _tables()
    for name in ("bot_relations", "bot_personality"):
        if name in existing:
            op.drop_table(name)
