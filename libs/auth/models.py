"""Auth data models."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional
from uuid import UUID

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
    email: Optional[str] = None
    preferred_username: Optional[str] = None
    realm_access: Optional[dict] = None
    resource_access: Optional[dict] = None
    exp: Optional[int] = None
    iat: Optional[int] = None
    iss: Optional[str] = None

    @property
    def roles(self) -> List[str]:
        """Extract realm roles from Keycloak token structure."""
        if self.realm_access and "roles" in self.realm_access:
            return self.realm_access["roles"]
        return []

    def has_role(self, role: str | UserRole) -> bool:
        role_str = role.value if isinstance(role, UserRole) else role
        return role_str in self.roles
