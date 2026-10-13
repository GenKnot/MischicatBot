"""players.fame：知名度（和 reputation 道德声望分开）

名望影响一件事传多远（无名小卒的死讯没人知道；名动天下的人被杀会传遍全服），见 utils/fame.py。
幂等：全新库的基线已按当前 ORM 建表。

Revision ID: c3f9a7d2e851
Revises: b8e4c2a61d90
Create Date: 2026-10-12
"""
from alembic import op
import sqlalchemy as sa


revision = "c3f9a7d2e851"
down_revision = "b8e4c2a61d90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "fame" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("players")}:
        with op.batch_alter_table("players") as batch:
            batch.add_column(sa.Column("fame", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    if "fame" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("players")}:
        with op.batch_alter_table("players") as batch:
            batch.drop_column("fame")
