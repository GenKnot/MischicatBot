"""bot_personality.tier：机器人档位（炮灰 / 正常 / 天骄）

幂等：全新库的基线已按当前 ORM 建表、带这一列。

Revision ID: 7b1c4e9d2a60
Revises: 5d2e8a41c9b7
Create Date: 2026-10-10
"""
from alembic import op
import sqlalchemy as sa


revision = "7b1c4e9d2a60"
down_revision = "5d2e8a41c9b7"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    return "tier" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("bot_personality")}


def upgrade() -> None:
    if _has_column():
        return
    with op.batch_alter_table("bot_personality") as batch:
        batch.add_column(sa.Column("tier", sa.String(), server_default=sa.text("'正常'")))


def downgrade() -> None:
    if not _has_column():
        return
    with op.batch_alter_table("bot_personality") as batch:
        batch.drop_column("tier")
