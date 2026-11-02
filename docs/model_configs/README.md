# Model & Provider Configuration

Three properties must hold at all times:

1. **No model id, vendor name or API key in Python.** Code asks the config store for an
   agent's `AgentConfig`; the YAML (or an active DB override) supplies provider, model,
   fallback, parameters, prompt paths and thresholds.
2. **Secrets live in the environment only.** Provider YAML stores the *name* of the env var
   (`api_key: env:OPENAI_API_KEY`). `/admin/providers` returns that name and a boolean
   `has_api_key`, never the value. A literal key (`api_key: <secret>`) is honoured for a
   throwaway local setup, but `api_key: env:NAME` is what ships — and the test suite rejects
   a literal in any committed provider file.
3. **Every run is attributable.** `agent_runs` / `tasks` / `workflow_runs` freeze the
   `config_version` (checksum of the effective config) used for that execution.

## 1. Configuration layers

```
config/app.yaml                    global defaults (server, tasks, storage, media, budget, limits, logging)
config/environments/<APP_ENV>.yaml environment overlay (development | test | production)
environment variables              highest precedence runtime override (DATABASE_URL, STORAGE_ROOT, …)
config/agents/<id>.yaml            per-agent model/generation/prompt/runtime/evaluation config
config/providers/<bucket>.yaml     provider catalogue per capability bucket (llm/vision/image/video/audio)
config/workflows/<id>.yaml         node list, handlers, review gates
active config_versions row         optional DB override merged over the agent YAML (admin console)
```

Relevant environment variables (all optional, see `.env.example`): `APP_ENV`,
`APP_CONFIG_DIR`, `APP_DATA_DIR`, `DATABASE_URL`, `STORAGE_ROOT`, `APP_INLINE_TASKS`,
`APP_MAX_WORKERS`, `APP_ALLOW_DEV_AUTH`, `APP_DEMO_USER_ID`, `FFMPEG_BIN`, `FFPROBE_BIN`,
`AGENT_MODEL_PROVIDER` / `AGENT_MODEL_ID` (force every agent onto one model, dev/staging only).

## 2. Two layers of parameters

Provider-level parameters describe the **service**; agent-level parameters describe the
**request**. Keeping them apart is what lets one provider serve many agents.

| Provider YAML (`config/providers/<bucket>.yaml`) | Agent YAML (`config/agents/<id>.yaml`) |
| --- | --- |
| `protocol` (adapter), `enabled`, `models[]` | `model.provider`, `model.model_id`, `model.capability` |
| `url`, `api_key` (literal or `env:NAME`), `endpoint` | `model.fallback_provider`, `model.fallback_model_id` |
| `timeout_seconds`, `max_concurrency` | `generation.timeout_seconds`, `generation.max_retries` |
| `extra.submit_path` / `status_path` / `cancel_path`, poll limits | `generation.temperature`, `top_p`, `seed`, `max_output_tokens` |
| `extra.request_fields` / `request_defaults` (extra submit fields) | `structured_output.*`, `prompt.*`, `runtime.*`, `evaluation.*` |
| `extra.input_cost_per_1k`, `output_cost_per_1k`, `unit_cost` | `structured_output.*`, `prompt.*`, `runtime.*`, `evaluation.*` |
| `extra.supported_params`, `max_tokens_field` | `model.provider_options` (pass-through) |

```yaml
providers:
  openai_compatible:            # 供应商标识，agent 的 model.provider 引用它
    enabled: true
    protocol: openai_chat       # mock | openai_chat | openai_images | openai_speech | openai_videos | http_task | local_worker
    url: https://api.deepseek.com/v1   # 也可以是 env:SOME_VAR
    api_key: env:DEEPSEEK_API_KEY      # 也可以直接粘贴密钥（仅限本机自用）
    models: [deepseek-chat]     # 智能体 model_id 填这里列出的模型名
```

The legacy `kind` / `api_key_env` / `base_url_env` / `base_url` / `endpoint_env` spelling is
still parsed, so an older provider file keeps working after an upgrade.

## 3. Provider buckets and adapters

| Bucket file | `protocol` values implemented | Notes |
| --- | --- | --- |
| `llm.yaml` | `mock`, `openai_chat` | OpenAI-compatible chat completions; works with vLLM/Azure/DashScope compatible mode |
| `vision.yaml` | `mock`, `openai_chat` | image + text messages, same wire format |
| `image.yaml` | `mock`, `openai_images` | `POST /images/generations` |
| `video.yaml` | `mock`, `openai_videos`, `http_task`, `local_worker` | `openai_videos` = OpenAI-style `/v1/videos` submit → poll → `/content` download; `http_task` = same flow but the file comes from a `video_url` in the status body |
| `audio.yaml` | `mock`, `openai_speech` | `POST /audio/speech`, voice from agent options |

`providers/registry.py` maps YAML `protocol` (or the legacy `kind` / `extra.protocol`) to an
implementation and resolves credentials at construction time. A disabled provider or a missing
API key raises `ProviderUnavailableError`; an unknown provider, a model/protocol mismatch or an
unsupported generation parameter raises `ConfigurationError` — always before the first call,
never halfway through a paid stage. `extra.supported_params` is enforced: declaring `temperature` unsupported
makes an agent that sets it fail fast instead of silently ignoring the value.

### Cost accounting

`extra.input_cost_per_1k` / `extra.output_cost_per_1k` (LLM) and `extra.unit_cost`
(media) are turned into `cost_usd` on every call. `agent_runs.cost_usd`,
`model_call_logs.cost_usd`, `budget_events` and `projects.spent_usd` are updated from that
single number, so the budget guard and the dashboard agree. Default mock costs are `0.0`,
which is why a full local run reports `$0`.

## 4. Agent config anatomy

```yaml
agent:
  id: script
  name: Script Agent
  enabled: true
  version: 1.0.0
  description: 将小说章节解析为结构化剧本…
model:
  provider: mock              # must exist in config/providers/llm.yaml
  model_id: mock-llm          # must be listed under that provider's models
  capability: text_reasoning  # descriptive label; the bucket comes from the agent class
  fallback_provider: mock
  fallback_model_id: mock-llm
  provider_options: {}        # forwarded verbatim to the provider adapter
generation:
  temperature: 0.3
  top_p: 0.9
  seed: 42
  max_output_tokens: 8192
  timeout_seconds: 180
  max_retries: 2
structured_output:
  enabled: true
  schema_name: script         # -> app.schemas.registry
  validation_required: true
  repair_attempts: 1
prompt:
  system: prompts/script/system.md
  user_template: prompts/script/user.md
  version: 1.0.0
runtime:
  concurrency: 2
  cache_enabled: false
  human_review_required: false
evaluation:
  enabled: true
  checks: [schema_valid, completeness, fact_traceability]
  thresholds: { completeness: 0.6 }
```

`model.capability` is documentation for humans and the admin table; the provider lookup uses
the agent's class attribute (`script` → `llm`, `video` → `video`, …). `test_config.py`
asserts that every registered agent resolves its configured provider in the right bucket.

## 5. Switching to a real model

1. Enable the provider: `config/providers/llm.yaml → openai.enabled: true`.
2. Export the key: `$env:OPENAI_API_KEY = "sk-..."` (never commit it, never put it in YAML).
3. Point the agent at the model — edit YAML or use the console's 模型配置 tab:

```yaml
model:
  provider: openai
  model_id: gpt-4.1-mini
```

4. Verify: `GET /admin/providers` shows the provider `enabled` with `has_api_key: true`, and
   `GET /admin/status` shows the resolved `config_versions`; then run `/analyze?wait=true` and
   inspect `agent_runs` (provider, model, latency, cost) or `GET /admin/model-configs/script`.

Rollback is symmetric: `DELETE /admin/model-configs/{agent}/override` returns the agent to
its YAML definition.

### Example: two local services (text + video)

The shipped YAML points the twelve text agents at a local vLLM and the video agent at a local
MiniMax-H3 service; the two vendors never have to match. Both keys live in `.env`:

```ini
QWEN_API_KEY=qwen3.8
MINIMAX_API_KEY=minimax
```

```yaml
# config/providers/llm.yaml
  qwen:
    enabled: true
    protocol: openai_chat
    url: http://127.0.0.1:8000/v1
    api_key: env:QWEN_API_KEY
    models: [qwen3.8-27b]
    extra:
      request_defaults: { reasoning_effort: medium }   # 该网关不带这个字段会 400

# config/providers/video.yaml
  minimax:
    enabled: true
    protocol: openai_videos
    url: http://127.0.0.1:8090/v1
    api_key: env:MINIMAX_API_KEY
    models: [minimax-h3]
    extra:
      content_suffix: /content          # GET /v1/videos/{id}/content 取 mp4
      max_duration_seconds: 14          # 服务上限 14.375s，超出先截断
      request_defaults: { steps: 8, seed: 42 }
```

`extra.request_defaults` is merged into every submit payload, so vendor-only knobs (thinking
effort, `steps`, or a smaller `width`/`height` when VRAM is tight) never need code changes.
`extra.request_fields` narrows which request values are sent (default `prompt`,
`duration_seconds`, `width`, `height`).

Reasoning models may narrate before answering and then close the trace with `</think>`; the
adapter extracts the JSON object from the tail instead of failing on the prose. The parser
prefers the outermost object, so nested payloads still round-trip.

Tests never touch these services: the `settings` fixture exports
`AGENT_MODEL_PROVIDER=mock`, so no test can reach a live endpoint.

## 6. Config versions (admin workflow)

| Action | Endpoint | Effect |
| --- | --- | --- |
| list | `GET /admin/model-configs` | effective config per agent + `active_version` |
| inspect | `GET /admin/model-configs/{agent}` | effective payload + version list (no implicit YAML diff; compare with the file) |
| save | `POST /admin/model-configs/{agent}/versions` | validates the full payload, writes `version+1`, deactivates the previous row, reloads the store |
| rollback | `POST /admin/model-configs/{agent}/rollback` | re-activates the newest inactive version |
| activate any | `POST /admin/model-config-versions/{id}/activate` | switch to a specific stored version |
| reset | `DELETE /admin/model-configs/{agent}/override` | drop the override, fall back to YAML |

Rules:

* Only one row per `(scope, key)` is active; `ConfigStore.apply_overrides` merges it over the
  YAML at load time, so a change takes effect without a redeploy.
* `ensure_consistent()` runs at boot: if a stored override no longer validates against the
  schema, the process refuses to start instead of failing mid-pipeline.
* Versions are immutable and checksummed (`stable_checksum`); `config_version` values in
  `agent_runs`, `tasks` and `workflow_runs` identify the exact snapshot.
* Only `scope="agent"` versions are activatable today; `provider`/`workflow` rows are reserved.

## 7. Adding a provider

1. Implement the adapter in `backend/app/providers/` (subclass the capability base:
   `LLMProvider`, `VisionProvider`, `ImageProvider`, `VideoProvider`, `AudioProvider`).
2. Register the `kind` in `providers/registry.py`.
3. Add a block to the matching `config/providers/<bucket>.yaml` with `enabled: false`,
   `models`, env-var names, timeout, concurrency and cost fields.
4. Add a test asserting the new kind resolves and that a missing key produces
   `ConfigurationError` (see `backend/tests/test_config.py`).
5. Agents need no change — point the ones you want at the new provider/model.

For hosted video vendors, prefer the `http_task` protocol (submit/poll/cancel/download paths
in `extra`); only the paths differ between vendors, not the agent.

## 8. Security checklist

* Provider YAML contains env-var **names** only; `test_config.py` fails if a `sk-`-style value
  appears in `config/providers/*.yaml`.
* `.env` is git-ignored; production keys come from a secret manager.
* `auth.allow_dev_auth` must be `false` in production; the demo identity exists for local use.
* Admin endpoints require `role == "admin"`; payloads never echo credentials.
