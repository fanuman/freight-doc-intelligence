"""human review: reviewed/rejected statuses and the reviews audit table

Revision ID: 0004
Revises: 0003

A person can now settle a document the pipeline could not. That adds two statuses and a table
that records who decided what.

  documents.status   gains 'rejected'  (a person said: this document is not usable)
  extractions.status gains 'reviewed'  (a person approved or corrected the reading)
  reviews            new, append-only: one row per decision, never updated or replaced

`reviews` follows the rules of the other tenant tables: tenant_id on every row, the same
row-level-security policy, and COMPOSITE foreign keys (tenant_id, id) so a review can never
point at another tenant's document or user. The reviewer link needs users to offer such a
key, so this migration adds a unique constraint on users (tenant_id, id). The default
privileges from docker/postgres/init-app-role.sh already give the app role access to the
new table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_DOCUMENT_STATUSES = "'uploaded', 'processing', 'needs_review', 'processed', 'failed'"
NEW_DOCUMENT_STATUSES = "'uploaded', 'processing', 'needs_review', 'processed', 'failed', 'rejected'"


def upgrade() -> None:
    """Upgrade schema."""
    # A CHECK constraint cannot be edited: drop it and create the longer one.
    op.drop_constraint("documents_status_check", "documents", type_="check")
    op.create_check_constraint("documents_status_check", "documents", f"status IN ({NEW_DOCUMENT_STATUSES})")
    op.drop_constraint("extractions_status_check", "extractions", type_="check")
    op.create_check_constraint("extractions_status_check", "extractions", "status IN ('ok', 'needs_review', 'reviewed')")

    # Lets reviews point at users by (tenant_id, id) together.
    op.create_unique_constraint("users_tenant_id_id_key", "users", ["tenant_id", "id"])

    op.create_table(
        "reviews",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("corrected_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("action IN ('approve', 'correct', 'reject')", name="reviews_action_check"),
        # Corrected values are stored with a 'correct' decision, and only with that one.
        sa.CheckConstraint("(action = 'correct') = (corrected_data IS NOT NULL)", name="reviews_corrected_data_check"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"], ["documents.tenant_id", "documents.id"],
            name="reviews_document_fk", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewer_id"], ["users.tenant_id", "users.id"],
            name="reviews_reviewer_fk",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("reviews_document_idx", "reviews", ["document_id", "created_at"], unique=False)

    op.execute("ALTER TABLE reviews ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON reviews "
        "USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("reviews")  # also drops its index, policy and constraints
    op.drop_constraint("users_tenant_id_id_key", "users", type_="unique")

    # The old constraints do not know the new values, so move those rows to the closest old one first.
    op.execute("UPDATE documents SET status = 'failed' WHERE status = 'rejected'")
    op.execute("UPDATE extractions SET status = 'ok' WHERE status = 'reviewed'")
    op.drop_constraint("extractions_status_check", "extractions", type_="check")
    op.create_check_constraint("extractions_status_check", "extractions", "status IN ('ok', 'needs_review')")
    op.drop_constraint("documents_status_check", "documents", type_="check")
    op.create_check_constraint("documents_status_check", "documents", f"status IN ({OLD_DOCUMENT_STATUSES})")
