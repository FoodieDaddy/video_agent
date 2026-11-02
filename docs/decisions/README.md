# Architecture Decision Records

Every decision that constrains future work is recorded here, in the order it was made. An ADR
is immutable history: to change a decision, add a new ADR that supersedes the old one and mark
the old one `Superseded by NNNN`.

Format per record: **Status · Context · Decision · Consequences · Alternatives considered ·
Revisit when**.

| # | Title | Status |
| --- | --- | --- |
| [0001](0001-config-driven-agent-registry.md) | Configuration-driven agents; no model in Python | Accepted |
| [0002](0002-sqlalchemy-sqlite-postgres-no-migrations.md) | SQLAlchemy models over SQLite/PostgreSQL, JSON payloads, no migration framework yet | Accepted |
| [0003](0003-persisted-in-house-workflow-engine.md) | A small persisted workflow engine instead of a graph/orchestration framework | Accepted |
| [0004](0004-immutable-versioning-and-config-ledger.md) | Append-only versioning for content and configuration | Accepted |
| [0005](0005-header-dev-auth-and-project-scoping.md) | Header auth for development, project-scoped authorization | Accepted |
| [0006](0006-task-runner-and-sse-from-db-events.md) | Thread runner + `task_events` table as the SSE source | Accepted |
| [0007](0007-mock-first-media-and-local-storage.md) | Mock provider that renders real media; local storage by default | Accepted |
| [0008](0008-windows-one-click-installer.md) | Windows one-click install/uninstall executables instead of a bundled runtime | Accepted |

## Conventions

* One decision per file, numbered sequentially, never renumbered.
* Write the *reasoning*, not the implementation: "why" ages well, "how" belongs in the code.
* Include what was rejected. The rejected options are the most valuable part for the next
  developer, who will otherwise propose them again.
* "Revisit when" makes the decision falsifiable: a future reviewer can check whether the
  trigger already happened.
