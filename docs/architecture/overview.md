# Architecture Overview

AI Film Studio is a configuration-driven, human-in-the-loop pipeline that converts a
novel into a rendered short film. This document explains the layers, the runtime data
flow, and the invariants the code relies on. Decisions with trade-offs are recorded in
[`docs/decisions/`](../decisions/README.md).

当前已实施第一批逻辑模块化，源码入口见[模块导航](../../backend/app/modules/README.md)，
已迁移范围与后续阶段见[重构进度](refactoring-progress.md)。本文下方保留的
`app.services`、`app.core`、`app.agents`、`app.providers` 等旧路径现在主要作为
兼容入口；其唯一实现位于 `app.modules`。业务 ORM 和 Pydantic Schema 暂保留
原定义，workspace 和完整仓储/DTO 解耦尚未实施。

## 1. Design goals

| Goal | Consequence in the code |
| --- | --- |
| Model choice is configuration, not code | Agents read `config/agents/*.yaml`; provider YAML only references env-var **names** |
| Cheap work before expensive work | Script → characters/scenes → gate → director → storyboard → gate → shots → gate → audio/edit → gate → export |
| Nothing silent is lost | Every stage writes versioned rows; every workflow node writes a checkpoint; every model call writes `agent_runs` + `model_call_logs` |
| Restartable | Workflow cursor and outputs live in `workflow_runs.state`; tasks and events live in tables |
| Offline first | `mock` provider renders real files through FFmpeg; the whole suite runs without keys or GPU |
| One obvious extension point per feature | New agent = class + registry entry + YAML + prompt + schema; new stage = handler + YAML node |

## 2. Layers

```
HTTP (FastAPI, /api/v1)                web/ console (vanilla JS, no build)
        │                                        │
        ▼                                        ▼  fetch + SSE
api/routes/* ──► modules/<business>/public ──► application use cases / queries
                         │                               │
                         ▼                               ▼
               workflow / reviews                  ai_runtime execution
                         │                               │
                         ▼                               ▼
            platform task runner             registered business Agent → Provider

platform: config / Base / Session / storage / FFmpeg
bootstrap: 13 business roles → 17 executable Agent IDs
```

### 2.1 `core/`

* `settings.py` — frozen `Settings` built by `load_settings()`: `config/app.yaml` <
  `config/environments/<APP_ENV>.yaml` < environment variables. Directories are created
  in `ensure_dirs()`.
* `config_models.py` — typed views of agent/provider/workflow YAML (pydantic models).
* `config_store.py` — loads `config/**` once, computes `stable_checksum` per file, and
  merges the **active** `config_versions` override row on top of the YAML.
* `security.py` — development header auth (`X-User-Id`, `X-User-Role`); resolves to the
  demo admin identity when no header is sent.
* `exceptions.py` — `AppError` hierarchy mapped to HTTP status codes by `main.py`.

### 2.2 `models/` and `schemas/`

SQLAlchemy tables (`models/`) describe persistence; pydantic classes (`schemas/`) describe
agent input/output and are the structured-output contract. `schemas/registry.py` maps a
schema name from agent YAML to a pydantic model, so validation never hardcodes an agent.
`scripts/export_schemas.py` exports them to `config/schemas/*.json` for prompts/tools.

### 2.3 `providers/`

A provider implements one capability bucket (`llm`, `vision`, `image`, `video`, `audio`)
behind `providers/base.py`:

```python
async def complete(...) / describe_image(...) / generate_image(...) / generate_video(...) / synthesize(...)
```

`providers/mock.py` generates deterministic text and delegates file generation to
`providers/mock_generators.py` (Pillow frames, FFmpeg clips, silent WAV).
`providers/openai_compat.py` speaks `POST {base_url}/chat/completions` so OpenAI, Azure
proxies, vLLM and DashScope-compatible endpoints all work. `providers/registry.py`
resolves `(capability, provider_name)` using the YAML: a disabled provider or a missing key
env var raises `ProviderUnavailableError`, an unknown provider/model kind or a protocol that
cannot serve the capability raises `ConfigurationError` — always before the first call, never
halfway through a paid stage.

### 2.4 `agents/`

`BaseAgent` holds the whole per-agent contract:

1. render the system/user prompt from `prompt.system` / `prompt.user_template` (with the
   `prompt.version` recorded on the run);
2. validate the input payload with the pydantic model from `schemas/`;
3. call the configured provider with `generation.*` parameters, retrying
   `generation.max_retries` times;
4. when `structured_output.enabled`, parse JSON, validate against the schema and repair
   `structured_output.repair_attempts` times;
5. on provider failure, retry once through `model.fallback_provider` /
   `model.fallback_model_id`;
6. apply `evaluation.checks` / `thresholds` when configured;
7. return an `AgentResult` carrying provider, model, latency, token usage, cost and the
   config version.

`services/agent_runner.py::run_agent` wraps that in an `AgentRun` row (input, output,
status, error, latency, prompt/config version) and records `ModelCallLog` entries, so cost
and failures are auditable per project/task.

### 2.5 `services/`

| Module | Responsibility |
| --- | --- |
| `projects.py` | projects, membership, owner/member scoping, dashboard |
| `documents.py` | upload (txt/md/docx/pdf), sample ingestion, chapter parsing into `story_chapters` |
| `pipeline.py` | script, characters/profiles, scenes, directing, storyboard, shots, all `*_public` serializers |
| `media.py` | character sheets, per-shot video versions + selection, TTS/subtitles, edit timeline, FFmpeg render/export |
| `quality.py` | DB-derived metrics + evaluation agent run |
| `reviews.py` | review lifecycle (pending → approved/rejected), comments, gate lookups |
| `config_admin.py` | config version ledger, activate/rollback, DB override merge |
| `workflow.py` | workflow engine (see §3) |
| `workflow_handlers.py` | node name → service call mapping |
| `tasks.py` | `Task`/`TaskEvent` records, thread runner, cancellation |
| `runtime.py` | process-wide singletons: settings, config store, storage, runner |

Services take `(db, runtime, *, project=..., task=..., user_id=...)` and emit task events;
they never read HTTP concerns.

## 3. Workflow engine

New runs persist a JSON `workflow_definition` snapshot in `workflow_runs.state`; resume prefers it over mutable YAML. Legacy runs without a snapshot retain the previous current-config fallback.


Workflow definitions are YAML (`config/workflows/*.yaml`) with an ordered `nodes` list:

```yaml
- id: extract_characters
  type: handler              # handler | gate
  handler: characters        # key in services/workflow_handlers.HANDLERS
  agent: character_extraction
  title: 人物提取与档案
  continue_on_error: false   # optional: log the failure and continue
- id: review_characters_scenes
  type: gate
  review_stage: characters_scenes
```

Runtime rules:

* `workflow_runs.state` = `{"next_index", "outputs", "workflow_config_version"}`. The
  cursor is the source of truth; `resume()` continues at exactly that node.
* Every node writes a `workflow_checkpoints` row (`status`, `summary`, `output`, `error`).
* A `gate` node calls `reviews.get_or_create_pending(...)`. If nothing is approved yet it
  parks the run in `awaiting_review` and returns; the API then exposes a pending review.
* `POST /reviews/{id}` with `approved` resumes the run; `rejected` records the comment and
  re-opens a **new** pending review for the same stage — the run never advances.
* One active run per project/definition is enforced (`ValidationAppError`).
* On handler failure: `continue_on_error: true` stores `{"error": ...}` in outputs and
  moves on; otherwise the run is marked `failed` with the error message and checkpoint.
* `stop=ctx.stop` is threaded into long media loops, so cancelling the task aborts
  between shots/segments instead of after the entire stage.

Because the engine is our own ~200 lines instead of a graph framework, the checkpoint
semantics, review parking and cancellation hooks are explicit and unit-testable.

> Pitfall encoded in the code: the engine mutates the state dict in place, so it always
> writes back **a copy** (`run.state = dict(state)`). Re-assigning the same object is
> invisible to SQLAlchemy and leaves the cursor stale — which silently replays stages.

## 4. Tasks and progress

Long-running work is always a `Task`:

```
route ──► tasks.enqueue(runtime, project, type, runner) ──► Task row (pending) ──► runner thread
                                                                          │
                                                       emit(event) ──► task_events ──► SSE / polling
```

* `tasks.inline: true` starts a dedicated thread per task (`APP_INLINE_TASKS=0` switches to
  a bounded `ThreadPoolExecutor`).
* The worker opens its own session (`session_scope`), sets `running`, records the config
  version snapshot, runs the async handler with `asyncio.run`, then writes
  `succeeded` / `failed` / `cancelled`. Failures are stored on the task and emitted as an
  `error` event, never raised into the request thread.
* `?wait=true` on mutating endpoints runs the task and waits (bounded) before returning —
  convenient for the console and tests.
* SSE (`GET /projects/{id}/tasks/{task_id}/events/stream`) polls `task_events` and emits
  `event: task` frames plus a terminal `event: end`. Using the table (rather than an
  in-process bus) keeps it correct with multiple workers. The console consumes it with
  `fetch` + `ReadableStream` because `EventSource` cannot send auth headers.

## 5. Versioning and reproducibility

| Entity | Versioning |
| --- | --- |
| `scripts`, `character_profiles`, `scene_profiles`, `directing_plans`, `storyboards`, `editing_projects` | incrementing `version` per project; newest wins, older rows stay queryable |
| `video_generations` | every attempt kept; `shots.selected_video_id` picks the approved take |
| `assets` | content-addressed storage keys; `kind` distinguishes image/video/audio/subtitle/film |
| `config_versions` | checksummed snapshots of the agent/provider/workflow config; one active row merged over YAML; activate/rollback supported |
| `workflow_runs.config_versions`, `tasks.config_versions`, `agent_runs.config_version` | freeze the config actually used |

A task therefore answers "which prompt, which model, which config checksum produced this?"

## 6. API surface and console

* All endpoints live under `/api/v1` (`api/router.py`); `/health` and `/media/{key}` are
  outside the prefix. Full reference: [../api/README.md](../api/README.md).
* Errors use one envelope: `{"error": {"code", "message", "details", "request_id"}}`.
* The console (`web/`) is served by the same process: `/` → `index.html`, `/app.js`,
  `/styles.css`. It has eleven workbench tabs mirroring the pipeline stages plus an admin
  tab for model configuration.

## 7. Storage and media

* The database stores **object keys**, never blobs. `LocalStorage` (default) and
  `S3Storage` (`STORAGE_BACKEND=s3`) implement the same interface; path traversal is
  rejected by `LocalStorage.path_for`.
* `utils/ffmpeg.py::resolve_binary` locates `ffmpeg`/`ffprobe` from settings, PATH or a
  bundled binary and raises a descriptive error.
* Mock providers still call FFmpeg, so a green test run proves the media path works
  (colour frames, silent clips, normalised WAV, burned-in subtitles, H.264 export).

## 8. Deployment topology

```
browser ──► nginx (optional) ──► uvicorn (FastAPI, 1+ replicas) ──► PostgreSQL (prod) / SQLite (dev)
                                        │
                                        ├── object storage (S3/MinIO) or local data/storage
                                        └── ffmpeg subprocesses
```

`docker-compose.yml` runs one API container (tasks inline) with `data/` bind-mounted and an
optional MinIO profile. Scaling out requires a real database, `tasks.inline: false` and an
external worker (documented gap) — see ADR 0006.

## 9. Where to change what

| I want to… | Touch |
| --- | --- |
| swap model/provider for one agent | `config/agents/<id>.yaml` or the console 模型配置 tab |
| add a provider | `providers/*` implementation + `config/providers/<capability>.yaml` |
| add an agent | see [../agents/README.md](../agents/README.md) |
| add/reorder pipeline stages | `config/workflows/*.yaml` (+ handler if the stage is new) |
| change review gates | `type: gate` nodes and `reviews.py` |
| change API shape | `api/routes/*` + `api/serializers.py` |
| change the console | `web/app.js` |
