# 多模块化重构进度

- 日期：2026 年 11 月 5 日
- 当前分支：`codex/normalize-project-structure`
- 状态：13 成员 uv workspace、业务归属、主要 DTO/ID/端口边界已落地；本地全量门禁与干净安装验证通过；Docker/Windows 原生交付及完整 legacy 接口收敛仍有待验项

当前结构由 `apps/studio_api` 和 12 个 `packages/studio_*` 包组成，共 13 个 uv workspace 成员；均采用 src 布局、独立 `pyproject.toml` 和共同 `uv.lock`。标准启动为 `studio_api.main:app`，通过安装后的包导入。`backend/app` 是指向 `apps/studio_api/src/app` 的兼容符号链接。历史第 1～9 批保留各批实施时的事实与命令，不作为当前目录或完成状态。


## 当前验证与待验项（2026-11-05）

| 项目 | 实际证据 |
| --- | --- |
| 完整门禁 | `quality_gate.py --scope all --scope tests --scope smoke` 5/5 通过 |
| 后端回归 | 379 项通过；类型检查当前覆盖 6 个文件，严格检查通过 |
| 独立模块离线检查 | 模块 1：6 通过、1 个网络探针跳过；模块 2：8/8；模块 3：10/10；模块 4：13/13 |
| 多包构建 | 13 个 wheel 与 13 个 sdist 构建成功 |
| 干净安装 | 非 editable 安装后不依赖源码搜索路径；TestClient 四关 mock 流程、控制台、随包资源与 70,043 字节导出均通过，临时目录已清理 |
| HTTP/数据库结构 | 与 `520282f` 对照，71 个 OpenAPI 路径及 20 个 Schema 一致；39 张表结构一致，默认值 callable 的 Python 模块出处因迁移而变化 |

以上是本地、隔离数据库和 mock 的机制验收，没有新增真实模型质量证据。TestClient 检查不启动第二个独立网页服务。

尚需分别完成或保留的事项：Linux arm64 Docker 镜像构建及容器内隔离四关/FFmpeg 导出已通过，测试容器与本次启动的 Docker Desktop 已清理；对外 TCP/反向代理未验证；两个现有 Windows 访问上下文的 SSH 均拒绝连接，原生 EXE 构建、安装、启动与卸载未执行。HTTP 已无直接 SQL/内部 ORM 导入，外层 Session 事务与部分显式 legacy 公共 ORM 返回继续保留，完整仓储/DTO 解耦未覆盖全部存量接口；旧导入层继续保留，删除须单独完成消费者审计和发布兼容评审。部署鉴权、可靠队列、并发、取消与外部调用崩溃恢复继续独立实施。

## 历史阶段：已实施内容

| 内容 | 当前结果 |
| --- | --- |
| 集中业务流水线拆分 | 原 pipeline 的 31 个函数分别迁入 story、characters、scenes、production 的用例与查询文件；旧入口转发 |
| 非流水线服务迁移 | 项目、文档、资产、媒体、质量、审核、工作流、节点和配置管理进入所属模块 |
| Agent 与 Provider | 业务 Agent 按角色归属模块，公共基类和 Provider 进入 ai_runtime；保留 13 类角色、17 个执行 ID |
| 依赖组装 | bootstrap 统一提供默认 Agent 注册，正常启动显式装配，旧调用方保留惰性兼容 |
| 公共技术基础 | 配置、资源根、Base、Session、存储、FFmpeg、文本工具和 Runtime 进入 platform |
| 任务职责拆分 | 任务记录、技术运行器、业务任务分派分别拥有实现，技术运行器不反向依赖业务模块 |
| 纯领域规则 | 审核决定的既有状态判断抽入 reviews/domain，保持原异常、检查顺序和写入时机 |
| 消费者接线 | API、序列化、工作流和模块检查使用新公开入口；保留旧导入兼容 |
| 架构约束 | 增加模块同一性、单份元数据、角色注册、依赖 DAG、公开接口和领域依赖检查 |

本次提取出两个额外的明确边界：`assets` 管理业务资产登记，避免 story 与 production 相互依赖；`configuration` 管理配置版本账本，区别于底层 YAML/环境解析。当前目录导航见[架构阅读说明](overview.md)；本节所述路径为当时的逻辑模块布局。

## 保持的契约

- API 路由、请求响应、错误码、任务 ID 与状态字段。
- 数据库表与列、主键、版本以及现有 canonical 和审核语义。
- 调用方 Session、提交和回滚的责任，不新增隐式事务。
- YAML、提示词、Schema 名称、Agent ID 和环境变量约定。
- 模块 1～3 的 CLI、报告、沙箱、来源判断与禁止下游调用保护。
- 单实例运行约定；没有增加新的后台服务或 Agent 服务。

旧入口保持函数或模块对象身份，配置缓存、engine、Runtime 和 Base/metadata 均不复制。API 与模型 Schema 继续按原契约验证。

## 验收记录

验证报告与本批工作区关联，真实模型验收与本地回归分开保存。

- 全量后端回归：102 项通过，其中包括新增 16 项架构约束和 8 项审核规则/错误映射检查。
- API 对照：当前完整 OpenAPI 定义与原提交基线一致，覆盖 65 个路径。
- 数据对照：39 张 ORM 表的列、类型、可空性、主键和外键定义一致。
- Ruff 与代码差异空白检查通过。
- wheel 构建通过，包含 117 个新模块 Python 文件，未打包本地 `.env`。这只验证当前单包构建，不代表 workspace、Docker 或 Windows 安装运行已经验收。
- 启动装配检查：健康检查、控制台均返回 200，17 个 Agent 已注册，默认模型与凭据仍从根 `.env` 自动读取。
- 真实模块检查：模块 1 为 7/7，模块 2 为 8/8，模块 3 为 10/10，均使用当前正式 Provider 和 `.env`，没有通过命令行覆盖模型或密钥。
- 本次模块 2 样例得到 3 个章节摘要、9 个事件、7 条对白；模块 3 得到 4 个人物、3 个场景，9 次目标模型调用。模块 3 上游仍为 mock 夹具，边界与修复机制使用独立 mock/stub。

OpenAPI 与表结构对照说明兼容的外部结构保持，不代替行为测试。真实调用只验证样例链路，人物、场景等产物数量不作为准确率。

## 第二批：工程规范与公共契约

本批落实注释和工程质量基础，不改变现有业务状态、审核范围、模型重试或数据库结构。

- 新增[工程与注释规范](../development/engineering-standards.md)、[贡献指南](../../CONTRIBUTING.md)和 PR 评审模板，统一中文说明、公共契约、事务责任、资源清理与完成标准。
- 六个业务模块的 13 个 application 文件补充 94 个函数说明，其中 29 个复杂入口说明输入、返回、异常与事务/重试边界；另补 AI Runtime、Provider、Workflow、资产、配置和会话/运行器契约。
- 纠正配置快照、节点恢复、人物档案版本和费用/尝试次数等过强描述；明确媒体部分成功、当前审核版本、文件回滚和内存配置回滚的既有限制。
- 增加 `scripts/checks/quality_gate.py` 供本地与 CI 共用，默认检查 lint、格式、渐进严格类型和模块架构；全量测试与 smoke 使用显式 scope。所有执行强制 mock 并隔离数据库、存储及临时目录，不启动独立网页服务。
- 严格类型检查当前覆盖 contracts（含 public）与 reviews/domain，共 5 个文件；序列化返回值补两处类型 cast，不改变数据处理。其他模块尚未完成严格类型治理。
- Python CI 使用 `uv.lock` 的 frozen 安装，对齐 main/master/PR；Docker 探测增加失败清理。GitHub 仓库侧配置已更新，不代表 Gitee 的 runner 和合并条件已经启用。
- 统一格式化 backend 与 scripts/checks。执行结构对照覆盖本轮改动的 60 个存量 Python 文件：剔除文档字符串及两处类型 cast 后，与本轮开始前的工作区结构一致。

完整验证命令与模式说明见[测试说明](../testing/README.md)。现有工作区的前序重构和环境配置保持，未自动提交 Git。

本批最终本地验收（2026-11-04，Python 3.12，锁定开发环境）：

| 检查 | 结果 |
| --- | --- |
| 组合门禁 `--scope all --scope tests --scope smoke` | 5/5，通过，33.4 秒；全量测试已包含架构检查，因此同轮不重复执行架构 scope |
| 全量后端测试 | 117 项通过，其中新增 15 项门禁编排回归；1 条第三方 TestClient 弃用提醒 |
| Ruff / 格式 / mypy | lint 通过，235 个 Python 文件格式合规，选定 5 个文件严格类型通过 |
| Schema 导出 | 6 份，已提交 Schema 无差异 |
| 模块 1～3 离线检查 | 模块 1 为 6 通过、1 项真实探针跳过；模块 2 为 8/8；模块 3 为 10/10 |
| 完整 mock smoke | 四关审核、6/6 镜头视频、9 条音轨、30 秒导出完成 |
| 隔离与清理 | 正式 data 文件大小/修改时间未变，门禁与模块 2/3 沙箱已删除，未启动独立网页服务 |

以上均为本地离线验收，没有新增真实模型调用，也没有执行远程 GitHub/Gitee CI、Docker 或 Windows 安装器构建。

本批不替代数据库迁移、事务补偿、幂等恢复、审核快照、生产身份、Docker/Windows 完整依赖锁定或单实例锁的独立实施；这些任务及验收证据已列入工程规范。

## 后续收尾与交付验证

1. HTTP 已完成 SQL/内部持久化导入收束；继续按调用方需要收窄外层 Session 与显式 legacy 公共 ORM 返回，不通过宽泛实体导出绕过模块边界。
2. Docker 镜像构建和容器内隔离流程已通过；对外 TCP、反向代理与部署健康探针由部署验收继续验证。
3. 在原生 Windows 验证安装 EXE、锁文件依赖安装、启动/停止和卸载。
4. 审计外部旧路径消费者后，将删除兼容入口作为独立变更；本批不删除。
5. 真实模型、媒体质量和部署运行策略按各自证据验收，不能复用 mock 结果代替。


场景字段透传、审核版本快照、任务并发和取消等已知行为问题仍需独立处理。本批目录与职责迁移不宣称已经修复这些问题，也没有接入 LangGraph、DSH 或 Pi。


## 第三批：工作流定义快照与恢复一致性

- `WorkflowEngine.start()` 在创建 `WorkflowRun` 时，将实际执行的 `WorkflowConfig`（JSON 形式）写入 `workflow_runs.state.workflow_definition`，同时保留原有 `workflow_config_version`。
- `WorkflowEngine.resume()` 优先从该快照重建定义并继续执行，避免 YAML 在运行期间发生变更后，恢复任务悄悄切换节点顺序或 handler。
- 为兼容历史数据，未包含 `workflow_definition` 的旧运行记录仍按原行为读取当前配置；不会伪造其历史定义。
- 新增回归测试：运行在审核关卡暂停后，恢复过程不再查询可变的当前配置，并验证快照包含定义 ID 与节点。
- 该改进只冻结工作流定义，不冻结 Prompt、Agent、Provider、环境变量或外部模型服务版本；这些配置仍通过现有 `config_versions` 审计，尚未形成完整的可复现执行包。
- 本批不改变数据库表结构，复用已有 JSON `state` 字段；不要求 Alembic 迁移。

本地验证：`backend/tests/test_workflow_service.py` 4 项通过。全量后端测试在当前执行环境超过可用执行时限，未完成；不得将其标记为通过。

## 第四批：story 领域规则与 ORM 归属第一切片

- 将剧本基线指纹规则抽入 `story/domain/script_baseline.py`，领域输入为不可变字节 DTO；指纹仍使用既有 canonical JSON 格式，保持已保存工作流基线可比较。
- `story/application/queries.py` 负责把 Script ORM 行投影到领域输入，并保留原 `story.public` 函数签名。
- 将 `SourceDocument`、`StoryChapter`、`Script`、`StoryEvent` 映射移入 `story/infrastructure/persistence/models.py`，使用唯一的 platform `Base` 和 metadata。
- `app.models.story` 保留为模块别名兼容入口；`app.models` 聚合仍注册全部业务表。story 内部改为导入模块内映射，其他旧调用方继续通过兼容路径读取同一类对象。
- 本批未改变表名、列、外键或事务责任；完整仓储和跨模块 DTO 边界尚未完成。

本地验证：story 领域和基线回归 32 项通过，模块架构、模块 3/4 与 story 回归 105 项通过；后续全量门禁结果见第五批。

## 第五批：全量业务 ORM 映射归属

- 39 个 ORM 类的唯一实现已迁入 `projects`、`story`、`characters`、`scenes`、`production`、`reviews`、`workflow`、`assets`、`configuration`、`ai_runtime` 和 `platform` 的持久化目录。
- `app.models` 及旧的 `app.models.character/scene/production/story` 导入继续导出或别名到同一类；`app.models` 仍集中导入所有映射，使唯一 `Base.metadata` 可完整注册。
- 同模块 application 改为导入所属映射；跨模块现存调用仍有 ORM 直接依赖，后续通过 repositories/DTO 分批收窄。
- 对比重构前 `HEAD` 与当前 metadata：39 张表的列名、类型、可空性、主键、外键、约束和索引完全相同；本批只改变类定义归属，没有数据库结构或数据迁移。

本地验证：`scripts/checks/quality_gate.py --scope lint --scope format --scope types --scope architecture --scope tests` 全部通过；后端 309 项通过，含模块架构约束；有一条第三方 Starlette `TestClient` 弃用提醒。测试使用隔离数据库和 mock；没有启动网页服务或调用真实模型。

## 第六批：production 媒体用例拆分

- 将原 1,178 行 `production/application/media.py` 中的实现按人物资产、镜头视频、配音字幕、剪辑/渲染/导出迁入 `character_assets.py`、`shot_video.py`、`audio.py`、`editing.py`；共享尺寸与资产读取放入 `media_support.py`。
- `production.public` 直接导出新实现；旧 `application.media` 保留函数对象重新导出，供现存调用方迁移期间使用。质量用例改为直接依赖同模块的 `editing` 用例。
- 保持函数签名、返回值、事务提交责任、模型调用和 FFmpeg 行为不变；没有改变状态机或数据库结构。

本地验证：`scripts/checks/quality_gate.py --scope lint --scope format --scope types --scope architecture --scope tests` 全部通过；后端 310 项通过，含旧 facade 与新实现函数对象一致性检查；有一条第三方 Starlette `TestClient` 弃用提醒。测试使用隔离数据库和 mock，没有启动网页服务或调用真实模型。

## 第七批：剧本基线跨模块 DTO

- 在 story contracts 增加不可变 `ScriptBaselineReference`，只含项目/剧本 ID、版本号与已校验指纹，不含 ORM 或 JSON 正文。
- `assert_script_baseline_reference()` 与旧 `assert_script_baseline()` 共用同一读取、刷新和冲突判断；旧接口仍返回 Script ORM，供尚未迁移的调用方使用。
- workflow 恢复与 reviews 审批只需要验证基线，不再接收校验函数返回的 Script 实体；production 仍在部分用例中使用旧接口，后续继续迁移。
- 保持异常类型、错误文本、状态检查顺序和事务责任；只增加返回 DTO 的公开入口。

本地验证：`scripts/checks/quality_gate.py --scope lint --scope format --scope types --scope architecture --scope tests` 全部通过；后端 311 项通过，含旧 baseline ORM 接口、DTO 返回、工作流恢复和审核路径回归；有一条第三方 Starlette `TestClient` 弃用提醒。测试使用隔离数据库和 mock，没有启动网页服务或调用真实模型。

## 第八批：跨模块资产引用 DTO

- `assets/contracts.py` 新增不可变 `AssetReference`，包含 asset ID、project ID、类型、存储键、MIME 类型和字节数，不暴露 SQLAlchemy Asset 行。
- 新增 `save_asset_reference()`，内部复用现有资产写入和 flush 流程；story 文档、人物图片、镜头视频、配音与字幕生成已迁到该返回契约。
- `save_asset()` 仍保留原 ORM 返回，成片渲染和导出等尚未迁移的调用方暂沿用旧接口；文件写入、数据库事务与补偿语义不变。

本地验证：`scripts/checks/quality_gate.py --scope lint --scope format --scope types --scope architecture --scope tests` 全部通过；后端 312 项通过，含 AssetReference 持久化与消费者回归；有一条第三方 Starlette `TestClient` 弃用提醒。测试使用隔离数据库和 mock，没有启动网页服务或调用真实模型。

## 第九批：数据所有权、应用装配与 Schema 归属

- 人物形象生成与版本写入归 characters；production 通过人物、场景和剧本值快照读取输入。资产读取归 assets 查询/仓储，成片旧 ORM 返回保留显式兼容适配。
- 审核只协调，批准标记由人物、场景、制作模块分别写入；审核读取工作流通过组合根注入的只读端口，避免 reviews→workflow 反向依赖。分镜校验使用 ID DTO，原 ORM tuple 校验只用于兼容入口。
- 项目状态与费用写入归 projects；任务分派读取 ProjectContext 快照，并以实体 ID 调用所属模块。任务存储只依赖 ProjectIdentity 协议。
- 业务 Schema 按模块归属；14 个输出 Schema 和 7 个导出文件由 bootstrap 装配。ORM 聚合注册也归 bootstrap，旧 models/schemas 继续导出同一类对象。
- platform 与 ai_runtime 不再反向导入 bootstrap；正式应用、兼容入口及离线检查显式装配。

本批合并检查：lint、格式、选定类型检查通过；全量后端 336 项通过、1 项测试夹具仍直接修改旧项目实体而失败。该夹具已改用项目费用公开用例，所在文件 17 项回归通过。后续 workspace 全量门禁将覆盖本批最终状态。未调用真实模型或启动额外服务。


## 第十批：实际 uv workspace 与交付路径

- 将应用实现迁至 `apps/studio_api/src/studio_api`，12 个业务/技术实现迁至 `packages/studio_*/src/studio_*`；每个成员有独立依赖声明，根项目共同冻结到 `uv.lock`。
- `apps/studio_api/src/app` 保留旧路径转发，`backend/app` 为该兼容目录的符号链接。配置缓存、ORM 元数据、Agent/Schema 注册表和 Provider 观察点保持同一对象，应用组合根负责完整装配。
- 标准启动、模块检查和门禁通过已安装包导入，测试不再依赖 backend 的 PYTHONPATH 注入。架构扫描 canonical 源码，覆盖依赖 DAG、公开入口、领域规则和直接成员依赖清单。
- 正式资源继续编辑根 config/web/samples，构建前由 `scripts/sync_studio_resources.py` 同步到应用随包资源；wheel 的资源定位支持独立安装。
- Dockerfile 与 Windows payload/安装路径已调整为完整 workspace 和冻结依赖；交付实现与运行验证分开记录，外部平台未执行项见顶部。

本批最终证据为本页“当前验证与待验项”表；不使用历史逻辑分包的通过报告替代新目录验证。仓库和模块 README 已切换到 canonical 阅读路径，历史批次说明保留。

## 第十一批：HTTP、任务和检查入口的公开边界（提交 `1e6b5bc`）

- 所有 HTTP 适配器通过所属模块公开用例/查询读取与更新实体；接口层保留授权、入队和原事务提交责任，不再直接执行 ORM 查询或导入持久化模型。
- 项目创建/更新、剧本详情及持久化事件投影归所属模块；任务 SSE 使用 TaskReference，审核恢复条件使用 WorkflowRunReference，缺失记录和授权错误顺序保留。
- 新增 HTTP 架构门禁，覆盖 API 源码中的持久化导入和直接 Session 读写；旧 entity 查询/返回仅在明确兼容入口保留。
- 冒烟脚本使用各模块公开接口；模块检查的诊断实体来自应用组合根，标准脚本不再使用旧业务门面或 backend 搜索路径注入。

最终本地门禁 `--scope all --scope tests --scope smoke` 为 5/5；后端 379 项通过，严格类型覆盖 6 文件。mock 完整流程通过四关审核、6 个镜头、9 条音轨和 30 秒成片导出。完整 OpenAPI 与 workspace 提交 `0a2060d` 逐项一致：71 路径、20 Schema，差异 0；报告见 [HTTP 对照](../testing/api-boundaries-2026-11-05.md)。本批没有改变数据库映射或启动第二个独立网页服务。


## 第十二批：交付机制实际执行

- 13 个成员 wheel 与 sdist 构建通过；应用 sdist 在独立位置再次构建 wheel，提示词和前端资源保持完整。归档未包含本地 `.env` 或数据库。
- 安装器共享机制在 macOS 临时标准 venv 实际执行固定 uv 引导与冻结、非 editable 安装，安装后移走源码载荷，13 个成员和包内资源仍可读取；临时目录及引导均清理。见 [安装机制报告](../testing/installer-workspace-2026-11-05.md)。
- Linux arm64 Docker 镜像完整构建成功；禁用外部网络、不挂载正式数据、不绑定主机端口，在临时容器中运行完整 TestClient 四关与 FFmpeg 导出，成片为 70,049 字节。见 [容器报告](../testing/docker-workspace-2026-11-06.md)。
- 本次临时容器已删除，诊断镜像标签已清理，Docker Desktop 已恢复关闭；正式项目原单实例未重启。
- Windows 两个现有访问上下文均无法建立 SSH 连接。Windows EXE、快捷方式、原生安装/启动/卸载仍待可用环境；已请求连接信息，不能标记整体交付验收全部完成。
