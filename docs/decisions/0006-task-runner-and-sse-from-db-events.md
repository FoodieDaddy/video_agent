# ADR 0006 — Thread runner + `task_events` table as the SSE source

* **Status:** Accepted
* **Date:** 2026-11-02
* **Deciders:** platform team

## Context

Every meaningful action is long and asynchronous: a script generation is one LLM call, a shot
stage is N video calls, a render is an FFmpeg subprocess. The operator needs live progress
("镜头 3/6"), and the system needs a durable record of what happened even if nobody is
watching.

Requirements:

* progress must be visible in a browser without a build step;
* a page reload must not lose the run (progress is not ephemeral);
* the design must not break when more than one process serves requests;
* tests must be able to run a task synchronously and assert the result;
* cancellation must be observable by the worker loop.

## Decision

* **One record type for work:** `tasks` rows with `type`, `status`, `stage`, `progress`,
  `payload`, `result`, `error`, `attempts`, plus a frozen `config_versions` snapshot.
* **Progress is a table, not a bus:** `task_events` is append-only (`event_type`, `level`,
  `message`, `progress`, `data`). `services/tasks.py::emit` writes it; every service reports
  through it.
* **SSE reads the table.** `GET /projects/{id}/tasks/{task_id}/events/stream` polls
  `task_events` (`after=` cursor, short sleep) and frames `event: task` / `event: end` /
  `event: timeout`. Because the data is in the database, multi-process and multi-worker
  deployments stay correct with no pub/sub infrastructure.
* **The runner is pluggable.** `TaskRunner` uses one thread per task when `tasks.inline: true`
  (dev/test) and a bounded `ThreadPoolExecutor` otherwise; each task opens its own session,
  runs the async handler with `asyncio.run`, and records terminal state itself. Failures are
  captured on the task — never raised into the request thread.
* **`?wait=true`** lets a caller block for the finished task (console convenience, tests).
* **Cancellation is a flag** (`runner.is_cancelled`) exposed to long loops as `ctx.stop`.
* **Config is snapshotted at start**, so a mid-run config change cannot alter provenance.

## Consequences

**Positive**

* Progress survives reloads and process restarts; the console can rebuild state from
  `GET /tasks/{id}/events` and then attach to the stream.
* No broker, no Redis, no in-process subscription registry to leak or desynchronise.
* Tests are deterministic: inline execution + `?wait=true` means no sleeps or polling loops in
  the suite.
* One place (`tasks.py`) to add retries, timeouts or a fair queue.

**Negative**

* Polling adds latency (~0.5 s granularity) and a query per client per tick; fine for an
  operator console, not for thousands of concurrent streams.
* `task_events` grows fast during heavy media work (one row per shot segment); needs a
  retention policy.
* Inline threads do not survive process death: an interrupted render leaves the task `running`
  until a supervisor reconciles it. `tasks.inline: false` plus an external worker is the
  documented next step, and no worker ships yet — so production must currently run a single
  process.
* Threads + `asyncio.run` per task is simple but means no shared event loop; concurrency is
  bounded by `max_workers`, not by an async scheduler.

## Alternatives considered

1. **WebSocket** — lower latency and bidirectional, but the browser console would need
   reconnection logic and the server a connection registry; SSE is enough for one-way progress.
2. **Redis pub/sub + worker (Celery/RQ)** — the canonical scalable answer; adds a broker to
   operate and still needs the database record for durability and audit.
3. **In-process `asyncio.Queue` / event bus** — trivial, but events are lost on restart and
   wrong as soon as two processes serve the API.
4. **No progress, poll only `task.status`** — cheapest, but the operator loses the per-stage
   narrative that makes a 40-shot run debuggable.

## Revisit when

* More than ~20 concurrent operators: switch the stream to Redis pub/sub (or Postgres
  `LISTEN/NOTIFY`) while keeping `task_events` as the durable log.
* `tasks.inline: false` gets a real worker: the worker becomes the single writer of task
  terminal state and the API only observes.
* A run can be interrupted by a deploy: add a supervisor that requeues `running` tasks older
  than a heartbeat threshold.
