"""Password hashing and JWT creation/verification. No database access here."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from freight_intel.config import get_settings

# argon2id with the library's recommended parameters. It is deliberately slow
# and memory-hungry, so stolen hashes are expensive to brute-force.
_hasher = PasswordHasher()

# A real hash of a throwaway string. verify_password() checks against it when
# the email is unknown, so "no such user" costs the same time as "wrong
# password" and an attacker can't tell the two apart by timing.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return password_hash is not None


def create_access_token(*, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id),  # who
        "tid": str(tenant_id),  # which tenant: the ONLY source of tenant identity
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Return the claims, or raise jwt.PyJWTError if the token is not valid.

    `algorithms=[...]` is pinned: without it a forged token claiming
    alg=none could be accepted. `require` rejects tokens missing key claims.
    Expiry is checked automatically.
    """
    settings = get_settings()
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "tid"]},
    )
