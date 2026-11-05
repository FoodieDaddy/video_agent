# 多模块化重构进度

- 日期：2026 年 11 月 5 日
- 当前分支：`codex/normalize-project-structure`
- 状态：逻辑模块化、工作流定义快照、39 个 ORM 映射归属、production/media 拆分和 story→workflow/reviews 基线 DTO 已落地；其余仓储/DTO 边界与 workspace 仍在后续阶段

本批按[改动说明](modular-monolith-refactoring-proposal.md)推进业务分包，保留原有运行方式和业务行为。当前仍是 `backend/app` 下的模块化单体，目标中的 `apps`、`packages`、独立成员 `pyproject.toml` 和 workspace 尚未建立。

## 已实施内容

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

本次提取出两个额外的明确边界：`assets` 管理业务资产登记，避免 story 与 production 相互依赖；`configuration` 管理配置版本账本，区别于底层 YAML/环境解析。完整目录导航见[模块说明](../../backend/app/modules/README.md)。

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

## 后续阶段

1. 继续抽取剧本、人物、场景和制作中的领域规则，建立更窄的仓储和 DTO 边界；story 的基线指纹规则已进入 domain，workflow/reviews 已消费基线 DTO，其他应用接口仍保留原 Session/ORM 契约。
2. 业务 ORM 映射已归入所属模块并保留共享 Base；继续迁移仓储、DTO 与跨模块查询，再逐步收拢 `app.models` 聚合注册。
3. production/media 已按人物资产、镜头视频、配音字幕、剪辑渲染和质量首轮拆分；后续保持职责边界并避免重新聚合成大文件。
4. 模块边界稳定后再迁入 apps/packages workspace，同时处理安装包、配置、样例和前端资源定位。
5. 旧入口的删除另作兼容性变更，不与本次迁移混在一起。

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
