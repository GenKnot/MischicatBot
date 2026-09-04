"""baseline: 现有 schema

这是接入 Alembic 时的基线，代表「2026-09-03 的 schema」。

对全新库：按 ORM 模型建出全部表。
对已有库：create_all 带 checkfirst，已存在的表跳过，等于空操作。

历史包袱：utils/db.py 里那 41 条 ALTER（`_migrate`）暂时保留，让还没升级过的
老库也能补齐字段。**它已经冻结，不要再往里加新的** —— 从这条基线之后，
所有 schema 变更都写成新的 alembic revision。

Revision ID: 0001_baseline
Revises:
"""
from alembic import op

from utils.db_async import Base

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # 不提供回退：这条基线会把整个库删掉，不是任何人想要的结果
    raise NotImplementedError("baseline 不支持 downgrade")
