# ADR 0004 — Append-only versioning for content and configuration

* **Status:** Accepted
* **Date:** 2026-11-02
* **Deciders:** platform team

## Context

Film production is iterative: the operator edits a character's appearance, regenerates a
storyboard, rejects a shot, tries a different model. Three requirements follow:

1. **Do not lose work.** Overwriting a script row destroys the only record of what the previous
   gate approved, and makes "why did quality drop?" unanswerable.
2. **Do not silently change history.** A shot whose video was produced by model A must not claim
   to have been produced by model B after a config change.
3. **Cost control.** Regenerations must be countable per stage and attributable to a model and a
   config snapshot.

## Decision

* **Content is versioned by insertion.** `scripts`, `character_profiles`, `scene_profiles`,
  `directing_plans`, `storyboards`, `editing_projects`, `video_generations` each carry a
  per-project `version`; edits create a new row and update the pointer
  (`characters.canonical_profile_id`, `shots.selected_video_id`,
  `scripts`/`storyboards` "latest" queries). Old rows stay queryable forever.
* **Provenance columns on every generated row:** `agent_id`, `model_id`, `prompt_version`,
  `config_version`. The values are captured from the config snapshot at generation time, not
  resolved later.
* **Configuration is a ledger, not a file rewrite.** `config_versions(scope, key, version,
  checksum, payload, is_active)` is append-only; exactly one row per `(scope, key)` is active
  and is merged over the YAML by `ConfigStore.apply_overrides`. Rollback re-activates an older
  row; reset deactivates all rows and falls back to YAML.
* **Runs freeze their inputs.** `workflow_runs.config_versions`, `tasks.config_versions` and
  `agent_runs.config_version` record what the execution actually used, so a mid-flight config
  change cannot rewrite an in-progress run's provenance.
* **Approval is explicit.** `approved` / `approved_version` marks the version a human blessed;
  gates read that flag instead of guessing from "latest".

## Consequences

**Positive**

* Full audit trail: every artifact answers *what* produced it, *with which prompt/config* and
  *when*.
* Rejection flows are safe: a re-generated version does not destroy the one the reviewer saw.
* Rollback of a bad model change is one API call, and the ledger records who did it.
* Costs are attributable per attempt (`video_generations`, `agent_runs`, `budget_events`).

**Negative**

* Tables grow monotonically; the demo database accumulates rows per run. Needs a retention or
  archive policy before long-term production use.
* "Latest" is a query on `version_desc` in several services — a mistake here (ordering by
  `created_at`) can subtly pick the wrong row; each service has one documented accessor.
* Two sources of truth for configuration (YAML + active override) require discipline: the
  console always writes a new version, never patches YAML in place.
* Storage duplicates media on re-generation (a shot can have many clips); acceptable because
  assets are content-addressed and small in the mock world.

## Alternatives considered

1. **Mutable rows + an audit log table** — one place to look, but every read must consult the
   log to reconstruct history, and accidental overwrites are one bug away.
2. **Event sourcing for the whole domain** — maximum fidelity, disproportionate complexity for
   a pipeline whose state is already checkpointed per node.
3. **Git-backed config only** (no DB ledger) — reviewable, but changing a model in production
   then requires a deploy, which is exactly what the operator console exists to avoid.
4. **Soft deletes instead of versions** — keeps rows but cannot represent "two alternative
   storyboards exist"; the operator needs to compare, not undelete.

## Revisit when

* Version counts make list endpoints slow (add `(project_id, entity, version)` indexes and a
  "keep last N + all approved" retention rule).
* Multi-tenant usage requires per-tenant config ledgers (add `tenant_id` to `config_versions`
  before the first external tenant).
* Diffing between versions becomes a product requirement — then store a normalized diff instead
  of full payload snapshots.
