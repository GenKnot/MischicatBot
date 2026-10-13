"""bot_requests：机器人对熟人的请求 / 委托（借灵石、借物品、送信、陪着采集……）（U1·江湖百态）

幂等：全新库的基线已按当前 ORM 建表。

Revision ID: c5f9d2b8e147
Revises: b4e8c1a7d935
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa


revision = "c5f9d2b8e147"
down_revision = "b4e8c1a7d935"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "bot_requests" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "bot_requests",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("bot_id", sa.String(), nullable=False),
            sa.Column("player_id", sa.String(), nullable=False),
            sa.Column("template", sa.String(), nullable=False),
            sa.Column("state", sa.String(), server_default=sa.text("'offered'")),
            sa.Column("params", sa.Text(), server_default=sa.text("'{}'")),
            sa.Column("created_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("due_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("updated_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("note", sa.String(), server_default=sa.text("''")),
        )
        op.create_index("ix_bot_requests_player_id", "bot_requests", ["player_id"])


def downgrade() -> None:
    if "bot_requests" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("bot_requests")
