"""HTTP layer for sign-up and login: parse the request, call a service, map errors."""
from fastapi import APIRouter, HTTPException, status

from freight_intel.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from freight_intel.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


# Plain `def`, not `async def`: our database driver is blocking, and FastAPI
# runs plain `def` routes in a thread pool so they don't freeze the server.
@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest) -> TokenResponse:
    try:
        token = auth_service.register(
            company_name=body.company_name, email=body.email, password=body.password
        )
    except auth_service.EmailAlreadyRegistered:
        # A 409 reveals that the email exists. That is the usual trade-off for
        # sign-up forms (users need the message); login stays generic.
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest) -> TokenResponse:
    try:
        token = auth_service.login(email=body.email, password=body.password)
    except auth_service.InvalidCredentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=token)
