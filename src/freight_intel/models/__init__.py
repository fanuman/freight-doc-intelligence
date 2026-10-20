"""Import every model here so Base.metadata knows about all tables.

Alembic does `from freight_intel.models import Base`; importing this package
runs these imports, which registers the tables. A model that is never imported
is invisible to autogenerate.
"""
from freight_intel.models.base import Base
from freight_intel.models.document import Document, DocumentStatus, DocumentType
from freight_intel.models.extraction import Charge, Extraction
from freight_intel.models.reconciliation import Discrepancy, Reconciliation
from freight_intel.models.review import Review
from freight_intel.models.tenant import Tenant
from freight_intel.models.user import Role, User

__all__ = [
    "Base",
    "Charge",
    "Discrepancy",
    "Document",
    "DocumentStatus",
    "DocumentType",
    "Extraction",
    "Reconciliation",
    "Review",
    "Role",
    "Tenant",
    "User",
]
