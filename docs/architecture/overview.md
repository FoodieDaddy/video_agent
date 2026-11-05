# 当前架构与阅读入口

更新日期：2026 年 11 月 5 日。当前源码已形成 `apps/studio_api` 与 12 个 `packages/studio_*` 成员的 uv workspace，共 13 个可安装成员，共享 `uv.lock` 和开发环境。各成员共同运行在一个受管应用实例中。

旧 `backend/app` 是指向 `apps/studio_api/src/app` 的兼容符号链接；旧 `app.*`、`app.modules.*`、models/schemas 路径转发到 canonical 包，重要模块和类保持对象身份。新增实现进入 `studio_*` 包，不反向借用旧目录。迁移事实与验证证据见[重构进度](refactoring-progress.md)，目标和保留边界见[重构方案](modular-monolith-refactoring-proposal.md)。

## 1 应用、业务与技术能力

```text
浏览器 → studio_api.api → studio_<业务>.public / contracts
                                  │
                     application 用例 / 查询 / 命令
                         │                       │
                       domain            infrastructure
                                         仓储 / ORM / Agent

studio_workflow → 业务模块公开用例
studio_reviews → 领域状态规则 + 各数据所有者的批准操作
studio_ai_runtime → 通用执行 / Provider / 审计
studio_platform → 配置 / Base / Session / 存储 / FFmpeg / 任务线程
studio_api.bootstrap → Agent / Schema / ORM 聚合及依赖装配
```

`studio_api.main` 创建 FastAPI、注册中间件/异常处理和路由；`bootstrap/lifespan.py` 管理启动与关闭。`bootstrap/composition.py` 汇总 Agent、输出 Schema、模型和审核读取端口装配。platform 和 ai_runtime 不反向导入应用组合根或业务实现。

应用为 13 类角色装配 17 个 Agent ID，Schema 目录为 14 个输出名称装配类型，并维护 7 个 JSON Schema 导出文件。通用注册表只保存协议、类型和执行目录；业务 Agent 与 Schema 均归所属包。

## 2 按业务阅读代码

每个成员的源码在 `packages/studio_<名称>/src/studio_<名称>/`。先看 `public.py`、`contracts.py` 与模块 README，再按具体用例进入 application、domain、infrastructure。

| 包 | 内容与数据所有权 |
| --- | --- |
| `studio_projects` | 项目、用户/成员、权限、状态和费用写入；ProjectContext 查询 |
| `studio_story` | 源文档、章节、剧本、故事事件、正文工作区和基线指纹 |
| `studio_characters` | 人物、档案、关系、图片、服装/状态、声线、人物批准写入 |
| `studio_scenes` | 场景、档案、参考资产、场景批准写入 |
| `studio_production` | 导演、分镜、镜头视频、音轨、剪辑、渲染、评估和制作批准写入 |
| `studio_reviews` | 审核记录、评论、决定与批准协调；工作流读取由注入端口提供 |
| `studio_workflow` | YAML 节点协调、人工关卡、暂停恢复、任务业务分派 |
| `studio_assets` | 资产登记、版本、引用 DTO 和字节存储访问协调 |
| `studio_configuration` | 配置版本账本、激活与回滚 |
| `studio_ai_runtime` | Agent 基类、Provider、执行和输出 Schema 注册机制 |
| `studio_platform` | 配置解析、数据库基础、技术任务表与线程、存储、媒体工具 |
| `studio_contracts` | 序列化协议和最小 ProjectIdentity 协议 |

ORM 类定义在各所有者 `infrastructure/persistence`，技术 Task/TaskEvent 位于 platform persistence。所有映射共享 `studio_platform.persistence.base.Base`，39 张表在应用 model catalog 中集中注册；旧 `app.models` 继续导出同一类。业务 Pydantic Schema 在所属包 `schemas/`，旧 `app.schemas` 继续别名到同一类型。

人物图片用例在 characters；production 保留旧人物图片转发接口。制作媒体按 `shot_video.py`、`audio.py`、`editing.py`、`quality.py` 分开，共享读取位于 `media_support.py`；旧 `application.media` 只重新导出。

## 3 公开边界与兼容期

跨业务模块只导入 public/contracts。制作模块使用人物/场景生成输入深副本、剧本 Snapshot、资产引用等 DTO；项目状态和费用由 projects 写入，任务分派通过 ProjectContext 和业务实体 ID 调用数据所有者。审核中的产物批准也由所属业务模块执行。

`ScriptSnapshot`、人物/场景 payload 是与 Session 脱离的深副本；冻结 dataclass 字段并不代表嵌套 JSON 不可修改，也不代表所有读取跨多条查询构成一致数据库快照。剧本校验入口显式刷新并核验指纹，不能用已有 DTO 冒充后续写入时的最新状态。

HTTP 层已经通过模块公开用例和查询访问数据，不再直接执行 SQL、导入内部持久化模型或访问私有 ORM 实现；Session 提交/回滚仍由既有外层管理。显式 legacy 公共接口保留部分 ORM 返回，仓储与 DTO 尚未覆盖每一个历史函数。兼容入口只转发，不复制规则；删除旧入口应单独评审消费者和发布兼容策略。

架构测试扫描真实 canonical 源码，检查业务/技术公开入口、DAG、纯 domain 依赖、旧路径反向依赖及成员直接包依赖声明；惰性 public 导出同样纳入依赖图。安装成员不会自动提供运行时安全隔离。

## 4 工作流、任务与审核

`config/workflows/*.yaml` 定义有序 handler/gate 节点。WorkflowRun 保存节点输出和 `next_index`，节点执行写 checkpoint。新运行同时保存 `state.workflow_definition`；恢复优先使用定义快照，历史无快照记录回退读取当前定义。

这仅冻结工作流定义。Agent、Provider、Prompt、环境变量和外部服务版本仍按现有配置解析；配置指纹是出处证据，并非可复现执行包。工作流仍是顺序引擎，Orchestrator 的计划输出不承担运行时动态调度。

TaskRunner 在进程内使用线程或线程池，处理函数在自己的 Session 中执行。取消主要在阶段/循环边界生效，不能保证中断已发出的模型请求或 FFmpeg。任务事件持久化到表并通过 SSE/polling 读取；这不等于已经完成多实例可靠领取和崩溃恢复。

四个人工关卡保留现有业务范围。分镜关绑定来源、版本和镜头内容指纹；第一关等其他范围按各自当前规则处理。审批决定默认不自动排队恢复，调用方需显式请求续跑；驳回不自动重新生成全部上游产物。

## 5 配置、资源与安装

配置来源保持根 `config/app.yaml`、环境 YAML 和环境变量覆盖规则；应用/检查脚本可读取根 `.env`，进程环境值优先。正式凭据不进入 wheel、安装 payload、报告或源码。

`studio_api.resource_root` 统一定位资源：显式 `STUDIO_RESOURCE_ROOT` 优先；源码使用仓库的 config/web/samples；wheel 使用随包资源。`scripts/sync_studio_resources.py` 从正式目录同步资源副本，构建前执行，不编辑副本。

```bash
uv sync --frozen --extra dev
uv run --frozen --extra dev python scripts/sync_studio_resources.py
uv build --all-packages --wheel
```

每个 workspace 成员声明自己的直接依赖；所有成员使用同一锁文件和依赖解。测试与脚本通过已安装包导入，无需把 backend 加到 `PYTHONPATH`。

## 6 事务与运行限制

多数应用用例只 flush，由外层决定提交或回滚；工作流在既有节点边界提交。数据库提交与模型请求、文件写入和远端费用不构成一个事务，部分媒体生成可返回失败明细；不能把函数正常返回等同于所有产物成功或已通过审核。

单实例、单 Uvicorn worker 仍是默认运行方式：

```bash
uv run --frozen --extra dev uvicorn studio_api.main:app --host 127.0.0.1 --port 8010 --workers 1
```

Docker 与 Windows 安装器已按完整 workspace 和锁文件调整。Linux arm64 镜像构建与容器内四关 mock/FFmpeg 导出已通过（禁外部网络、无主机端口绑定）；Windows 的两个访问上下文均拒绝 SSH 连接，原生 EXE 构建、安装、启动与卸载尚未执行。mock 媒体与离线检查证明的是机制，真实模型质量、生产鉴权和可靠多实例执行仍需独立验收。

当前 HTTP 边界批次已提交为 `1e6b5bc`；完整门禁 5/5 通过，后端 379 项通过。外部平台交付的当前进度与原始检查证据见[重构进度](refactoring-progress.md)。
