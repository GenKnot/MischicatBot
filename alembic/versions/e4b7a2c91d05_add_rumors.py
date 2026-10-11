"""rumors / rumor_optout：江湖传闻（U1）

· `rumors`：传闻本体（保留 7 天），频道广播按 `broadcast_at` 记谁播过；
· `rumor_optout`：关闭了『我的事迹进传闻』的真人。

幂等：全新库的基线已按当前 ORM 建表。

Revision ID: e4b7a2c91d05
Revises: d1a8c5e30f72
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa


revision = "e4b7a2c91d05"
down_revision = "d1a8c5e30f72"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "rumors" not in tables:
        op.create_table(
            "rumors",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.Float(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("score", sa.Integer(), server_default=sa.text("0")),
            sa.Column("subject_id", sa.String(), nullable=False),
            sa.Column("subject_name", sa.String(), nullable=False),
            sa.Column("is_human", sa.Boolean(), server_default=sa.text("0")),
            sa.Column("negative", sa.Boolean(), server_default=sa.text("0")),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("city", sa.String(), server_default=sa.text("''")),
            sa.Column("broadcast_at", sa.Float(), server_default=sa.text("0")),
        )
    if "rumor_optout" not in tables:
        op.create_table("rumor_optout", sa.Column("player_id", sa.String(), primary_key=True))


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in ("rumor_optout", "rumors"):
        if name in tables:
            op.drop_table(name)
