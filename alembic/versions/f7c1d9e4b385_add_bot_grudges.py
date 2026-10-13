"""bot_grudges / player_enemies：仇恨账本（U1·江湖百态 P3）

bot_grudges：谁恨谁、为了谁、为什么（带原因文字）、轻重、蹲守窗口与续期。player_enemies：玩家前世的仇人记录（转世后还在）。
幂等：全新库的基线已按当前 ORM 建表。

Revision ID: f7c1d9e4b385
Revises: e6b9c4d8a273
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa


revision = "f7c1d9e4b385"
down_revision = "e6b9c4d8a273"
branch_labels = None
depends_on = None


def upgrade() -> None:
    names = sa.inspect(op.get_bind()).get_table_names()
    if "bot_grudges" not in names:
        op.create_table(
            "bot_grudges",
            sa.Column("holder_id", sa.String(), primary_key=True),
            sa.Column("target_id", sa.String(), primary_key=True),
            sa.Column("victim_id", sa.String(), primary_key=True),
            sa.Column("kind", sa.String(), server_default=sa.text("''")),
            sa.Column("reason", sa.String(), server_default=sa.text("''")),
            sa.Column("severity", sa.Integer(), server_default=sa.text("0")),
            sa.Column("events", sa.Integer(), server_default=sa.text("1")),
            sa.Column("state", sa.String(), server_default=sa.text("'active'")),
            sa.Column("style", sa.String(), server_default=sa.text("''")),
            sa.Column("stubborn", sa.Boolean(), server_default=sa.text("0")),
            sa.Column("created_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("known_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("window_until", sa.Float(), server_default=sa.text("0")),
            sa.Column("renewals", sa.Integer(), server_default=sa.text("0")),
            sa.Column("last_ambush_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("last_apology", sa.Float(), server_default=sa.text("0")),
        )
        op.create_index("ix_bot_grudges_target_id", "bot_grudges", ["target_id"])
    if "player_enemies" not in names:
        op.create_table(
            "player_enemies",
            sa.Column("player_id", sa.String(), primary_key=True),
            sa.Column("enemy_id", sa.String(), primary_key=True),
            sa.Column("life", sa.Integer(), primary_key=True, server_default=sa.text("1")),
            sa.Column("enemy_name", sa.String(), server_default=sa.text("''")),
            sa.Column("reason", sa.String(), server_default=sa.text("''")),
            sa.Column("since", sa.Float(), server_default=sa.text("0")),
        )


def downgrade() -> None:
    names = sa.inspect(op.get_bind()).get_table_names()
    for t in ("player_enemies", "bot_grudges"):
        if t in names:
            op.drop_table(t)
