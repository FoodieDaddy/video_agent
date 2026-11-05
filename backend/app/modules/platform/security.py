"""Development authentication with production-safe role handling.

Header-based identities are a local development/test convenience only. The role
header is deliberately rejected outside those environments; production must
provide a trusted authentication integration rather than trusting client
controlled identity or authorization headers.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header

from app.modules.platform.configuration.settings import Settings
from app.modules.platform.exceptions import PermissionDeniedError


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    name: str
    role: str = "user"

    @property
    def is_admin(self) -> bool:
        return self.role in {"admin", "owner"}


def resolve_user(settings: Settings, user_id: str | None) -> CurrentUser:
    if user_id:
        return CurrentUser(id=user_id, email=f"{user_id}@local", name=user_id)
    if not settings.allow_dev_auth:
        raise PermissionDeniedError("Authentication required: provide the X-User-Id header")
    return CurrentUser(
        id=settings.demo_user_id,
        email=f"{settings.demo_user_id}@studio.local",
        name="Demo User",
        role="admin",
    )


async def get_current_user(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> CurrentUser:
    settings = _settings()
    if settings.env not in {"development", "dev", "test"}:
        # Never silently fall back to spoofable headers in staging/production.
        # A trusted OIDC/JWT integration must replace this development adapter.
        raise PermissionDeniedError("Trusted authentication is not configured")

    user = resolve_user(settings, x_user_id)
    # Role simulation is intentionally limited to isolated local/test runs.
    if x_user_role and user.id != settings.demo_user_id:
        normalized_role = x_user_role.strip().lower()
        if normalized_role in {"user", "editor", "admin", "owner"}:
            user = CurrentUser(id=user.id, email=user.email, name=user.name, role=normalized_role)
    return user


def _settings() -> Settings:
    from app.modules.platform.configuration.settings import get_settings

    return get_settings()


def require_admin(user: CurrentUser) -> None:
    if not user.is_admin:
        raise PermissionDeniedError("Administrator role required")


async def get_admin_user(
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
) -> CurrentUser:
    user = await get_current_user(x_user_id=x_user_id, x_user_role=x_user_role)
    require_admin(user)
    return user
