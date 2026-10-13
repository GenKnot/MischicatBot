"""bot_memories：机器人对真人的记忆（U1·关系记忆）

幂等：全新库的基线已按当前 ORM 建表。

Revision ID: b8e4c2a61d90
Revises: a7d3e51b9c28
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa


revision = "b8e4c2a61d90"
down_revision = "a7d3e51b9c28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "bot_memories" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "bot_memories",
            sa.Column("player_id", sa.String(), primary_key=True),
            sa.Column("bot_id", sa.String(), primary_key=True),
            sa.Column("kind", sa.String(), primary_key=True),
            sa.Column("detail", sa.String(), primary_key=True, server_default=sa.text("''")),
            sa.Column("count", sa.Integer(), server_default=sa.text("0")),
            sa.Column("extra", sa.String(), server_default=sa.text("''")),
            sa.Column("first_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("prev_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("last_at", sa.Float(), server_default=sa.text("0")),
        )


def downgrade() -> None:
    if "bot_memories" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("bot_memories")
