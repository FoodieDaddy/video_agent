"""Development-friendly request authentication.

The first release ships header based identity so the whole API is usable without
an identity provider.  Production deployments are expected to swap
:func:`get_current_user` for OIDC/JWT verification; project level isolation and
permission checks are already enforced downstream.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header

from app.core.exceptions import PermissionDeniedError
from app.core.settings import Settings


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
    user = resolve_user(settings, x_user_id)
    if x_user_role and user.id != settings.demo_user_id:
        user = CurrentUser(id=user.id, email=user.email, name=user.name, role=x_user_role)
    return user


def _settings() -> Settings:
    from app.core.settings import get_settings

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
