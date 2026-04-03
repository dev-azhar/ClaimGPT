"""
FastAPI auth middleware: JWT verification + RBAC.

Integrates with Keycloak (or any OIDC provider) via JWKS endpoint.
Falls back to HS256 shared-secret for service-to-service calls.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .models import TokenPayload, UserRole

logger = logging.getLogger("auth")

_bearer_scheme = HTTPBearer(auto_error=False)

# ------------------------------------------------------------------ config
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() == "true"
JWKS_URL = os.getenv("AUTH_JWKS_URL", "")  # e.g. http://keycloak:8080/realms/claimgpt/protocol/openid-connect/certs
JWT_ALGORITHM = os.getenv("AUTH_JWT_ALGORITHM", "RS256")
JWT_SECRET = os.getenv("AUTH_JWT_SECRET", "")  # fallback HS256 for service-to-service
JWT_AUDIENCE = os.getenv("AUTH_JWT_AUDIENCE", "claimgpt")
JWT_ISSUER = os.getenv("AUTH_JWT_ISSUER", "")


# ------------------------------------------------------------------ JWKS cache
@lru_cache(maxsize=1)
def _fetch_jwks() -> dict:
    """Fetch JWKS from the OIDC provider (cached in-process)."""
    if not JWKS_URL:
        return {}
    try:
        resp = httpx.get(JWKS_URL, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("Failed to fetch JWKS from %s", JWKS_URL)
        return {}


def _decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT token."""
    options = {"verify_aud": False}

    # Try RS256 via JWKS first
    if JWKS_URL:
        jwks = _fetch_jwks()
        if jwks:
            try:
                payload = jwt.decode(
                    token,
                    jwks,
                    algorithms=[JWT_ALGORITHM],
                    options=options,
                )
                return TokenPayload(**payload)
            except JWTError:
                pass

    # Fallback: HS256 shared secret (service-to-service)
    if JWT_SECRET:
        try:
            payload = jwt.decode(
                token,
                JWT_SECRET,
                algorithms=["HS256"],
                options=options,
            )
            return TokenPayload(**payload)
        except JWTError:
            pass

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
    )


# ------------------------------------------------------------------ FastAPI dependencies

async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> TokenPayload | None:
    """
    Extract and decode the Bearer token.
    Returns None when auth is disabled (dev mode).
    """
    if not AUTH_ENABLED:
        return None

    if not creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
        )

    return _decode_token(creds.credentials)


def require_role(*roles: str | UserRole):
    """
    Dependency factory: require the caller to have at least one of the listed roles.

    Usage:
        @app.post("/admin/...", dependencies=[Depends(require_role("admin"))])
    """
    async def _check(user: TokenPayload | None = Depends(get_current_user)):
        if not AUTH_ENABLED:
            return  # skip in dev
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        role_strs = [r.value if isinstance(r, UserRole) else r for r in roles]
        if not any(user.has_role(r) for r in role_strs):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {role_strs}",
            )
    return _check


# ------------------------------------------------------------------ Starlette middleware (optional)

class AuthMiddleware:
    """
    ASGI middleware that validates JWT on every request (except health checks).
    Use as: app.add_middleware(AuthMiddleware)
    """

    SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not AUTH_ENABLED:
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if path in self.SKIP_PATHS:
            return await self.app(scope, receive, send)

        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()

        if not auth_header.startswith("Bearer "):
            from starlette.responses import JSONResponse
            resp = JSONResponse({"detail": "Missing authorization"}, status_code=401)
            return await resp(scope, receive, send)

        token = auth_header[7:]
        try:
            _decode_token(token)
        except HTTPException:
            from starlette.responses import JSONResponse
            resp = JSONResponse({"detail": "Invalid token"}, status_code=401)
            return await resp(scope, receive, send)

        return await self.app(scope, receive, send)
