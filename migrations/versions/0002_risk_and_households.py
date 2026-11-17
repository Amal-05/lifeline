"""Add risk map cells and encrypted household registrations."""

from alembic import op

revision = "0002_risk_households"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    from services.api.models import HouseholdRegistration, RiskCell

    HouseholdRegistration.__table__.create(bind, checkfirst=True)
    RiskCell.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    op.drop_table("household_registrations")
    op.drop_table("risk_cells")
