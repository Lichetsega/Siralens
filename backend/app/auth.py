"""
Authentication boundary.

This is the only module that knows tokens come from Supabase. The rest of the
app depends on `get_current_user` and receives our own `User` object, so the
auth provider can be swapped later by changing this file only.
"""
from dataclasses import dataclass
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import Settings, get_settings

AUTH_PROVIDER = "supabase"
_bearer = HTTPBearer(auto_error=False)
_jwks_client: PyJWKClient | None = None


@dataclass(frozen=True)
class AuthClaims:
    subject: str
    email: str | None


@dataclass(frozen=True)
class User:
    """Our own user. Every other table references `id`, never the provider's ID."""

    id: UUID
    email: str | None
    display_name: str | None
    preferred_language: str
    consent_at: object | None


def _unauthorized(detail: str = "Invalid or expired token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _get_jwks_client(settings: Settings) -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
        )
    return _jwks_client


def verify_token(token: str, settings: Settings) -> AuthClaims:
    """Verify a Supabase access token and return its claims. Raises 401 on any failure."""
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg == "HS256":  # legacy shared-secret projects
            if not settings.supabase_jwt_secret:
                raise _unauthorized("HS256 token but no JWT secret configured")
            key, algorithms = settings.supabase_jwt_secret, ["HS256"]
        elif alg in ("ES256", "RS256"):  # asymmetric signing keys
            if not settings.supabase_url:
                raise _unauthorized("SUPABASE_URL not configured")
            key = _get_jwks_client(settings).get_signing_key_from_jwt(token).key
            algorithms = [alg]
        else:
            raise _unauthorized("Unsupported token algorithm")

        payload = jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience=settings.supabase_jwt_audience,
            options={"require": ["exp", "sub"]},
        )
    except HTTPException:
        raise
    except jwt.PyJWTError:
        raise _unauthorized()
    return AuthClaims(subject=payload["sub"], email=payload.get("email"))


_UPSERT_USER = """
insert into users (auth_provider, auth_subject, email)
values (%s, %s, %s)
on conflict (auth_provider, auth_subject)
do update set email = coalesce(excluded.email, users.email), last_seen_at = now()
returning id, email, display_name, preferred_language, consent_at
"""


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> User:
    if creds is None:
        raise _unauthorized("Missing bearer token")
    claims = verify_token(creds.credentials, settings)
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(_UPSERT_USER, (AUTH_PROVIDER, claims.subject, claims.email))
        row = await cur.fetchone()
    return User(**row)
