# Database Schema

SQLite in development/test, PostgreSQL in production (`DATABASE_URL`). Schema is created
by SQLAlchemy metadata (`init_schema()`); there is no migration tool yet, so destructive
changes require a manual migration (see ADR 0002).

Conventions shared by every table:

* `id` — prefixed string (`prj_`, `doc_`, `char_`, `shot_`, `run_`, `task_`, `asset_`, …).
* `created_at` / `updated_at` — UTC timestamps (`ids.utcnow()`).
* JSON columns hold domain payloads (`content`, `profile`, `camera`, `state`, …); the
  database never stores binary media, only `storage_key` references.
* Every content-producing table carries provenance: `model_id`, `config_version`
  (and `prompt_version` where a prompt is involved).

## 1. Projects and identity

| Table | Purpose |
| --- | --- |
| `users` | minimal identity (id, email, name, role, is_active) — real auth is external |
| `projects` | name, owner, status, language, genre, aspect ratio, budget limit/spent, settings, config version |
| `project_members` | project-scoped membership with role (`owner`/`editor`/`viewer`) |

`project.status` follows `draft → ingested → script_ready → characters_ready →
storyboard_ready → video_ready → edited → completed` (plus `archived`); the vocabulary is
`ProjectStatus` in `core/constants.py`. `projects.spent_usd` is maintained by the agent
runner from provider cost estimates, so budget enforcement reads one row.

## 2. Story intake

| Table | Purpose |
| --- | --- |
| `source_documents` | uploaded novel (filename, content type, `asset_id`, size, parse status/error, meta) |
| `story_chapters` | deterministic chapter split: index, title, content, `char_count`, summary |
| `story_events` | script-derived events: order, title, description, chapter index, location, characters, importance |

Parsing is deterministic (regex on 第X章/Chapter N + blank-line fallback), so re-parsing a
document is cheap and never calls a model.

## 3. Script

| Table | Purpose |
| --- | --- |
| `scripts` | one row per version: title, logline, synopsis, genre, tone, `content` (JSON script), `source_document_id`, provenance, `approved` |

`content` contains `{summary, scenes, events, dialogue, themes, tone, characters_mentioned}`;
the schema is `config/schemas/script.schema.json`. Edits (PATCH) create a new version rather
than mutating a row.

## 4. Characters

| Table | Purpose |
| --- | --- |
| `characters` | canonical identity: name, aliases, role type, status, `canonical_profile_id`, summary, appearance keywords, `approved_version` |
| `character_profiles` | versioned description payload (`content`), source (`extracted`/`edited`/`imported`), approved flag, provenance |
| `character_assets` | generated sheets (portrait/full_body/turnaround/expression/costume) → `asset_id`, version, approved |
| `character_relationships` | source/target + relation + strength |
| `character_states` | story-time snapshot: age, emotion, injury, location, items |
| `character_costumes` | costume/wardrobe per story time with visual keywords and asset |
| `character_voices` | TTS binding: voice id, provider, model, style, sample asset, consent flag |

## 5. Scenes

| Table | Purpose |
| --- | --- |
| `scenes` | name, slug, status, summary, `canonical_profile_id`, `approved_version`, chapter index |
| `scene_profiles` | versioned scene description (time of day, weather, props, palette, prompt hints) |
| `scene_assets` | generated stills/plates → `asset_id`, version, approved |

## 6. Directing, storyboard, shots

| Table | Purpose |
| --- | --- |
| `directing_plans` | versioned director plan (`content`: visual style, pacing, camera language, color script, music direction) |
| `storyboards` | versioned board header (`directing_plan_id`, title, notes, approval, provenance) |
| `shots` | the unit of production: order, scene, description, action, `camera` JSON, characters, dialogue, duration, visual/negative prompt, reference assets, `selected_video_id`, `selected_audio_id`, approved |
| `shot_characters` | shot ↔ character link with costume/state/action/emotion |

Shots inherit `config_version`/`prompt_version` from generation time, so re-generating a
board does not silently change previous provenance.

## 7. Media

| Table | Purpose |
| --- | --- |
| `assets` | every stored file: kind (`image`/`video`/`audio`/`subtitle`/`film`/`export`), `storage_key`, mime, size, dimensions, duration, checksum, provenance, meta |
| `video_generations` | one row per attempt per shot: version, provider/model, `task_ref`, `asset_id`, params, references, prompt + versions, duration, cost, error, `selected` |
| `audio_tracks` | TTS lines: shot, character, kind (narration/dialogue/sfx), asset, text, voice, language, version, duration, start offset, status, provenance |
| `editing_projects` | versioned timeline (`timeline` JSON clips/tracks), `output_asset_id`, `subtitle_asset_id`, `manifest`, duration, render status/error |
| `asset_versions` | generic audit link: entity type/id ↔ asset/version/note/active |

`assets.storage_key` is content-addressed (`projects/<project>/<kind>/<hash>-<name>`), which
makes duplicate uploads free and keeps the `/media/{key}` route stateless.

## 8. Reviews and workflow

| Table | Purpose |
| --- | --- |
| `reviews` | gate record: stage, target type/id, status (`pending`/`approved`/`rejected`), comment, decision JSON, reviewer, `reviewed_at` |
| `review_comments` | threaded discussion on a review |
| `workflow_runs` | definition + version, status, `current_node`, `awaiting_stage`, `pending_review_id`, `state` (`next_index`, `outputs`, config version), frozen `config_versions`, `task_id`, error, timings |
| `workflow_checkpoints` | one row per node execution: node id/type, status, summary, state snapshot, output, error |

`reviews` is intentionally generic (`target_type`/`target_id`) so new gate kinds (e.g. a shot
re-take gate) do not need a schema change.

## 9. Tasks and operations

| Table | Purpose |
| --- | --- |
| `tasks` | type, status, stage, progress, message, payload, result, error, attempts/max, frozen `config_versions`, timings |
| `task_events` | append-only progress log: level, event type, message, progress, data — the SSE source |
| `agent_runs` | one row per agent execution: provider/model, config+prompt version, input/output, latency, cost, tokens, attempts, error, meta |
| `model_call_logs` | per provider call: provider, capability, model, request id, status, latency, cost, tokens, request meta, error |
| `budget_events` | cost ledger by project/task/category |
| `config_versions` | config ledger: scope (`agent`/`provider`/`workflow`), key, version, `checksum`, `payload`, `is_active`, author, note |
| `prompt_versions` | prompt template snapshots with checksum |

Two ledgers exist on purpose: `agent_runs` answers "what did the model return?", while
`model_call_logs` answers "what did we call, how often, and what did it cost?" — a single
agent can make several calls (repair, fallback).

## 10. Querying notes

* No explicit secondary indexes are declared yet (SQLite tolerates it at this scale). When
  moving to PostgreSQL, add `(project_id, created_at)` on `tasks`, `assets`,
  `agent_runs`, `budget_events` and `(task_id, created_at)` on `task_events` first — those
  are the predicates every list endpoint uses.
* `workflow_runs.state` is JSON and mutated through SQLAlchemy; always assign a **copy**
  (`run.state = dict(state)`) or the ORM will not emit an UPDATE.
* Deletion is avoided: rows are versioned or status-flipped so history stays auditable.
