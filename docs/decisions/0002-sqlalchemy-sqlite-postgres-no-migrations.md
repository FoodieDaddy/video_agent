# ADR 0002 — SQLAlchemy models over SQLite/PostgreSQL, JSON payloads, no migration framework yet

* **Status:** Accepted
* **Date:** 2026-11-02
* **Deciders:** platform team

## Context

The domain is document-shaped: a script is a nested structure, a camera spec is a dict, a
timeline is a list of clips. Modelling every leaf as a column would create dozens of
join-heavy tables that only the serializers ever read. On the other hand, some relations must
be queried and enforced: projects → characters → shots → videos, tasks by project, reviews by
status.

The team also needs to run the entire stack on a laptop with no services (tests, smoke script,
demo) while shipping the same code against PostgreSQL in production.

## Decision

* **One ORM, two databases.** SQLAlchemy 2.x declarative models in `app/models/`, engine
  created from `DATABASE_URL` (`sqlite:///…` in dev/test, `postgresql+psycopg://…` in prod).
  Nothing in the service layer is dialect-specific.
* **Hybrid schema.** Relations and anything filtered/sorted gets a real column
  (`project_id`, `status`, `version`, timestamps). Nested domain content lives in JSON columns
  (`scripts.content`, `character_profiles.content`, `shots.camera`, `editing_projects.timeline`,
  `workflow_runs.state`), validated by pydantic before it is written.
* **Schema creation via metadata** (`init_schema()`) instead of a migration framework for now;
  `create_all` is idempotent enough for greenfield development.
* **No binary data in the database.** Media is written to storage and referenced by
  `storage_key`.
* **Every mutation commits once per unit of work.** Services `flush()`; the API layer or the
  task worker commits. This keeps the workflow engine's checkpoint/commit rhythm explicit.

## Consequences

**Positive**

* The same test suite runs on SQLite with zero setup, so CI is fast and contributors need no
  container.
* JSON columns let the domain evolve (new shot field, new timeline effect) with a pydantic
  change instead of a DDL migration.
* Serializers (`api/serializers.py`, `*_public` functions) insulate the wire format from ORM
  changes.

**Negative**

* JSON columns cannot be queried or indexed in a portable way; anything the UI filters must be
  promoted to a column (this already happened for `status`, `version`, `stage`).
* `create_all` cannot alter existing tables: a real schema change on a live database needs a
  hand-written migration or a fresh database. Acceptable while the schema is pre-1.0.
* SQLite's type affinity hides mistakes (e.g. a str where a float was expected); PostgreSQL
  will surface them later.
* Mutable JSON requires discipline — see the `run.state = dict(state)` pitfall in
  `services/workflow.py`; re-assigning the same object does not emit an UPDATE.

## Alternatives considered

1. **PostgreSQL only** — best fidelity, but every test would need a service; the mock-first
   offline promise (ADR 0007) would break.
2. **Fully normalized schema** (tables for shots, dialogue lines, camera fields, timeline
   clips) — more queryable, but multiplies boilerplate and makes the agent payload
   (pydantic) and the storage layer diverge.
3. **Document store (MongoDB)** — natural fit for JSON documents, but loses relational
   integrity for the project/version/ownership model and adds an operational dependency.
4. **Alembic from day one** — correct long-term, yet premature while the schema is still being
   shaped; the cost is a migration per iteration during development.

## Revisit when

* The first real deployment with data that must be preserved appears — then introduce Alembic
  and mark `create_all` as dev-only.
* Any list/dashboard endpoint needs to filter on a JSON field (promote it to a column first).
* Moving to PostgreSQL for production: add the indexes listed in
  [../database/schema.md](../database/schema.md) §10 and re-run the suite against it.
