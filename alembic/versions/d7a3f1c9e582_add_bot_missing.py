"""bot_missing：机器人打听失踪朋友的调查（U1·江湖百态）

幂等：全新库的基线已按当前 ORM 建表。

Revision ID: d7a3f1c9e582
Revises: c5f9d2b8e147
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa


revision = "d7a3f1c9e582"
down_revision = "c5f9d2b8e147"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "bot_missing" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "bot_missing",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("seeker_id", sa.String(), nullable=False),
            sa.Column("missing_id", sa.String(), nullable=False),
            sa.Column("missing_name", sa.String(), server_default=sa.text("''")),
            sa.Column("culprit_id", sa.String(), nullable=False),
            sa.Column("culprit_name", sa.String(), server_default=sa.text("''")),
            sa.Column("kind", sa.String(), server_default=sa.text("'kill'")),
            sa.Column("rel", sa.String(), server_default=sa.text("''")),
            sa.Column("severity", sa.Integer(), server_default=sa.text("0")),
            sa.Column("reason", sa.String(), server_default=sa.text("''")),
            sa.Column("city", sa.String(), server_default=sa.text("''")),
            sa.Column("started_at", sa.Float(), server_default=sa.text("0")),
            sa.Column("progress", sa.Integer(), server_default=sa.text("0")),
            sa.Column("state", sa.String(), server_default=sa.text("'active'")),
            sa.Column("asked", sa.Text(), server_default=sa.text("'{}'")),
        )
        op.create_index("ix_bot_missing_seeker_id", "bot_missing", ["seeker_id"])


def downgrade() -> None:
    if "bot_missing" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("bot_missing")
