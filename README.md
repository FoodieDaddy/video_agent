# AI Film Studio

AI Film Studio 是配置驱动、包含人工审核关卡的影视生产平台。现有主链路为：

`小说 → 章节 → 剧本 → 人物/场景 → 审核 → 导演 → 分镜 → 审核 → 镜头视频 → 审核 → 配音/字幕 → 剪辑 → 评估 → 终审 → 导出`

仓库采用 **uv workspace**：一个 `studio-api` 应用包与 12 个业务/技术包共同组成一个应用实例，使用同一份 `uv.lock`。开发、测试和启动通过安装后的 `studio_*` 包导入。旧 `app.*` 路径保留兼容；`backend/app` 是指向 `apps/studio_api/src/app` 的兼容符号链接，正式实现已在 `apps/` 和 `packages/` 中。

每个 Agent 从 YAML 读取模型、Provider、提示词和结构化输出配置。当前保留任务书的 13 类角色、17 个执行 ID；生产链路由 YAML 工作流引擎协调。目录、角色注册或 mock 通过均不能证明真实模型生成质量。

## 安装与单实例启动

需要 Python 3.11+、uv，以及可用的 FFmpeg/ffprobe。首次安装或锁文件变化后，在仓库根目录执行：

```bash
uv sync --frozen --extra dev
ffmpeg -version
ffprobe -version
```

启动前确认项目没有正在运行的实例。当前标准入口无需 `--app-dir` 或设置 `PYTHONPATH`：

```bash
uv run --frozen --extra dev uvicorn studio_api.main:app --host 127.0.0.1 --port 8010 --workers 1
```

浏览器打开 [控制台](http://127.0.0.1:8010/)，API 文档为 `/docs`，健康检查为 `/health`。桌面启动器使用 `uv run --frozen --extra dev python -m studio_api.desktop --port 8010`；同样需要先确认没有已有实例。

旧入口 `app.main:app` 和 `python -m app.desktop` 继续可用，供现存启动脚本迁移。新开发使用 canonical 包入口。项目默认只运行一个应用实例和一个 Uvicorn worker。

## 模型与本地配置

复制 `.env.example` 为根目录 `.env`，在其中配置 `FAST_GATEWAY_BASE_URL`、`FAST_GATEWAY_MODEL`、`FAST_GATEWAY_API_KEY`。这些变量用于默认文字 Provider `fast_gateway`；`.env` 属于本地私有文件，不提交。已有进程环境变量优先；修改 `.env` 后重新启动应用或重新执行检查脚本。

图像、视觉、视频与语音使用各自 Provider 配置；文字接口可用不代表媒体服务已就绪。详细配置见[模型配置说明](docs/model_configs/README.md)。默认真实检查可能产生模型费用；离线质量门禁强制 mock。

前端默认连接真实后端。`/?mode=demo` 才进入标记清楚的内存演示模式，演示修改不写真实项目。真实生成需要明确提交，审核默认只保存决定。旧控制台保留于 `/legacy/index.html`，详见[前端说明](web/README.md)。

## 检查与验收

代码质量、架构和类型门禁共用同一入口，使用已安装的 workspace 成员，不注入 `backend` 到 Python 搜索路径：

```bash
uv run --frozen --extra dev python scripts/checks/quality_gate.py
uv run --frozen --extra dev python scripts/checks/quality_gate.py --scope tests
uv run --frozen --extra dev python scripts/checks/quality_gate.py --scope smoke
```

门禁使用 mock、临时 SQLite 和临时存储；不会启动独立网页服务。mock Provider 会生成真实文件，完整媒体链路仍依赖 FFmpeg；其结果只验证机制与文件链路。

跨模块检查脚本可以独立运行，通常不需要启动网页服务：

```bash
uv run --frozen --extra dev python scripts/checks/module1_config_llm.py --offline
uv run --frozen --extra dev python scripts/checks/module2_script_agent.py --offline
uv run --frozen --extra dev python scripts/checks/module3_characters_scenes.py --offline
uv run --frozen --extra dev python scripts/checks/module4_directing_storyboard.py --offline
```

省略 `--offline` 会按脚本约定使用正式配置和根 `.env`。模块 3 上游剧本仍使用 mock 夹具，不能把该检查描述为从小说到影片的真实模型全链路验收。最新验证范围与待验项见[重构进度](docs/architecture/refactoring-progress.md)和[测试说明](docs/testing/README.md)。

## 目录与阅读顺序

```text
apps/studio_api/                 应用成员清单与 src 布局
  src/studio_api/                FastAPI、HTTP 适配、bootstrap、桌面入口与资源定位
  src/app/                       旧导入兼容入口
packages/studio_*/               12 个成员，各有 pyproject.toml
  src/studio_*/                  public、contracts、用例、领域、仓储、ORM、Agent、Schema
backend/app -> ../apps/studio_api/src/app
backend/tests/                   行为、契约、架构与安装兼容回归
config/                          YAML、提示词、JSON Schema，正式资源来源
web/                             HTML/CSS/JS 控制台，正式资源来源
samples/                         示例小说，正式资源来源
scripts/                         门禁、模块检查、资源同步、Schema 导出与安装器构建
installer/                       Windows、macOS、Linux 安装与卸载入口及共享安装引擎
deployment/                    Docker 与 Nginx 参考配置
```

从对应 `packages/studio_<业务>/src/studio_<业务>/public.py` 和同目录 README 开始阅读，随后查看 application、domain、infrastructure。跨业务模块通过 public/contracts 协作；技术公开接口、依赖 DAG 和成员直接依赖声明由架构测试检查。HTTP 层已通过公开用例/查询访问数据，不再直接执行 SQL 或导入内部 ORM；外层仍负责 Session 事务，部分显式 legacy 公共接口继续返回 ORM。完整事务解耦和旧入口删除未完成。

## 资源、wheel 与分平台部署

`config/`、`web/`、`samples/` 是资源的编辑来源。构建 wheel 前同步到 `studio-api` 包资源目录：

```bash
uv run --frozen --extra dev python scripts/sync_studio_resources.py
uv build --all-packages --wheel
```

同步脚本只复制这三个资源目录，不包含 `.env`、数据库、生成媒体或虚拟环境。应用优先使用显式 `STUDIO_RESOURCE_ROOT`，源码运行可定位仓库资源，独立 wheel 使用随包资源；安装后自定义资源可以通过 `STUDIO_RESOURCE_ROOT` 统一指定。

Dockerfile 已改为复制完整 workspace，并使用共享锁文件冻结安装：

```bash
docker compose up --build
```

Linux arm64 镜像已实际构建成功，并在禁用外部网络的临时容器中通过 TestClient 完成四关 mock、真实 FFmpeg 渲染与导出；未绑定主机端口，未验证对外 TCP/反向代理。证据见 [Docker 验收](docs/testing/docker-workspace-2026-11-06.md)。

### Windows、macOS、Linux 发布包

发布目标按平台分别出包，当前本机实际安装与运行验收使用 macOS。所有平台仍采用同一份应用源码、13 成员 workspace 和 `uv.lock`；平台入口、前置条件及实际验证范围分别记录。

| 目标平台 | 发布形式与入口 | 前置条件 |
| --- | --- | --- |
| macOS | `*-macos-source-bootstrap.tar.gz`；`Install.command` 或 `install.sh` | 本机 Python ≥3.11、FFmpeg/ffprobe；安装时需要网络获取固定 uv 和锁定依赖 |
| Linux | `*-linux-source-bootstrap.tar.gz`；`install.sh` | 本机 Python ≥3.11、FFmpeg/ffprobe；安装时需要网络 |
| Windows 源码引导包 | `*-windows-source-bootstrap.zip`；`install.cmd` | 本机 Python ≥3.11、FFmpeg/ffprobe；此包不包含原生 EXE |
| Windows 原生引导包 | `*-windows-native-bootstrap.zip`；`install.exe` / `uninstall.exe` | 在 Windows 构建；EXE 可引导安装 Python，发布器验证 EXE 来源、架构与载荷哈希 |

macOS/Linux 发布包是源码引导归档，应用和依赖在目标机器上安装，不是包含 Python/FFmpeg 的通用二进制应用。分别构建三个源码引导包：

```bash
uv run --frozen --extra dev python scripts/build_releases.py --platform all --source-only
```

默认从已提交的 Git HEAD 提取源码，工作区中尚未提交的代码、配置和前端改动不会进入发布。归档输出到 `dist/releases/`，每包的 `release.json` 记录平台、类型、来源提交、锁文件及内容哈希。Windows 原生构建命令和 Mac/Linux 安装生命周期见[操作手册](docs/manual/README.md#29-macoslinux-用户级安装与卸载)。完整 EXE 需要当前构建生成的 `windows-installers.json`，不能把旧版本 EXE 混入新源码包。

本轮实际验证以 macOS 本机为主，不再等待远程 Windows 机器。Windows 原生 EXE 构建、快捷方式、注册表、安装和卸载的结果仍由对应 Windows CI 或原生环境单独报告；源码归档构建和跨平台脚本测试不代替原生执行。macOS 本机完整安装、启动、停止及卸载的最终记录见[重构进度](docs/architecture/refactoring-progress.md)。

## 运行边界

- TaskRunner 使用进程内线程/线程池；单实例仍是默认运行约定，没有独立可靠队列。
- 新工作流记录保存定义快照，恢复优先使用该快照；历史无快照记录读取当前定义。Agent、Prompt、Provider 和环境尚未形成完整执行快照。
- 数据库和对象存储没有跨资源事务；外部模型调用、文件写入和费用不能随数据库回滚自动撤销。
- 审核批准范围按各阶段既有规则处理，分镜采用来源与镜头快照；其他关卡不能据此声称全部冻结。
- 生产身份、可靠队列、崩溃恢复、并发与取消策略仍需各自部署和验收。

## 文档

- [重构方案](docs/architecture/modular-monolith-refactoring-proposal.md)、[当前进度与证据](docs/architecture/refactoring-progress.md)、[架构阅读图](docs/architecture/overview.md)
- [贡献指南](CONTRIBUTING.md)、[工程规范](docs/development/engineering-standards.md)、[测试说明](docs/testing/README.md)
- [操作手册](docs/manual/README.md)、[API 说明](docs/api/README.md)、[数据结构](docs/database/schema.md)
- [Agent 说明](docs/agents/README.md)、[架构决策记录](docs/decisions/README.md)

## License

Proprietary sample code. 发布或再分发前请明确适用许可。
