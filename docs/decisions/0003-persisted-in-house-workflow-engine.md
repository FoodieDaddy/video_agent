# ADR 0003 — A small persisted workflow engine instead of a graph/orchestration framework

* **Status:** Accepted
* **Date:** 2026-11-02
* **Deciders:** platform team

## Context

The pipeline is long-running, expensive and partially human-gated:

```
script → characters → scenes → [gate] → director → storyboard → [gate]
       → character assets → shots → [gate] → audio → editing → render → evaluation → [gate] → export
```

Requirements that make this hard:

* a run must stop at a gate for minutes or days, then continue **exactly** where it stopped;
* the operator must see progress per node and re-enter a single stage without re-running the
  rest (e.g. regenerate shots only);
* every node must record what it produced, so a failed render is diagnosable;
* cancellation must take effect inside long media loops, not after them;
* the same engine must run in-process for tests (fast, synchronous) and in a worker later.

Graph frameworks (LangGraph), durable-execution engines (Temporal) and queue frameworks
(Celery) each solve part of this, at the cost of a new mental model, new operational
dependencies and control flow that is harder to unit-test than explicit code.

## Decision

Implement a ~200-line engine in `services/workflow.py` over the existing database:

* **Workflow definitions are YAML** (`config/workflows/*.yaml`): an ordered list of nodes, each
  `type: handler` (calls a function from `services/workflow_handlers.HANDLERS`) or
  `type: gate` (blocks on a `Review` with a `review_stage`).
* **The cursor is data.** `workflow_runs.state = {"next_index", "outputs", …}` and
  `run.current_node`; `resume()` reads `next_index` and continues from that node. Nothing is
  replayed.
* **Every node writes a `workflow_checkpoints` row** (status, summary, output, error) before
  the next node starts.
* **Gates create a `Review` row** and park the run in `awaiting_review`. Approving via the API
  enqueues a resume task; rejecting re-opens a fresh pending review at the same stage.
* **One active run per project/definition**, enforced at `start()`.
* **Failures are explicit:** `continue_on_error: true` records the error in `outputs` and
  moves on; otherwise the run is marked `failed` with the message on the run row.
* **Cancellation is threaded in** as `ctx.stop`, checked between shots/segments.

## Consequences

**Positive**

* Review gates, checkpoints, resumption and cancellation are ordinary database operations —
  inspectable with SQL, testable in a unit test, and portable across processes.
* The YAML definition is diffable and reviewable by non-engineers; adding a stage rarely means
  touching the engine.
* No extra runtime (no broker, no scheduler, no graph runtime) to operate for the demo or CI.
* Debugging is straightforward: read `workflow_runs`, `workflow_checkpoints`, `tasks`.

**Negative**

* No parallelism inside a run: nodes execute sequentially. Shot fan-out is handled inside the
  `video` handler instead of by the engine.
* No automatic retry/compensation semantics per node; retries are the caller's job (the task
  runner records attempts) and a failed run resumes at the failed node when re-run.
* The engine is our code: its invariants need tests. A real bug already occurred — SQLAlchemy
  skipped the UPDATE because `state` was reassigned as the same object, silently replaying
  stages; fixed by writing `dict(state)` and now covered by `test_pipeline_api.py`.
* Long-running nodes hold a database session for their duration; acceptable for minutes-scale
  tasks, not for hour-long GPU jobs.

## Alternatives considered

1. **LangGraph / semantic-kernel style graph** — great for agent-internal loops, but the
   checkpoint format is framework-owned; human gates and per-node review rows would become
   custom extensions.
2. **Temporal** — strongest durability story (activities, retries, timers), but it is a server
   to operate and a programming model to teach before the first film is exported.
3. **Celery chains/chords** — natural for task fan-out, yet state lives in the broker result
   backend; pausing for a human decision is awkward and the review data would still need our
   tables.
4. **A `while` loop inside a single long task** — simplest, but loses resumability: a restart
   during a 40-minute render would lose every previous stage.

## Revisit when

* Runs must survive process death mid-node (currently a crash inside a node requires
  re-running that node) — that is where durable execution starts to pay for itself.
* Shot-level fan-out needs real parallelism across workers: introduce per-shot tasks and let
  the engine only orchestrate stage boundaries.
* More than ~30 nodes with conditional branches: an explicit `when:`/`next:` map should replace
  the implicit "index + 1" flow before the YAML becomes a program.
