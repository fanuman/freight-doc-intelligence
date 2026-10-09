"""auth support: login lookup function and tenant self-registration policy

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

from alembic import op

from freight_intel.config import get_settings

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Login happens before we know the tenant, and RLS hides every user until a
# tenant is set. This function is the single controlled gap: it runs with its
# owner's rights (SECURITY DEFINER), returns one user's credentials by exact
# email, and nothing else. search_path is pinned so nobody can shadow `users`.
AUTH_LOOKUP_FUNCTION = """
CREATE FUNCTION auth_get_user_by_email(p_email text)
RETURNS TABLE (id uuid, tenant_id uuid, password_hash text, role text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$
    SELECT u.id, u.tenant_id, u.password_hash, u.role
    FROM users u
    WHERE u.email = p_email
$$
"""

# A new company may create exactly one tenant row: the one whose id equals the
# tenant context of the current transaction. That lets registration be a plain
# ORM insert, with no privileged function.
TENANT_SELF_REGISTER_POLICY = """
CREATE POLICY tenant_self_register ON tenants
    FOR INSERT
    WITH CHECK (id = app_current_tenant())
"""


def upgrade() -> None:
    app_user = op.get_bind().dialect.identifier_preparer.quote(
        get_settings().app_db_user
    )
    op.execute(AUTH_LOOKUP_FUNCTION)
    # Functions are executable by everyone by default. Lock it to the app role.
    op.execute("REVOKE ALL ON FUNCTION auth_get_user_by_email(text) FROM PUBLIC")
    op.execute(
        f"GRANT EXECUTE ON FUNCTION auth_get_user_by_email(text) TO {app_user}"
    )
    op.execute(TENANT_SELF_REGISTER_POLICY)


def downgrade() -> None:
    op.execute("DROP POLICY tenant_self_register ON tenants")
    op.execute("DROP FUNCTION auth_get_user_by_email(text)")
