# Testing

```powershell
python -m pytest                       # whole suite (~25 s with the mock provider + FFmpeg)
python -m pytest backend/tests/test_api.py -q
python -m pytest -k pipeline -vv
python -m pytest --cov=app --cov-report=term-missing   # needs pytest-cov
python scripts/smoke_pipeline.py       # script-level end-to-end, prints artifacts
```

`pyproject.toml` sets `pythonpath = ["backend"]` and `testpaths = ["backend/tests"]`, so no
`PYTHONPATH` juggling or `conftest.py` at the repo root is needed.

## 1. Strategy

| Level | File | What it proves |
| --- | --- | --- |
| Contract | `test_config.py` | every registered agent has a YAML + prompts + a resolvable provider in its capability bucket; config checksums are stable; the default workflow has handlers and ≥3 review gates; provider YAML never contains secrets |
| Unit | `test_narrative.py` | chapter splitting, character-name heuristics, location extraction/dedupe, speech duration scaling |
| API contract | `test_api.py` | health/meta, console assets, project isolation (403), story intake + SSE frames, character assets + approval, admin config versions incl. rollback and role enforcement, error envelope |
| API end-to-end | `test_pipeline_api.py` | full run over HTTP with four gate approvals: shots, videos, audio, editing, render, evaluation, export, media bytes, SSE end frame, project completion |
| Service | `test_workflow_service.py` | rejected gate reopens a fresh review at the same stage; `run_public` checkpoints; project summary counters |

Everything runs against the **mock provider**, which still writes real PNG/MP4/WAV files via
FFmpeg — so a green suite also validates media handling, not just JSON.

## 2. Fixtures (`backend/tests/conftest.py`)

Each test gets a throwaway world, which is why the suite is order-independent and safe to run
in parallel later:

```python
@pytest.fixture()
def settings(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("APP_ENV", "test")          # config/environments/test.yaml
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(data_dir / 'studio.db').as_posix()}")
    monkeypatch.setenv("STORAGE_ROOT", str(data_dir / "storage"))
    get_settings.cache_clear()
    return load_settings(data_dir=data_dir)
```

* `settings` — isolated SQLite file + storage root; `APP_ENV=test` forces inline tasks,
  `max_workers=1` and `WARNING` logs.
* `app` / `client` — `create_app(settings)` inside `TestClient` so the lifespan boots the
  engine, schema, runtime and stored config overrides.
* `runtime` — the same `AppRuntime` the app used (config store, storage, runner).
* `headers` — `tester` (plain user) and `admin` identity headers.
* `project` — a created project owned by `tester`.

Because `get_settings` is `lru_cache`d, the fixture clears it; otherwise the first test's
database would leak into the next one.

## 3. Conventions

* **Never assert on mock internals** (exact generated text). Assert on structure, counts,
  versions, status transitions and file existence — those are the real contracts.
* **Always drive the workflow to the gate you need** rather than calling services out of
  order: `POST /workflows/start?wait=true` returns as soon as it parks in
  `awaiting_review`, so `characters` only exist after that call (running `/analyze` alone
  produces a script and nothing else).
* **Use `?wait=true`** in tests; SSE is tested explicitly with the stream endpoint.
* **Keep the suite key-free.** A test that needs a real key belongs behind a marker and is
  skipped by default.
* **Time budget:** a new HTTP e2e test should stay under ~5 s with the mock provider. If it
  needs more, it is probably rendering too many shots.

## 4. CI expectations (`.github/workflows/ci.yml`)

1. `ruff check backend` — lint (`E,F,I,W,UP,B`, line length 110).
2. `pytest` — the full suite on Ubuntu with `ffmpeg` installed via `apt-get`.
3. Optionally `python scripts/export_schemas.py` and fail if `config/schemas/*.json` changed,
   which keeps the JSON schemas committed alongside the pydantic models.

Mypy is configured but advisory (`ignore_missing_imports = true`).

## 5. Regressions worth remembering

* **Workflow cursor persistence.** The engine mutates `state` in place; assigning the same
  dict back to `run.state` produces no UPDATE in SQLAlchemy, so the run replays stages from
  the top (`storyboard` v1…v4, shots never approved). Always `run.state = dict(state)`.
  `test_pipeline_api.py` would fail loudly if this regressed.
* **Provider lookup uses the agent class capability**, not `model.capability`. Querying
  `store.provider("text_reasoning", "mock")` raises `ConfigurationError`; use
  `describe_agents()` → `entry["capability"]`.
* **Demo identity.** Sending `X-User-Id: user_demo` makes that user a plain member, so
  `/admin/*` returns 403. To act as the admin in tests, send the `headers["admin"]` fixture
  (`X-User-Role: admin` with a non-demo id) or omit `X-User-Id` entirely.
* **FFmpeg availability.** `utils/ffmpeg.py` resolves the binary from `FFMPEG_BIN`, PATH or a
  bundled copy; tests fail with a descriptive error rather than silently skipping.

## 6. Adding a test

1. Put HTTP-level tests in `test_api.py` / `test_pipeline_api.py`; service-level in a new
   `test_<service>.py`; pure helpers in `test_<util>.py`.
2. Reuse the fixtures — do not build your own app or database.
3. Prefer one behaviour per test with an explicit assertion message for the workflow-state
   assertions (`assert run["status"] == "awaiting_review", run`).
4. If you add a stage to `novel_to_video.yaml`, extend `EXPECTED_STAGES` in
   `test_pipeline_api.py` so the gate order stays asserted.
