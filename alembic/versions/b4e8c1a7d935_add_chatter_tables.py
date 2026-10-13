"""chatter_state / chatter_pair / chatter_queue：机器人主动搭话（U1·江湖百态 P5）

chatter_state：每个玩家当天收到几条、是否屏蔽；chatter_pair：某机器人最近一次主动找某玩家说话的时间（冷却）；
chatter_queue：延迟发送的搭话（突破道贺、公共事件前后、冲突后放话），后台循环到点发。
幂等：全新库的基线已按当前 ORM 建表。

Revision ID: b4e8c1a7d935
Revises: a9d2e7f3c416
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa


revision = "b4e8c1a7d935"
down_revision = "a9d2e7f3c416"
branch_labels = None
depends_on = None


def upgrade() -> None:
    names = sa.inspect(op.get_bind()).get_table_names()
    if "chatter_state" not in names:
        op.create_table(
            "chatter_state",
            sa.Column("player_id", sa.String(), primary_key=True),
            sa.Column("day", sa.String(), server_default=sa.text("''")),
            sa.Column("count", sa.Integer(), server_default=sa.text("0")),
            sa.Column("muted", sa.Boolean(), server_default=sa.text("0")),
        )
    if "chatter_pair" not in names:
        op.create_table(
            "chatter_pair",
            sa.Column("player_id", sa.String(), primary_key=True),
            sa.Column("bot_id", sa.String(), primary_key=True),
            sa.Column("last_at", sa.Float(), server_default=sa.text("0")),
        )
    if "chatter_queue" not in names:
        op.create_table(
            "chatter_queue",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("player_id", sa.String(), nullable=False),
            sa.Column("speaker_id", sa.String(), nullable=False),
            sa.Column("scene", sa.String(), nullable=False),
            sa.Column("fmt", sa.Text(), server_default=sa.text("'{}'")),
            sa.Column("due_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("sent_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("outcome", sa.String(), server_default=sa.text("''")),
        )
        op.create_index("ix_chatter_queue_due_at", "chatter_queue", ["due_at"])


def downgrade() -> None:
    names = sa.inspect(op.get_bind()).get_table_names()
    for t in ("chatter_queue", "chatter_pair", "chatter_state"):
        if t in names:
            op.drop_table(t)
