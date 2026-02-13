"""initial schema baseline

Revision ID: 20260207_0001
Revises:
Create Date: 2026-02-07 20:00:00
"""

from __future__ import annotations

from alembic import op

try:
    from transcriptionist_v3.infrastructure.database.models import Base
except ModuleNotFoundError:
    from infrastructure.database.models import Base


# revision identifiers, used by Alembic.
revision = "20260207_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)

