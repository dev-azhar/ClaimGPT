"""Auth data models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class UserRole(str, Enum):
    ADMIN = "admin"
    REVIEWER = "reviewer"
    SUBMITTER = "submitter"
    VIEWER = "viewer"
    SERVICE = "service"


class TokenPayload(BaseModel):
    """Decoded JWT token claims (Keycloak-compatible)."""
    sub: str  # subject (user ID)
    email: str | None = None
    preferred_username: str | None = None
    realm_access: dict | None = None
    resource_access: dict | None = None
    exp: int | None = None
    iat: int | None = None
    iss: str | None = None

    @property
    def roles(self) -> list[str]:
        """Extract realm roles from Keycloak token structure."""
        if self.realm_access and "roles" in self.realm_access:
            return self.realm_access["roles"]
        return []

    def has_role(self, role: str | UserRole) -> bool:
        role_str = role.value if isinstance(role, UserRole) else role
        return role_str in self.roles
