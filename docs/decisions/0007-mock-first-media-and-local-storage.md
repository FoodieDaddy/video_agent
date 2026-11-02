# ADR 0007 — Mock provider that renders real media; local storage by default

* **Status:** Accepted
* **Date:** 2026-11-02
* **Deciders:** platform team

## Context

The platform orchestrates paid, slow, GPU-bound services. That is exactly the kind of
dependency that makes a codebase untestable: without keys, nothing runs; with keys, the suite
is slow, expensive and non-deterministic, and CI cannot run at all.

Two failure modes are common in this situation and both are unacceptable here:

* stub everything and never exercise the media path (then FFmpeg, storage and timeline bugs
  ship to production);
* require real credentials to run anything (then contributors and CI cannot verify a change).

## Decision

* **Ship a first-class `mock` provider per capability bucket** (`llm`, `vision`, `image`,
  `video`, `audio`), enabled by default in `development` and `test`.
* **The mock produces real files, deterministically.** Text is generated from structured
  heuristics (`utils/narrative.py`), images are drawn with Pillow, clips are rendered by
  FFmpeg from generated frames, audio is a normalised silent/synthesised WAV, subtitles are
  real SRT. So the mock exercises the entire media pipeline: storage writes, `/media/{key}`
  serving, timeline assembly, subtitle burn-in, final H.264 export.
* **Cost is zero and latency is small**, so the suite can run the *full* pipeline (including a
  gate-by-gate HTTP run) in seconds.
* **Real providers are configured, never hardcoded** (ADR 0001). Enabling `openai` or a video
  vendor is a YAML flag plus an env key; agent code is unchanged.
* **Storage defaults to the local filesystem** (`STORAGE_ROOT`), with S3/MinIO available behind
  `STORAGE_BACKEND=s3`. The database only ever stores `storage_key`, so switching backends is a
  deployment concern, not a schema concern.
* **The sample novel ships in the repo** (`samples/novel_sample.txt`) and is importable through
  `POST /projects/{id}/upload?sample=true`, which is what the console's demo button uses.

## Consequences

**Positive**

* `pytest` and `scripts/smoke_pipeline.py` run with no network, no keys, no GPU, in seconds —
  CI needs only Python and FFmpeg.
* Media bugs are caught by tests (they were: frame/clip generation, missing audio, subtitle
  burn-in all had to work for the pipeline test to pass).
* Demo is honest: the exported 30-second film is a real MP4 produced by the real render path.
* Determinism (seeded generation, fixed durations) makes assertions stable.

**Negative**

* The mock's output is obviously not "good film"; quality evaluation scores are structural, not
  aesthetic — they verify plumbing, not taste.
* Two provider implementations to keep in sync with the base interfaces; a new capability must
  add both.
* Local storage with a bind mount is fine for one container and wrong for horizontal scaling
  (shared volume or S3 required).
* Mock-provider defaults mean a fresh production deploy silently uses fake models until someone
  changes YAML — mitigated by `/admin/status` and the provider `enabled` flags, but it is a
  real footgun worth a startup warning.

## Alternatives considered

1. **`unittest.mock` patches in tests only** — no integration coverage of media/storage; agents
   would still need real keys to run manually.
2. **Recorded fixtures (VCR-style cassettes)** — realistic but brittle: every prompt change
   invalidates cassettes, and no media is produced.
3. **Require a local model server** (Ollama/ComfyUI) — closer to production, but a heavy
   dependency for tests and CI.
4. **Reference-image assets checked into the repo** instead of generated frames — simpler, but
   hides the actual generation path and bloats the repository.

## Revisit when

* Real providers become the norm for development: keep mock as the CI default but add a
  `--real` marker for a nightly run against a paid account.
* Media volume makes local storage slow: default to S3/MinIO in `development` too.
* Quality evaluation needs to be meaningful: add reference-based metrics (image similarity,
  audio presence, shot-ratio checks) that work with both mock and real providers.
