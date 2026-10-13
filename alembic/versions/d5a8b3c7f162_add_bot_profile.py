"""bot_personality.profile：机器人的行为画像（JSON）

守序 / 冲动 / 义气 / 记仇 / 关系容量 / 偏离概率（utils/bot_profile.py）。老机器人为空，下次每日结算按种子补上。
幂等：全新库的基线已按当前 ORM 建表。

Revision ID: d5a8b3c7f162
Revises: c3f9a7d2e851
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa


revision = "d5a8b3c7f162"
down_revision = "c3f9a7d2e851"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "profile" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("bot_personality")}:
        with op.batch_alter_table("bot_personality") as batch:
            batch.add_column(sa.Column("profile", sa.Text(), server_default=sa.text("''")))


def downgrade() -> None:
    if "profile" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("bot_personality")}:
        with op.batch_alter_table("bot_personality") as batch:
            batch.drop_column("profile")
