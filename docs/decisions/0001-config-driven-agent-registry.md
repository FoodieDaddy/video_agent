# ADR 0001 — Configuration-driven agents; no model in Python

* **Status:** Accepted
* **Date:** 2026-11-02
* **Deciders:** platform team

## Context

The product must survive model churn: today's best Chinese-capable LLM is next quarter's
second choice, image and video vendors are replaced quarterly, and a single project may need a
cheap model for outlines and an expensive one for storyboards. Hardcoding `model="gpt-4o"` in
an agent class turns every such change into a code review, a deploy, and a mixed-version
fleet — and it silently breaks the audit trail ("which model produced this script?").

At the same time, *the request shape* genuinely differs per agent (temperature, max tokens,
repair budget, evaluation thresholds). A single global model config cannot express that
either.

## Decision

Each agent owns one YAML file under `config/agents/<id>.yaml` that is the complete,
authoritative description of how that agent runs:

```
agent:      identity, enabled flag, version, description
model:      provider, model_id, capability, fallback_provider/model, provider_options
generation: temperature, top_p, seed, max_output_tokens, timeout_seconds, max_retries
structured_output: enabled, schema_name, validation_required, repair_attempts
prompt:     system, user_template, version
runtime:    concurrency, cache_enabled, human_review_required
evaluation: enabled, checks, thresholds
```

Providers are catalogued separately per capability bucket (`config/providers/llm.yaml`, …),
so one provider serves many agents; provider YAML references **environment variable names**
for credentials. `ConfigStore` loads both, computes a checksum per agent config
(`config_version`), and the resulting values are frozen onto every `agent_run`.

Business code never names a model, a vendor or a parameter; it asks
`runtime.config_store.agent(agent_id)` and later `run_agent(...)`. Swapping a model is a YAML
edit (or an admin console change) plus a config-version row.

## Consequences

**Positive**

* Model/vendor swap without touching Python; no redeploy needed for a DB-backed override.
* Per-agent tuning (a strict script agent, a creative storyboard agent) in one place.
* Reproducibility: `config_version` + `prompt_version` on `agent_runs`/`tasks`/`workflow_runs`
  answer "what produced this?" months later.
* Secrets cannot leak into the repo because YAML only stores env-var names.

**Negative**

* A wrong YAML (typo'd provider, model not listed) fails at load/execute time, not at compile
  time — mitigated by `test_config.py` asserting registry ↔ YAML ↔ provider parity, and by
  `ensure_consistent()` refusing to boot on invalid stored overrides.
* Two files must be kept in sync when adding an agent (class + YAML); the registry test makes
  the omission loud.
* Reading a config requires indirection through the store; debugging means inspecting YAML and
  the active override row, not reading a constructor.

## Alternatives considered

1. **Constants in Python per agent** — simplest, but reintroduces the deploy-per-model-swap
   problem and invites drift between agents.
2. **One global model config** (`config/app.yaml → model: {...}`) — cheap, but cannot express
   "storyboard uses a stronger model than the chapter summarizer", which the pipeline needs.
3. **Environment-variable-only overrides** — works for one dimension (provider), not for the
   matrix of provider × model × parameters × prompts.
4. **Database-only configuration** — solves hot reload but loses reviewability: config changes
   would never appear in a diff. YAML as source of truth + DB overrides keeps both.

## Revisit when

* Agents need runtime routing logic the config schema cannot express (e.g. dynamic model
  selection by budget) — that belongs in a policy layer, not in YAML.
* Config count grows past a few dozen and hand-edited YAML becomes the bottleneck; then
  generate YAML from an admin UI, keeping YAML as the committed artifact.
