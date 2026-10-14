"""Associate GitHub App installations with one kodai organization."""
from alembic import op
import sqlalchemy as sa


revision = "0002_github_org_installation"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "installations",
        sa.Column("organization_id", sa.Uuid(as_uuid=False), nullable=True),
    )
    op.create_foreign_key(
        "fk_installations_organization_id_organizations",
        "installations",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_installations_organization_id",
        "installations",
        ["organization_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_installations_organization_id", table_name="installations")
    op.drop_constraint(
        "fk_installations_organization_id_organizations",
        "installations",
        type_="foreignkey",
    )
    op.drop_column("installations", "organization_id")
