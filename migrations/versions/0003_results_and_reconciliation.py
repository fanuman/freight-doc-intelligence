"""results and reconciliation: extractions, charges, reconciliations, discrepancies

Revision ID: 0003
Revises: 0002

Every new table carries tenant_id and the same row-level-security policy as `documents`.
Foreign keys between them are COMPOSITE (tenant_id, parent_id), so a child row can never
point at a parent owned by another tenant: Postgres checks foreign keys without applying
row-level security, so RLS alone would not stop that. The default privileges set up in
docker/postgres/init-app-role.sh already give the app role access to every table created
here, so no GRANT is needed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = ("extractions", "charges", "reconciliations", "discrepancies")

DISCREPANCY_TYPES = (
    "OVERCHARGE", "UNDERCHARGE", "UNQUOTED_CHARGE", "MISSING_CHARGE",
    "CURRENCY_MISMATCH", "EXPIRED_QUOTE", "ARITHMETIC_ERROR",
)


def upgrade() -> None:
    """Upgrade schema."""
    # Lets child tables point at documents by (tenant_id, id) together.
    op.create_unique_constraint("documents_tenant_id_id_key", "documents", ["tenant_id", "id"])

    op.create_table(
        "extractions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=True),
        sa.Column("quote_reference", sa.Text(), nullable=True),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=True),
        sa.Column("destination", sa.Text(), nullable=True),
        sa.Column("equipment", sa.Text(), nullable=True),
        sa.Column("total_minor", sa.BigInteger(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("doc_type IN ('quote', 'invoice')", name="extractions_doc_type_check"),
        sa.CheckConstraint("status IN ('ok', 'needs_review')", name="extractions_status_check"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"], ["documents.tenant_id", "documents.id"],
            name="extractions_document_fk", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", name="extractions_document_key"),
        sa.UniqueConstraint("tenant_id", "id", name="extractions_tenant_id_id_key"),
    )
    op.create_index("extractions_tenant_reference_idx", "extractions", ["tenant_id", "reference"], unique=False)
    op.create_index("extractions_tenant_route_idx", "extractions", ["tenant_id", "origin", "destination", "equipment"], unique=False)

    op.create_table(
        "charges",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("canonical_code", sa.Text(), nullable=False),
        sa.Column("raw_label", sa.Text(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("known", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "extraction_id"], ["extractions.tenant_id", "extractions.id"],
            name="charges_extraction_fk", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("charges_extraction_idx", "charges", ["extraction_id"], unique=False)

    op.create_table(
        "reconciliations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("quote_extraction_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_extraction_id", sa.Uuid(), nullable=False),
        sa.Column("match_method", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("total_variance_minor", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('clean', 'has_discrepancies')", name="reconciliations_status_check"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "quote_extraction_id"], ["extractions.tenant_id", "extractions.id"],
            name="reconciliations_quote_fk", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_extraction_id"], ["extractions.tenant_id", "extractions.id"],
            name="reconciliations_invoice_fk", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invoice_extraction_id", name="reconciliations_invoice_key"),
        sa.UniqueConstraint("tenant_id", "id", name="reconciliations_tenant_id_id_key"),
    )

    op.create_table(
        "discrepancies",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("reconciliation_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("charge_code", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("quoted_minor", sa.BigInteger(), nullable=True),
        sa.Column("invoiced_minor", sa.BigInteger(), nullable=True),
        sa.Column("variance_minor", sa.BigInteger(), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "type IN (" + ", ".join(f"'{t}'" for t in DISCREPANCY_TYPES) + ")",
            name="discrepancies_type_check",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reconciliation_id"], ["reconciliations.tenant_id", "reconciliations.id"],
            name="discrepancies_reconciliation_fk", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("discrepancies_reconciliation_idx", "discrepancies", ["reconciliation_id"], unique=False)

    # Same policy as `documents`: a row is visible and writable only inside its own tenant.
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = app_current_tenant()) WITH CHECK (tenant_id = app_current_tenant())"
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Children first. Dropping a table also drops its indexes, policies and constraints.
    for table in ("discrepancies", "reconciliations", "charges", "extractions"):
        op.drop_table(table)
    op.drop_constraint("documents_tenant_id_id_key", "documents", type_="unique")
