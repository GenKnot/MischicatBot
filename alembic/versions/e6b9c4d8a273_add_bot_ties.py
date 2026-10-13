"""bot_ties：机器人之间（以及真人与机器人之间）的关系网（U1·江湖百态 P2）

一对人一行（a_id < b_id）。种类：相识 / 朋友 / 结拜 / 同门 / 仇敌。
幂等：全新库的基线已按当前 ORM 建表。

Revision ID: e6b9c4d8a273
Revises: d5a8b3c7f162
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa


revision = "e6b9c4d8a273"
down_revision = "d5a8b3c7f162"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "bot_ties" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "bot_ties",
            sa.Column("a_id", sa.String(), primary_key=True),
            sa.Column("b_id", sa.String(), primary_key=True),
            sa.Column("kind", sa.String(), nullable=False, server_default=sa.text("'相识'")),
            sa.Column("strength", sa.Integer(), server_default=sa.text("0")),
            sa.Column("since", sa.Float(), server_default=sa.text("0")),
            sa.Column("last_event", sa.Float(), server_default=sa.text("0")),
            sa.Column("bond_id", sa.String(), server_default=sa.text("''")),
            sa.Column("note", sa.String(), server_default=sa.text("''")),
        )
        op.create_index("ix_bot_ties_b_id", "bot_ties", ["b_id"])


def downgrade() -> None:
    if "bot_ties" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("bot_ties")
