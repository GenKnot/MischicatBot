"""bot_raids 表 + bot_personality.home_city：劫杀机器人（U1）

· `bot_raids(player_id, day, robs, kills)`：真人每天打劫 / 击杀机器人的次数；
· `bot_personality.home_city`：机器人的常驻城市（去秘地历练后回这里）。

幂等：全新库的基线已按当前 ORM 建表。

Revision ID: d1a8c5e30f72
Revises: 9c4f7a1e5b83
Create Date: 2026-10-10
"""
from alembic import op
import sqlalchemy as sa


revision = "d1a8c5e30f72"
down_revision = "9c4f7a1e5b83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "bot_raids" not in insp.get_table_names():
        op.create_table(
            "bot_raids",
            sa.Column("player_id", sa.String(), primary_key=True),
            sa.Column("day", sa.String(), primary_key=True),
            sa.Column("robs", sa.Integer(), server_default=sa.text("0")),
            sa.Column("kills", sa.Integer(), server_default=sa.text("0")),
        )
    if "home_city" not in {c["name"] for c in insp.get_columns("bot_personality")}:
        with op.batch_alter_table("bot_personality") as batch:
            batch.add_column(sa.Column("home_city", sa.String(), server_default=sa.text("''")))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "home_city" in {c["name"] for c in insp.get_columns("bot_personality")}:
        with op.batch_alter_table("bot_personality") as batch:
            batch.drop_column("home_city")
    if "bot_raids" in insp.get_table_names():
        op.drop_table("bot_raids")
