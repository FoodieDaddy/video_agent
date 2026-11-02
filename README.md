# AI Film Studio

Configurable, extensible, human-in-the-loop multi-agent platform that turns a novel
into a finished short film: `novel → chapters → script → characters/scenes → review →
directing → storyboard → review → shots → review → audio/subtitles → editing →
evaluation → final review → export`.

Two rules shape the whole codebase:

1. **No model is hardcoded in Python.** Every agent reads provider, model, fallback,
   generation parameters, structured-output policy, prompt references, runtime limits
   and evaluation thresholds from `config/agents/<agent>.yaml`. Swapping a vendor or a
   model is a YAML/console change plus a restart-free config version bump.
2. **Every stage is reviewable and reproducible.** Content is versioned (scripts,
   profiles, storyboards, videos, edit projects), config versions are frozen per task,
   and four workflow gates block on a human decision before expensive work continues.

The repository ships a **mock provider** that produces real files (PNG frames, silent
MP4 clips, WAV narration) through FFmpeg, so the entire pipeline runs offline with no
API key and no GPU — tests and the smoke script depend on exactly that.

The shipped agent YAML points the twelve text agents at a local vLLM (`qwen`,
`http://127.0.0.1:8000/v1`) and the video agent at a local MiniMax-H3 service (`minimax`,
`http://127.0.0.1:8090/v1`); both keys live in `.env`. To run fully offline instead, set
`AGENT_MODEL_PROVIDER=mock` or edit the `model:` block of `config/agents/*.yaml` — see
[model configuration](docs/model_configs/README.md).

## Quick start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# optional: media tools (needed for real rendering, not for tests)
ffmpeg -version

# run the API + built-in console
uvicorn app.main:app --app-dir backend --reload --port 8000

# or: pick a free port, wait for /health and open the browser for you
python backend\app\desktop.py --port 8010
```

Open <http://127.0.0.1:8000/> for the console (create a project → 导入示例小说 →
一键完整流程 → approve the four gates). API docs live at `/docs`, health at `/health`.

Offline end-to-end check without the server:

```powershell
python scripts/smoke_pipeline.py        # full workflow, mock provider, auto-approves gates
python -m pytest                        # unit + integration + HTTP e2e suite
```

## Windows one-click install

Releases ship two executables — no Python, no Docker, no admin rights required:

| File | What it does |
| --- | --- |
| `install.exe` | Downloads a private CPython 3.12 when the machine has none, creates `%LOCALAPPDATA%\AIFilmStudio\venv`, installs the dependencies from `pyproject.toml`, copies the app, writes `start-studio.cmd`, adds desktop/Start-menu shortcuts and an uninstall entry |
| `uninstall.exe` | Stops the studio, removes shortcuts, the registry entry, the venv and the app files; **keeps** `data\` unless you pass `--purge` |

Double-click `install.exe`, wait for the dependency step, and the console opens in your browser.
`install.exe --dry-run` prints the plan first; `--dir`, `--port`, `--extras s3,pdf`,
`--no-shortcuts`, `--no-registry`, `--no-launch` and `--with-ffmpeg` are also available. Full walk
through: [docs/manual/README.md](docs/manual/README.md) § 2.2.

Building the artifacts (Windows; the script bootstraps its own build interpreter):

```powershell
python scripts/build_installers.py    # -> dist\install.exe + dist\uninstall.exe
```

A clean python.org CPython is installed into `build/` first, because an executable frozen from a
conda interpreter cannot load `_ssl` and would be unable to download anything. Both exes run
`--selftest` (SSL, embedded payload, FFmpeg, arch) before the build is considered successful —
see [ADR 0008](docs/decisions/0008-windows-one-click-installer.md).

## What you get

| Layer | Highlights |
| --- | --- |
| Config | `config/app.yaml` < `config/environments/<APP_ENV>.yaml` < environment variables; provider YAML references **env var names only** |
| Agents | 17 registered agents (orchestrator, script, character ×4, scene ×2, director, storyboard, prompt, video, audio ×2, editing, evaluation) |
| Providers | `mock` (offline) and `openai_chat` (any OpenAI-compatible gateway); capability buckets `llm/vision/image/video/audio` |
| Workflow | YAML-defined node list, persisted cursor, per-node checkpoints, gate nodes backed by `Review` rows |
| Tasks | Thread-based runner, `task_events` table as the SSE source (multi-process safe), cancellation, retries |
| Media | FFmpeg/ffprobe helpers, local or S3 storage, character sheets, per-shot clips, TTS + subtitles, timeline render, export |
| Review | Approve/reject with comments; rejection re-opens a fresh review for the same stage; edits are versioned |
| Admin | Per-agent config editor backed by a `config_versions` ledger with activation and rollback |
| Tests | 22 pytest cases: config contracts, narrative utilities, HTTP contracts/isolation/SSE, workflow gates, full mock pipeline |

## Repository layout

```
backend/app/            application (DDD-ish: core, models, schemas, providers, agents, services, api)
backend/tests/          pytest suite (unit, service, HTTP e2e)
config/                 app.yaml, agents/, providers/, workflows/, prompts/, schemas/, environments/
deployment/             docker/ (image) and nginx/ (reverse proxy reference config)
docs/                   manual (操作手册), architecture, api, database, agents, model_configs, testing, decisions (ADR)
installer/              stdlib-only install.py / uninstall.py frozen into dist\install.exe and dist\uninstall.exe
samples/                novel_sample.txt used by the console import button and tests
scripts/                smoke_pipeline.py, export_schemas.py, build_installers.py
web/                    no-build console (plain HTML/CSS/JS) served by FastAPI
docker-compose.yml      single-container API stack (SQLite + local storage, tasks inline)
```

## Documentation

- [docs/manual/README.md](docs/manual/README.md) — 操作手册 (operator manual: start, run, review, switch models, troubleshoot)
- [docs/architecture/overview.md](docs/architecture/overview.md) — layers, request/task flow, workflow engine
- [docs/api/README.md](docs/api/README.md) — endpoint reference, auth, SSE framing, error envelope
- [docs/database/schema.md](docs/database/schema.md) — tables grouped by bounded context
- [docs/agents/README.md](docs/agents/README.md) — agent catalogue and the "add an agent" checklist
- [docs/model_configs/README.md](docs/model_configs/README.md) — config layers, params, versions, adding a provider
- [docs/testing/README.md](docs/testing/README.md) — how to run/extend the suite, CI expectations
- [docs/decisions/](docs/decisions/README.md) — architecture decision records

## Configuration at a glance

```powershell
Copy-Item .env.example .env          # never commit .env
$env:APP_ENV = "development"         # development | test | production
$env:DATABASE_URL = "sqlite:///./data/studio.db"
$env:STORAGE_ROOT = "./data/storage"
$env:OPENAI_API_KEY = "sk-..."       # only when you actually switch a provider to openai
```

To leave the offline world, edit one agent YAML (or use the console's 模型配置 tab) — for
example `config/agents/script.yaml`:

```yaml
model:
  provider: openai
  model_id: gpt-4.1-mini
```

and enable that provider in `config/providers/llm.yaml`. No Python change is required.

## Docker

```powershell
docker compose up --build          # http://127.0.0.1:8000/
```

`data/` lives on the `studio-data` volume mounted at `/data`, so the SQLite database
and generated media survive rebuilds (`docker compose down -v` drops them).

## Status and known gaps

- The demo identity is an administrator when `X-User-Id` is absent; production must
  disable `auth.allow_dev_auth` and terminate auth at the gateway (see ADR 0005).
- `tasks.inline: false` expects an external worker that polls `tasks`; only the inline
  runner ships today. Keep `inline: true` (single container) until that worker exists.
- The console is intentionally vanilla JS: it exercises the API without a build step.
- `install.exe` / `uninstall.exe` are unsigned, so SmartScreen warns on first run; installing
  needs network access to PyPI (and to python.org when the machine has no Python 3.11+).

## License

Proprietary sample code. Replace this section before any redistribution.
