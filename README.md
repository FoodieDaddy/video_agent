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
2. **内容版本和审核关卡可追踪。** 剧本、档案、分镜、视频和剪辑项目保留版本，
   任务与运行记录保存配置指纹，四个人工关卡用于暂停和审核。当前未冻结完整执行配置，
   恢复执行仍可能读取当前定义；外部调用的幂等与崩溃恢复需要独立治理。

The repository ships a **mock provider** that produces real files (PNG frames, silent
MP4 clips, WAV narration) through FFmpeg, so the entire pipeline runs offline with no
API key and no GPU — tests and the smoke script depend on exactly that.

默认 12 个文字类智能体使用 `fast_gateway`。供应商地址、模型名和密钥统一在
项目根目录 `.env` 中管理，分别是 `FAST_GATEWAY_BASE_URL`、`FAST_GATEWAY_MODEL`、
`FAST_GATEWAY_API_KEY`（当前地址与模型见 `.env.example`）。正常启动及模块 1～3
的默认检查都会自动读取，无需每次
输入密钥、`export` 或传 `--base-url/--model`。`.env` 是本机私有文件，不提交 Git。
已有进程环境变量优先于 `.env`；修改 `.env` 后重新启动应用或重新运行检查脚本。
离线检查使用 `--offline`，不会请求真实文字模型；无本地 `.env` 的测试环境提供
非敏感的假地址/模型名即可（CI 已配置），不需要真实密钥。

本地 Qwen 配置保留为可切回的禁用选项。视频智能体仍使用独立的 MiniMax-H3
服务（`http://127.0.0.1:8090/v1`）；图像、视觉和语音能力保持各自配置，文字模型
配置不代表这些媒体服务已经就绪。详见 [模型配置](docs/model_configs/README.md)。

## Quick start

```powershell
# 先安装 Python 3.11+ 和 uv，再按锁文件创建项目环境
uv sync --frozen --extra dev

# 媒体工具：完整 mock 测试和实际渲染都需要
ffmpeg -version

# run the API + built-in console
uv run --frozen --extra dev uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010 --workers 1

# 桌面入口也可打开控制台；使用前先确认没有已有实例
# uv run --frozen --extra dev python backend\app\desktop.py --port 8010
```

Open <http://127.0.0.1:8010/> for the console (create a project → 导入示例小说 →
一键完整流程 → approve the four gates). API docs live at `/docs`, health at `/health`.

新版“片场 Studio”默认连接真实后端并读取项目，接口统一封装在 `web/api.js`。
`/?mode=demo` 才进入有明确标识的内存示例空间；也可在“工作室设置”中切换模式。
真实生成仍需明确提交，审核默认只保存结论。经典控制台保留于 `/legacy/index.html`。
页面结构、交互边界和前端测试见[前端说明](web/README.md)。

macOS/Linux 已有虚拟环境时，直接启动一个实例即可（若已有实例，先停止旧实例）：

```bash
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8010 --workers 1
```

模块检查直接使用正式 Provider 和根目录 `.env`，均无需启动网页服务；模块 2、3
会将测试数据库和文件存储隔离到临时沙箱，结束后清理：

```bash
.venv/bin/python scripts/checks/module1_config_llm.py
.venv/bin/python scripts/checks/module2_script_agent.py
.venv/bin/python scripts/checks/module3_characters_scenes.py
```

模块 3 的上游剧本仍是 mock 夹具，四类目标 Agent 在默认模式下走真实供应商。
纯离线验证给模块 2、3 添加 `--offline`；模块 1 的 `--offline` 仅跳过真实探针。

Offline end-to-end check without the server:

```powershell
uv run --frozen --extra dev python scripts/checks/quality_gate.py
uv run --frozen --extra dev python scripts/checks/quality_gate.py --scope tests
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
| Tests | 配置与 Provider 契约、模块边界、叙事工具、HTTP/隔离/SSE、工作流关卡和完整 mock 流程；以当前测试收集结果为准 |

## Repository layout

```
backend/app/            modules/ 业务与技术模块；bootstrap/ 组装；api/models/schemas；旧目录兼容入口
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

- [贡献指南](CONTRIBUTING.md) — 开发、验证、评审和单实例约定
- [工程与注释规范](docs/development/engineering-standards.md) — 公共契约、模块依赖、事务、质量门禁与后续任务
- [剧本工作区](docs/development/script-workspace.md) — 手动写作、四格式导入、版本恢复、AI润色/续写与模块2扩展验证
- [模块四工作区](docs/development/directing-storyboard-workspace.md) — 导演方案、分镜编辑与历史、来源保护及第二轮审核；[真实验收](docs/testing/module4-workspace-2026-11-05.md)
- [docs/manual/README.md](docs/manual/README.md) — 操作手册 (operator manual: start, run, review, switch models, troubleshoot)
- [docs/architecture/overview.md](docs/architecture/overview.md) — layers, request/task flow, workflow engine
- [多模块化改动说明](docs/architecture/modular-monolith-refactoring-proposal.md) — 目标模块边界、依赖、迁移与验收
- [重构进度](docs/architecture/refactoring-progress.md) — 首批逻辑模块化的实际落点、兼容约束与后续阶段
- [代码模块导航](backend/app/modules/README.md) — 从各业务公开入口阅读新结构
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
- `tasks.inline: false` 当前使用进程内线程池，不是独立外部 worker。可靠领取、
  重启对账与外部调用恢复需独立验证；项目默认保持单实例。
- The console is intentionally vanilla JS: it exercises the API without a build step.
- `install.exe` / `uninstall.exe` are unsigned, so SmartScreen warns on first run; installing
  needs network access to PyPI (and to python.org when the machine has no Python 3.11+).

## License

Proprietary sample code. Replace this section before any redistribution.
