"""bot_world_state 表 + bot_personality.settled_day：机器人每日结算（U1）

· `bot_world_state(key, value)`：机器人世界的少量全局状态（目标人数、补员日）；
· `bot_personality.settled_day`：这个机器人最后一次每日结算是哪天（'YYYY-MM-DD'），结算靠它保证每天只结一次、崩了能续。

幂等：全新库的基线已按当前 ORM 建表。

Revision ID: 9c4f7a1e5b83
Revises: 7b1c4e9d2a60
Create Date: 2026-10-10
"""
from alembic import op
import sqlalchemy as sa


revision = "9c4f7a1e5b83"
down_revision = "7b1c4e9d2a60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "bot_world_state" not in insp.get_table_names():
        op.create_table(
            "bot_world_state",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("value", sa.String(), nullable=False, server_default=sa.text("''")),
        )
    if "settled_day" not in {c["name"] for c in insp.get_columns("bot_personality")}:
        with op.batch_alter_table("bot_personality") as batch:
            batch.add_column(sa.Column("settled_day", sa.String(), server_default=sa.text("''")))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "settled_day" in {c["name"] for c in insp.get_columns("bot_personality")}:
        with op.batch_alter_table("bot_personality") as batch:
            batch.drop_column("settled_day")
    if "bot_world_state" in insp.get_table_names():
        op.drop_table("bot_world_state")
