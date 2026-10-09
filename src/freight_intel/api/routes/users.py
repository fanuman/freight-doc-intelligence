from fastapi import APIRouter, HTTPException, status

from freight_intel.api.deps import CurrentUserDep, DbSession
from freight_intel.repositories import users as users_repo
from freight_intel.schemas.user import MeResponse

router = APIRouter(tags=["users"])


@router.get("/me", response_model=MeResponse)
def me(current: CurrentUserDep, db: DbSession) -> MeResponse:
    """Who am I? A read this simple can call the repository directly;
    a service layer adds nothing until there is a rule to enforce."""
    user = users_repo.get_with_tenant(db, current.user_id)
    if user is None:
        # Valid token but the user no longer exists (deleted after it was issued).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return MeResponse(
        user_id=user.id,
        email=user.email,
        role=user.role,
        tenant_id=user.tenant_id,
        tenant_name=user.tenant.name,
    )
