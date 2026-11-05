"""Router aggregation for versioned API modules."""

from __future__ import annotations

from fastapi import APIRouter

from studio_api.api.routes import admin, people, production, projects, story, tasks, workflows

api_router = APIRouter(prefix="/api/v1")
for module in (projects, story, people, production, workflows, tasks, admin):
    api_router.include_router(module.router)

__all__ = ["api_router"]
