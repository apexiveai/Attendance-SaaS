"""Create the application schema for new installations.

Revision ID: 20261022_baseline
Revises:
"""
from alembic import op

from app.main import Base
import app.operations  # noqa: F401
import app.subscriptions  # noqa: F401


revision = "20261022_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    raise RuntimeError(
        "The initial schema migration is forward-only; restore a tested backup "
        "or apply a corrective forward migration."
    )
