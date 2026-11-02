# Agent Catalogue

Every agent is a subclass of `agents/base.py::BaseAgent` registered in
`agents/registry.py::AGENT_CLASSES` and configured by `config/agents/<id>.yaml`. A missing
or disabled YAML file is a configuration error surfaced by `/admin/model-configs`, not a
runtime crash mid-pipeline.

## 1. Execution contract

`services/agent_runner.py::run_agent` is the only entry point:

1. load `config.agent(id)` (YAML + active DB override) and instantiate the class;
2. `agent.validate_input(payload)` → pydantic model;
3. create an `AgentRun` row (`running`, provider, model, config version, input, capability);
4. `agent.execute(inputs, ctx)` renders the prompt, calls the provider, validates the
   structured output, repairs/retries/falls back per config, then runs `evaluation` checks;
5. persist output/status/latency/cost/tokens and emit cost to `budget_events` / `projects.spent_usd`.

Per-agent config keys (`config/agents/*.yaml`):

```yaml
agent:      { id, name, enabled, version, description }
model:      { provider, model_id, capability, fallback_provider, fallback_model_id, provider_options }
generation: { temperature, top_p, seed, max_output_tokens, timeout_seconds, max_retries }
structured_output: { enabled, schema_name, validation_required, repair_attempts }
prompt:     { system, user_template, version }
runtime:    { concurrency, cache_enabled, human_review_required }
evaluation: { enabled, checks[], thresholds{} }
```

## 2. Registered agents (17)

Default provider for all of them is `mock`, so the pipeline is runnable offline.

| Agent id | Capability | Output schema | Prompt(s) | Responsibility |
| --- | --- | --- | --- | --- |
| `orchestrator` | llm | `orchestrator_plan` | `prompts/orchestrator/*` | plans stages/tasks and re-entry points |
| `script` | llm | `script` | `prompts/script/*` | novel chapters → structured script (summary, scenes, events, dialogue, themes, tone) |
| `character_extraction` | llm | `character_extraction` | `prompts/character/extraction_*` | identify characters, roles, aliases, first appearance |
| `character_description` | llm | `character_profile` | `prompts/character/description_*` | appearance/personality prompt-ready profile |
| `character_vision` | vision | `character_vision` | `prompts/character/vision_*` | describe uploaded reference images / check likeness |
| `character_image` | image | — (image output) | `prompts/character/image_prompt.md`, `image_negative.md` | portrait/full-body/turnaround/expression sheets |
| `character_consistency` | vision | `character_consistency` | `prompts/character/consistency_*` | score whether a generated frame matches the approved sheet |
| `scene_extraction` | llm | `scene_extraction` | `prompts/scene/extraction_*` | locations with dedupe (旧书店 vs 书店) |
| `scene_description` | llm | `scene_profile` | `prompts/scene/description_*` | time of day, weather, props, palette, prompt hints |
| `director` | llm | `directing_plan` | `prompts/director/*` | visual style, pacing, camera language, color script, music direction |
| `storyboard` | llm | `storyboard` | `prompts/storyboard/*` | shot list: camera, action, dialogue, duration, visual/negative prompt |
| `prompt` | llm | `prompt_pack` | `prompts/prompt/*` | turns a shot description into provider-ready prompts |
| `video` | video | — (video output) | `prompts/video/*` | per-shot clip generation (provider or mock FFmpeg) |
| `audio` | llm | `audio_plan` | `prompts/audio/*` | narration/dialogue segmentation and timing |
| `audio_voice` | audio | — (audio output) | `prompts/audio/voice_*` | TTS synthesis per line/voice |
| `editing` | llm | `editing_plan` | `prompts/editing/*` | timeline order, transitions, subtitle track |
| `evaluation` | llm | `evaluation` | `prompts/evaluation/*` | score DB-derived metrics, recommend accept/retry |

Capability labels in the YAML (`text_reasoning`, …) are descriptive; the **bucket** used to
resolve a provider is the agent class attribute (`capability`), which must exist in
`config/providers/<capability>.yaml` (`llm`, `vision`, `image`, `video`, `audio`). The
`test_config.py` suite asserts this parity for every registered agent.

## 3. Adding an agent

Follow the same order the spec (§8.1) prescribes:

1. **Input/output schemas** — add `backend/app/schemas/<name>.py` (pydantic) and register the
   name in `schemas/registry.py`.
2. **Agent class** — subclass `StructuredLLMAgent` (text/vision) or `MediaAgent`
   (image/video/audio); set `agent_id`, `capability`, `schema_name`, `input_model` and
   `output_model`, then override `build_variables()` and/or `postprocess()` when the payload
   needs shaping. Retry/repair/fallback live in the base class — do not re-implement them.
3. **Registry** — add `"my_agent": MyAgent` to `agents/registry.py::AGENT_CLASSES`.
4. **Config** — copy an existing `config/agents/*.yaml`, change `agent.id`, `model`,
   `structured_output.schema_name` and `prompt.*`.
5. **Prompts** — add `config/prompts/<group>/system.md` and `user.md`. Rendering uses
   `string.Template.safe_substitute` (`$variable`, resolved from `build_variables()` and
   stringified), and the prompt checksum is recorded as `prompt_version` on every run.
6. **Workflow** — if the agent is a pipeline stage, add a handler in
   `services/workflow_handlers.py::HANDLERS` and a node in `config/workflows/*.yaml`.
7. **Tests** — extend `backend/tests/test_config.py` implicitly (parity is automatic) and add
   a behavioural test next to the existing ones.
8. **Docs** — add a row to the table above (and a `docs/agents/<id>.md` when the agent needs
   more than a paragraph).

No route, serializer or console change is required for a new agent unless the output must be
shown on a new tab; `/admin/model-configs` picks it up from the registry automatically.

## 4. Structured output, repair and fallback

Configured per agent, implemented once in the base class:

* `structured_output.enabled: true` → the prompt asks for JSON; the response is parsed and
  validated with the pydantic schema named by `schema_name`.
* `validation_required: true` → validation failures raise `ValidationAppError` (recorded on
  the `AgentRun`) rather than returning partial data.
* `structured_output.repair_attempts` → a repair round-trip that feeds the validation error
  back to the model.
* `generation.max_retries` → transport/5xx retries with the same provider.
* `model.fallback_provider` / `fallback_model_id` → one attempt through a different provider
  when the primary fails; the `AgentRun` records which model actually answered.
* `evaluation.enabled` with `checks`/`thresholds` → cheap post-checks (schema validity,
  completeness, traceability) that can fail a stage before it poisons the next one.

## 5. Prompt authoring rules

* System prompts state role, hard constraints and the JSON contract; user templates carry the
  data. Never embed project-specific content in the system prompt.
* Keep Chinese product language in prompts (the target output is Chinese) while code,
  comments and docs stay English.
* Bump `prompt.version` when the meaning changes, so `agent_runs.prompt_version` stays a
  reliable audit key.
* Reference schemas by `schema_name`, not by file path; `scripts/export_schemas.py` writes
  `config/schemas/*.json` for prompt embedding and tool use.
