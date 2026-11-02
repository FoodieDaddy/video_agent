# Model & Provider Configuration

Three properties must hold at all times:

1. **No model id, vendor name or API key in Python.** Code asks the config store for an
   agent's `AgentConfig`; the YAML (or an active DB override) supplies provider, model,
   fallback, parameters, prompt paths and thresholds.
2. **Secrets live in the environment only.** Provider YAML stores the *name* of the env var
   (`api_key_env: OPENAI_API_KEY`). `/admin/providers` returns the name and a boolean
   `has_api_key`, never the value.
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
| `kind` (adapter), `enabled`, `models[]` | `model.provider`, `model.model_id`, `model.capability` |
| `api_key_env`, `base_url_env`, `endpoint_env` | `model.fallback_provider`, `model.fallback_model_id` |
| `timeout_seconds`, `max_concurrency` | `generation.timeout_seconds`, `generation.max_retries` |
| `extra.protocol`, `extra.submit_path` / `status_path` / `cancel_path`, poll limits | `generation.temperature`, `top_p`, `seed`, `max_output_tokens` |
| `extra.input_cost_per_1k`, `output_cost_per_1k`, `unit_cost` | `structured_output.*`, `prompt.*`, `runtime.*`, `evaluation.*` |
| `extra.supported_params`, `max_tokens_field` | `model.provider_options` (pass-through) |

## 3. Provider buckets and adapters

| Bucket file | `kind` values implemented | Notes |
| --- | --- | --- |
| `llm.yaml` | `mock`, `openai_chat` | OpenAI-compatible chat completions; works with vLLM/Azure/DashScope compatible mode |
| `vision.yaml` | `mock`, `openai_chat` | image + text messages, same wire format |
| `image.yaml` | `mock`, `openai_images` | `POST /images/generations` |
| `video.yaml` | `mock`, `http_task`, `local_worker` | submit → poll → download contract, per-vendor paths from `extra` |
| `audio.yaml` | `mock`, `openai_speech` | `POST /audio/speech`, voice from agent options |

`providers/registry.py` maps YAML `kind`/`extra.protocol` to an implementation and resolves
credentials at construction time. A disabled provider or an unset key env var raises
`ProviderUnavailableError`; an unknown provider, a model/protocol mismatch or an unsupported
generation parameter raises `ConfigurationError` — always before the first call, never halfway
through a paid stage. `extra.supported_params` is enforced: declaring `temperature` unsupported
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
