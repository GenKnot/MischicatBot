"""参与记录的 activity 改为非空

主键列可空时 SQLite 认为 NULL != NULL，同一个人同一个活动能插进多行。
用空串表示"没有具体活动"。

Revision ID: 2bc9369e4fc7
Revises: 0001_baseline
Create Date: 2026-09-03 19:53:41.958510
"""
from alembic import op
import sqlalchemy as sa


revision = '2bc9369e4fc7'
down_revision = '0001_baseline'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE public_event_participants SET activity = '' WHERE activity IS NULL")
    with op.batch_alter_table("public_event_participants") as batch:
        batch.alter_column(
            "activity", existing_type=sa.String(),
            nullable=False, server_default=sa.text("''"),
        )


def downgrade() -> None:
    with op.batch_alter_table("public_event_participants") as batch:
        batch.alter_column(
            "activity", existing_type=sa.String(),
            nullable=True, server_default=None,
        )
