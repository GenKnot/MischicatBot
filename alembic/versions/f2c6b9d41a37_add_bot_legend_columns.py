"""bot_personality 的天骄传记：称号 / 背景 / 在天花板上等了几天（U1·天骄的一生）

· `epithet`：称号；`backstory`：一句话背景（只有天骄有）；
· `capped_days`：连续顶在天花板上的天数（天骄顶够了日子就会飞升）。

幂等：全新库的基线已按当前 ORM 建表。

Revision ID: f2c6b9d41a37
Revises: e4b7a2c91d05
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa


revision = "f2c6b9d41a37"
down_revision = "e4b7a2c91d05"
branch_labels = None
depends_on = None

COLUMNS = [
    ("epithet", sa.String(), sa.text("''")),
    ("backstory", sa.Text(), sa.text("''")),
    ("capped_days", sa.Integer(), sa.text("0")),
]


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("bot_personality")}
    with op.batch_alter_table("bot_personality") as batch:
        for name, type_, default in COLUMNS:
            if name not in existing:
                batch.add_column(sa.Column(name, type_, server_default=default))


def downgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("bot_personality")}
    with op.batch_alter_table("bot_personality") as batch:
        for name, _, _ in COLUMNS:
            if name in existing:
                batch.drop_column(name)
