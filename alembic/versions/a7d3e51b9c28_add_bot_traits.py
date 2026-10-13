"""bot_personality.traits：机器人的说话特质（JSON）

内向外向 / 星座 / 出身 / 说话习惯 / 口头禅 / 嗜好 / 往事（utils/bot_traits.py）。老机器人为空，下次每日结算按种子补上。
幂等：全新库的基线已按当前 ORM 建表。

Revision ID: a7d3e51b9c28
Revises: f2c6b9d41a37
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa


revision = "a7d3e51b9c28"
down_revision = "f2c6b9d41a37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "traits" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("bot_personality")}:
        with op.batch_alter_table("bot_personality") as batch:
            batch.add_column(sa.Column("traits", sa.Text(), server_default=sa.text("''")))


def downgrade() -> None:
    if "traits" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("bot_personality")}:
        with op.batch_alter_table("bot_personality") as batch:
            batch.drop_column("traits")
