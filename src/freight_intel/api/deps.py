"""FastAPI dependencies: reusable pieces that routes ask for in their signature.

FastAPI calls these before the route runs and passes the result in.
(Django: middleware plus `request.user`.)
"""
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.orm import Session

from freight_intel.config import get_settings
from freight_intel.db import tenant_session
from freight_intel.pipeline.checkpoint import get_checkpointer
from freight_intel.pipeline.llm import LLM
from freight_intel.security import decode_access_token
from freight_intel.storage import LocalStorage, get_storage

# Reads "Authorization: Bearer <token>" and makes Swagger show an Authorize
# button. auto_error=False so we return our own 401 instead of its default.
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CurrentUser:
    """Turn the bearer token into a CurrentUser, or answer 401.

    The tenant comes from the *signed* token. Never from the request body,
    query string or headers a client controls.
    """
    if credentials is None:
        raise _unauthorized()
    try:
        claims = decode_access_token(credentials.credentials)
        return CurrentUser(
            user_id=uuid.UUID(claims["sub"]),
            tenant_id=uuid.UUID(claims["tid"]),
            role=claims.get("role", "member"),
        )
    except (jwt.PyJWTError, ValueError, KeyError):
        # Bad signature, expired, malformed, missing claims: one answer for all.
        raise _unauthorized()


def get_db(user: Annotated[CurrentUser, Depends(get_current_user)]) -> Iterator[Session]:
    """A database session already locked to the caller's tenant.

    Every route that touches data takes this dependency, so a route cannot
    forget to scope its queries: the database itself enforces it.
    """
    with tenant_session(user.tenant_id) as session:
        yield session


# Short aliases so route signatures stay readable.
CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]


@lru_cache
def _openai_llm() -> LLM:
    """One model client for the whole process, created on first use (so the API starts without an OpenAI key)."""
    from freight_intel.pipeline.llm import OpenAILLM
    from freight_intel.pipeline.tracing import configure_tracing

    settings = get_settings()
    configure_tracing()
    return OpenAILLM(settings.extraction_model, settings.openai_api_key)


def get_llm() -> LLM:
    """The model client. Answers 503 when no OpenAI key is configured, before any file is stored."""
    if not get_settings().openai_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Document reading is not configured on this server")
    return _openai_llm()


def get_saver() -> BaseCheckpointSaver:
    """Where paused reviews are kept. Tests replace this with an in-memory saver."""
    return get_checkpointer()


LLMDep = Annotated[LLM, Depends(get_llm)]
SaverDep = Annotated[BaseCheckpointSaver, Depends(get_saver)]
StorageDep = Annotated[LocalStorage, Depends(get_storage)]
