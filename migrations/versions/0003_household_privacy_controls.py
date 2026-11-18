"""Record household consent and registrar."""

from alembic import op
import sqlalchemy as sa

revision = "0003_household_privacy"
down_revision = "0002_risk_households"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("household_registrations")}
    if "registrar_id" not in columns:
        op.add_column("household_registrations", sa.Column("registrar_id", sa.String(length=26), nullable=False, server_default="unknown"))
    if "consent_at" not in columns:
        op.add_column("household_registrations", sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade() -> None:
    op.drop_column("household_registrations", "consent_at")
    op.drop_column("household_registrations", "registrar_id")
