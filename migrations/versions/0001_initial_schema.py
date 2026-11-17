"""Create the initial Lifeline projections and append-only event tables."""

from alembic import op

from services.api import models  # noqa: F401
from services.api.db import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent so existing M0 databases containing only `events` can be upgraded in place.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
