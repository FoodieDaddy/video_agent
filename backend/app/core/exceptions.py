"""Domain errors mapped to HTTP responses by the API layer."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "internal_error"
    status_code = 500

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


class ConfigurationError(AppError):
    code = "configuration_error"
    status_code = 500


class ValidationAppError(AppError):
    code = "validation_error"
    status_code = 422


class NotFoundError(AppError):
    code = "not_found"
    status_code = 404


class PermissionDeniedError(AppError):
    code = "permission_denied"
    status_code = 403


class ConflictError(AppError):
    code = "conflict"
    status_code = 409


class ProviderError(AppError):
    code = "provider_error"
    status_code = 502


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"


class AgentSchemaError(AppError):
    """Agent returned output that could not be validated against its schema."""

    code = "agent_schema_error"
    status_code = 422


class WorkflowError(AppError):
    code = "workflow_error"
    status_code = 400


class ReviewRequiredError(AppError):
    code = "review_required"
    status_code = 409


class TaskFailedError(AppError):
    code = "task_failed"
    status_code = 409
