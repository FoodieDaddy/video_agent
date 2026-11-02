# HTTP API Reference

Base path: `/api/v1` (set in `config/app.yaml → app.api_prefix`). Everything is JSON
except document upload (multipart) and media download (binary).

Outside the prefix:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | liveness + database probe |
| GET | `/media/{storage_key}` | streams a stored asset (image/video/audio/subtitle/film) |
| GET | `/` , `/app.js`, `/styles.css` | the bundled console |
| GET | `/docs`, `/openapi.json` | interactive docs and schema |

## 1. Authentication and scoping

Development header auth (`auth.allow_dev_auth: true`):

```
X-User-Id: <id>        # omit to act as the demo administrator (auth.demo_user_id)
X-User-Role: admin     # only honoured for ids other than the demo id
```

* Omitting `X-User-Id` yields the demo admin identity, `user_demo`.
* Sending `X-User-Id: user_demo` downgrades that user to `role="user"` — the console
  therefore omits the header for the demo identity.
* Every project is owned by the creating user. Owners pass all checks; other users get
  `403 permission_denied`, and their project listing simply does not include it.
* `/admin/*` requires `role == "admin"` (`AdminDep`).
* Production must set `auth.allow_dev_auth: false` and terminate auth at the gateway.

## 2. Error envelope

All handled errors, including validation errors, share one shape:

```json
{
  "error": {
    "code": "validation_error",
    "message": "请求参数不合法",
    "details": {"field": "name"},
    "request_id": "req_..."
  }
}
```

| HTTP | `code` |
| --- | --- |
| 400 | `validation_error` |
| 401 / 403 | `unauthenticated` / `permission_denied` |
| 404 | `not_found` |
| 409 | `conflict` |
| 422 | `validation_error` (request body / query) |
| 500 | `internal_error` |

## 3. Long-running operations

Anything that calls a model or FFmpeg runs as a `Task` and returns `202` with
`{"task": {...}, ...}`.

* `?wait=true` — run the task and wait (bounded) so the response already contains the
  outcome. Used by the console and the tests.
* Poll `GET /projects/{id}/tasks/{task_id}` or subscribe to
  `GET /projects/{id}/tasks/{task_id}/events/stream`.
* `POST /projects/{id}/tasks/{task_id}/cancel` sets the cancellation flag; long loops
  check it between shots/segments.

### SSE framing

```
event: task
data: {"id":"tevent_...","event_type":"progress","progress":0.42,"message":"镜头 3/6",...}

event: end
data: {"status":"succeeded"}
```

Frames arrive every ~0.5 s (configurable via the `timeout` query, default 120 s) and end
with `event: end` once the task reaches a terminal state, or `event: timeout`. `after=<event_id>`
resumes from a known event. Clients must send auth headers, so `EventSource` is not usable —
the console reads the stream with `fetch` + `ReadableStream`.

## 4. Projects

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/projects` | projects visible to the caller |
| POST | `/projects` | body `ProjectCreate` → 201 |
| GET | `/projects/{id}` | project detail |
| PATCH | `/projects/{id}` | `ProjectUpdate` |
| GET | `/projects/{id}/dashboard` | stage cards, counts, pending review, film url |
| GET | `/projects/{id}/summary` | script/characters/scenes/shot/audio counters |
| GET | `/projects/{id}/assets?kind=` | stored assets; `kind` filters |
| GET | `/projects/{id}/meta` | workflows + agents + providers this project can use |

```powershell
$body = @{ name = "雨夜书店"; description = "示例"; genre = "悬疑" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/projects `
  -ContentType application/json -Body $body
```

## 5. Story intake (novel → script)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/projects/{id}/documents` | uploaded source documents |
| POST | `/projects/{id}/upload` | multipart `file`; `?sample=true` imports `samples/novel_sample.txt` |
| POST | `/projects/{id}/documents/{doc_id}/parse?wait=` | re-split a document into chapters |
| GET | `/projects/{id}/chapters` | parsed chapters |
| POST | `/projects/{id}/analyze?wait=` | run the `script` stage (task) |
| GET | `/projects/{id}/script` | latest script |
| GET | `/projects/{id}/scripts` | all script versions |
| GET | `/scripts/{script_id}` | one script |
| PATCH | `/scripts/{script_id}` | edit title/logline/synopsis/content → new version |

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/projects/$PID/upload?sample=true"
curl -X POST "http://127.0.0.1:8000/api/v1/projects/$PID/analyze?wait=true"
```

## 6. People (characters and scenes)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/projects/{id}/characters` | characters + latest profile |
| GET | `/characters/{id}` | character detail |
| PATCH | `/characters/{id}` | `CharacterUpdate` → new profile version |
| POST | `/characters/{id}/generate-images?wait=` | body `{ "kinds": ["portrait","full_body","turnaround"] }` |
| POST | `/characters/{id}/generate-views?wait=` | turnaround/expression views |
| POST | `/characters/{id}/approve` | marks the character approved for production |
| GET | `/characters/{id}/assets` | generated sheets |
| GET | `/projects/{id}/scenes` | scenes + latest profile |
| GET | `/scenes/{id}` | scene detail |
| PATCH | `/scenes/{id}` | `SceneUpdate` → new profile version |
| POST | `/scenes/{id}/approve` | approve scene |

## 7. Production (directing → shots → audio → edit → export)

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/projects/{id}/direct?wait=` | directing plan (task) |
| GET | `/projects/{id}/directing` | latest plan + version list |
| POST | `/projects/{id}/storyboards?wait=` | storyboard + shots (task) |
| GET | `/projects/{id}/storyboards` | latest board + versions |
| GET | `/projects/{id}/shots` | shots with camera, dialogue, duration, approval |
| GET | `/shots/{id}` | one shot |
| PATCH | `/shots/{id}` | `ShotUpdate` (description/action/camera/dialogue/duration/prompts/scene) |
| POST | `/shots/{id}/approve` | approve a single shot |
| POST | `/shots/{id}/generate?wait=` | generate one shot video (new `video_generations` row) |
| POST | `/projects/{id}/shots/generate?wait=` | generate all unapproved/missing shots (task) |
| GET | `/shots/{id}/versions` | candidate videos + selected one |
| POST | `/shots/{id}/versions/{video_id}/select` | pick the take |
| POST | `/projects/{id}/audio?wait=` | narration/dialogue TTS + subtitles (task) |
| GET | `/projects/{id}/audio` | tracks |
| POST | `/projects/{id}/editing?wait=` | build timeline (clips, subtitles, transitions) |
| GET | `/projects/{id}/editing` | latest edit project |
| POST | `/projects/{id}/render?wait=` | FFmpeg render to `film` asset |
| POST | `/projects/{id}/export?wait=` | publish the final asset as export |
| GET | `/projects/{id}/export` | export status + url |
| POST | `/projects/{id}/evaluate?wait=` | DB metrics + evaluation agent |
| GET | `/projects/{id}/evaluation` | latest evaluation report |

## 8. Workflows and reviews

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/projects/{id}/workflows` | runs, newest first |
| POST | `/projects/{id}/workflows/start?wait=` | body `{ "workflow_id": "novel_to_video" }` → 202 |
| GET | `/projects/{id}/workflows/{run_id}` | run + checkpoints + pending review id |
| POST | `/projects/{id}/workflows/{run_id}/resume?wait=` | continue after a gate/failure |
| POST | `/projects/{id}/workflows/{run_id}/cancel` | cancel a parked run |
| GET | `/projects/{id}/reviews?status=` | reviews for the project (`pending`/`approved`/`rejected`) |
| GET | `/reviews/{review_id}` | review + payload snapshot |
| POST | `/reviews/{review_id}` | `ReviewDecision` (owner or `editor` member) → approved resumes the run; rejected reopens the gate |
| GET / POST | `/reviews/{review_id}/comments` | review discussion |

```json
POST /api/v1/reviews/rev_abc
{ "status": "approved", "comment": "人物与场景可用", "resume_workflow": true }
```

Response: `{"review": {...}, "task_id": "...", "status": "pending", "task": {...}}` — the
`task_*` fields are only present when the approval resumed the workflow (pass `?wait=true`
to receive the finished resume task).

## 9. Tasks

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/projects/{id}/tasks?limit=` | recent tasks |
| GET | `/projects/{id}/tasks/{task_id}` | task state (`pending/running/succeeded/failed/cancelled`) |
| GET | `/projects/{id}/tasks/{task_id}/events` | event list (supports `after`) |
| GET | `/projects/{id}/tasks/{task_id}/events/stream` | SSE stream |
| POST | `/projects/{id}/tasks/{task_id}/cancel` | request cancellation |

## 10. Admin (model configuration)

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/meta` | app name/version, agents, providers, workflows, languages |
| GET | `/admin/status` | app/env, database driver, storage backend + root, ffmpeg binary/availability, task mode, agent counts, `config_versions` |
| GET | `/admin/model-configs` | every agent with provider/model/version/override flag |
| GET | `/admin/model-configs/{agent_id}` | effective payload (`agent`, `model`, `generation`, `structured_output`, `prompt`, `runtime`, `evaluation`) + version list |
| POST | `/admin/model-configs/{agent_id}/versions` | body `{ "payload": {...}, "note": "" }` → 201, new version activated |
| GET | `/admin/model-configs/{agent_id}/versions` | version history |
| POST | `/admin/model-configs/{agent_id}/rollback` | no body; re-activates the newest inactive version |
| DELETE | `/admin/model-configs/{agent_id}/override` | drop the DB override, fall back to YAML |
| GET | `/admin/model-config-versions?scope=&key=` | ledger across all agents |
| POST | `/admin/model-config-versions/{version_id}/activate` | activate a stored version globally |
| GET | `/admin/providers` | provider buckets, enabled flags, models, key env names |
| GET | `/admin/workflows` | workflow summaries with node lists |

Config versions are checksummed and immutable; activation writes a single `active` row per
agent that the config store merges over the YAML on the next reload. Running tasks keep the
version they started with.

## 11. Conventions recap

* IDs are prefixed strings (`prj_`, `task_`, `run_`, `rev_`, `shot_`, `asset_`, …).
* Timestamps are ISO-8601 UTC strings.
* Asset URLs are relative (`/media/<storage_key>`), so the same payload works behind a proxy.
* Mutating endpoints that can be slow accept `?wait=true`; without it they return the task
  and you follow the stream.
