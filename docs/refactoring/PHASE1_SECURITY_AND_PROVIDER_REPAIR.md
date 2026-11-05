# Refactoring Phase 1 — security boundary and provider repair

Date: 2026-11-05

## Scope completed in this increment

1. Restored `backend/app/modules/ai_runtime/providers/openai_compat.py` from the project's committed provider implementation. The uploaded working tree contained a copy of a pytest module at this import path, which caused circular imports during test collection. Imports were migrated to the current modular package paths.
2. Restricted header-based development identity and role simulation to `development`, `dev`, and `test`. Requests in other environments now fail closed until a trusted OIDC/JWT integration is configured. `X-User-Role` is not an authorization source outside local/test environments.
3. Normalized LLM transport failures into `ProviderError` without retaining the original HTTPX exception chain, which can contain Authorization headers or request metadata.
4. Removed upstream response bodies and signed download URLs from HTTP error messages. Provider health checks now treat 4xx responses as not healthy. Remote job error details are length-bounded and common credential forms are redacted.
5. Added a regression test for production-mode spoofed identity/role headers.
6. Removed the supplied local `.env` file from the deliverable copy. `.env.example` remains the setup template.
7. Added `APP_ENV_FILE` support to the module-2 checker so isolated test sandboxes can explicitly read the fixture project's `.env` without copying credentials into the sandbox.

## Validation performed

- `git diff --check`: passed.
- Python compile check for `backend/app` and `scripts/checks`: passed.
- Focused backend regression set (auth boundary, API, LLM transport, providers, module-1 checks): 26 passed.
- Frontend Node test suite: 107 passed, 0 failed.
- The complete backend suite is **not yet green** in this execution environment. The module-2 subprocess tests expect their `sitecustomize.py` test hook to override the runtime's preloaded `/opt/python-hooks/sitecustomize.py`; the preloaded hook wins, so the fake HTTP transport is not installed and live tests fail closed with connection errors. This is an environment/test-harness collision, not evidence that the real provider endpoint is unavailable. Re-run these tests in the project's normal local Python environment.

## Important security follow-up

A non-placeholder provider credential was present in the uploaded `.env`. That file has been excluded from this deliverable, but removing it from a ZIP does not revoke the credential. Rotate/revoke the affected provider key before using the project again. Do not paste the replacement key into source control or share it in a ZIP.

## Known work still required for the full refactor

This increment is the first repair tranche, not the completion of the full production refactor. The following remain open:

- Replace development header authentication with real OIDC/JWT identity, role claims, and project-level authorization. Production currently fails closed by design until this is configured.
- Protect media delivery with project-scoped authorization or short-lived signed URLs; the existing `/media/{storage_key}` compatibility route remains a follow-up risk.
- Introduce Alembic migrations and a verified SQLite-to-PostgreSQL migration path.
- Move long-running jobs from the in-process `TaskRunner` to a durable worker queue (Celery/Redis or an equivalent), including idempotency, retry policy, leases, and crash recovery.
- Freeze workflow/agent/provider configuration snapshots per execution.
- Add rate limits, quotas, cost reservations, tracing, metrics, dependency/security scanning, and CI release gates.
- Remove deprecated import aliases only after import-graph tests prove no remaining consumers.

## Recommended next order

1. Complete OIDC/JWT and project/media authorization.
2. Add Alembic and migration tests before changing production database engines.
3. Introduce durable task dispatch using an outbox and idempotent workers.
4. Add execution snapshots and cost/concurrency controls.
5. Add observability and supply-chain CI gates.
6. Retire compatibility aliases and consider LangGraph only if the existing workflow engine demonstrably cannot meet new workflow requirements.
