from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe for load balancers. Deliberately does not touch the database."""
    return {"status": "ok"}
