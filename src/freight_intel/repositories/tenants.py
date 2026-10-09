"""All database access for tenants. Only ORM calls, no business rules."""
import uuid

from sqlalchemy.orm import Session

from freight_intel.models import Tenant


def create(session: Session, *, tenant_id: uuid.UUID, name: str) -> Tenant:
    tenant = Tenant(id=tenant_id, name=name)
    session.add(tenant)  # stage the INSERT
    session.flush()  # send it now, so constraint errors surface here
    return tenant
