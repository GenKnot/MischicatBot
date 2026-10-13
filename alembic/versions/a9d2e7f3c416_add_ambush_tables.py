"""bot_encounters / player_ambush：拦路遭遇（U1·江湖百态 P4）

bot_encounters：一次拦路的状态（选择中 / 交涉中 / 已结束），重启后靠它收尾；player_ambush：每个玩家最近一次被拦的时间和保护期。
幂等：全新库的基线已按当前 ORM 建表。

Revision ID: a9d2e7f3c416
Revises: f7c1d9e4b385
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa


revision = "a9d2e7f3c416"
down_revision = "f7c1d9e4b385"
branch_labels = None
depends_on = None


def upgrade() -> None:
    names = sa.inspect(op.get_bind()).get_table_names()
    if "bot_encounters" not in names:
        op.create_table(
            "bot_encounters",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("target_id", sa.String(), nullable=False),
            sa.Column("leader_id", sa.String(), nullable=False),
            sa.Column("companions", sa.Text(), server_default=sa.text("'[]'")),
            sa.Column("rescuer_id", sa.String(), server_default=sa.text("''")),
            sa.Column("victim_id", sa.String(), server_default=sa.text("''")),
            sa.Column("reason", sa.String(), server_default=sa.text("''")),
            sa.Column("severity", sa.Integer(), server_default=sa.text("0")),
            sa.Column("context", sa.String(), server_default=sa.text("''")),
            sa.Column("stage", sa.String(), server_default=sa.text("'choose'")),
            sa.Column("created_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("expires_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("channel_id", sa.String(), server_default=sa.text("''")),
            sa.Column("message_id", sa.String(), server_default=sa.text("''")),
            sa.Column("price", sa.Integer(), server_default=sa.text("0")),
            sa.Column("result", sa.String(), server_default=sa.text("''")),
        )
        op.create_index("ix_bot_encounters_target_id", "bot_encounters", ["target_id"])
    if "player_ambush" not in names:
        op.create_table(
            "player_ambush",
            sa.Column("player_id", sa.String(), primary_key=True),
            sa.Column("last_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("protect_until", sa.Float(), server_default=sa.text("0")),
            sa.Column("count", sa.Integer(), server_default=sa.text("0")),
        )


def downgrade() -> None:
    names = sa.inspect(op.get_bind()).get_table_names()
    for t in ("player_ambush", "bot_encounters"):
        if t in names:
            op.drop_table(t)
