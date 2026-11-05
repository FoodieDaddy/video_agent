# AI Film Studio 多模块化改动说明

- 状态：核心结构已迁入 13 成员 uv workspace；业务归属、主要 DTO 和 production/media 拆分已落地；显式 legacy 接口及 Docker/Windows 交付验证仍有待验项
- 更新日期：2026 年 11 月 5 日（初稿为 11 月 4 日）
- 适用项目：video_agent

当前采用业务优先的模块化单体和同仓多包 uv workspace。`apps/studio_api` 与 12 个 `packages/studio_*` 成员共享锁文件和依赖解，每个包使用 src 布局并声明直接依赖。各成员共同组成一个应用，继续保持单实例启动约定。

当前目录和验收见[重构进度](refactoring-progress.md)与[架构说明](overview.md)。`backend/app` 现为指向应用包中旧 app 兼容目录的符号链接；主要实现位于 canonical `studio_*` 包。完整仓储/DTO 解耦仍有显式 legacy 返回适配，旧导入入口继续保留。

## 1 改动目标与适用范围

重构前代码以 `api`、`services`、`agents`、`schemas`、`models`、`providers` 等技术职责划分目录，`services/pipeline.py` 混合多项业务。本方案的实施已将业务用例、Agent、Schema 和 ORM 归入对应包；原路径保留薄兼容入口。

本方案将业务 module 作为一级边界，使开发者能够在对应模块内找到公开入口、用例、规则、数据访问和测试。相较此前讨论的全局四层目录，目录组织重心改为业务优先，职责分层原则继续保留。

改动目标：

- 将业务实现集中到明确的模块，减少跨目录查找和隐式依赖。
- 通过公开接口与数据契约协作，使内部实现可以独立调整。
- 为每个模块建立可单独运行的测试和职责说明。
- 保持现有业务行为，以分批迁移降低同时改动调用方的风险。

本轮结构方案不包含数据库拆分、微服务部署、业务规则修复或 Agent 执行框架替换。场景字段透传、审核版本绑定、并发、取消与恢复等已发现的问题，应单独记录和验收，避免混入纯结构迁移。

模块公开接口、内部实现与外部依赖的划分，参考 [Spring Modulith 的应用模块定义](https://docs.spring.io/spring-modulith/reference/fundamentals.html)。这里借鉴其模块组织方式，不引入 Java 技术栈。

## 2 模块与智能体的对应关系

本项目存在三个不同维度：

| 维度 | 含义 | 示例 |
| --- | --- | --- |
| 业务模块 | 代码职责和数据所有权边界 | 剧本、人物、场景、审核 |
| 验证模块 | 检查一条业务或技术链路的范围 | checks 模块 1、2、3 |
| Agent 角色与执行单元 | AI 能力的业务角色及具体实现 | 任务书的 13 类角色、当前注册的 17 个执行 ID |

三者不要求一一对应。模块 3 的检查会跨人物、场景、审核和工作流模块；人物业务模块内部也可以包含多个 Agent。

### 2.1 目标模块划分

| 模块 | 负责内容 | 角色归属 |
| --- | --- | --- |
| `studio_projects` | 项目基础信息、成员、访问权限 | 无专属 Agent |
| `studio_story` | 源文档、章节、剧本、故事事件、对白及版本 | Script |
| `studio_characters` | 人物身份、别名、关系、档案、形象资产 | Character、Character Vision、Character Image |
| `studio_scenes` | 场景身份、证据、描述、档案与参考资产 | Scene |
| `studio_production` | 导演、分镜、提示词、镜头、视频、音频、剪辑、评估和导出 | Director、Storyboard、Prompt、Video、Audio、Editing、Evaluation |
| `studio_reviews` | 待审对象、审核决定、审核意见及其业务规则 | 确定性业务代码 |
| `studio_workflow` | 生产阶段、人工关卡、暂停恢复及模块协调 | Orchestrator 的计划能力 |
| `studio_assets` | 业务资产登记、版本和存储引用，解除 story 与 production 的双向依赖 | 无专属 Agent |
| `studio_configuration` | 管理端配置版本账本，与底层配置解析分开 | 无专属 Agent |
| `studio_ai_runtime` | 通用执行协议、Provider、模型调用、结构化校验和执行事件 | 公共运行机制 |
| `studio_platform` | 配置、数据库基础设施、存储、媒体工具和任务调度实现 | 公共技术能力 |
| `studio_contracts` | 少量稳定的跨模块数据契约 | ID、版本引用、资产引用、执行结果等 |

源文档、章节和剧本放在同一个 story 模块，便于管理它们的版本关系和频繁读取；projects 模块保持项目身份与权限职责。production 模块内部再按规划、生成、后期和质量组织，不将所有制作逻辑集中到单个文件。

### 2.2 保留 13 类角色与 17 个执行 ID

| 任务书角色 | 保留的执行 ID |
| --- | --- |
| Orchestrator | `orchestrator` |
| Script | `script` |
| Character | `character_extraction`、`character_description`、`character_consistency` |
| Character Vision | `character_vision` |
| Character Image | `character_image` |
| Scene | `scene_extraction`、`scene_description` |
| Director | `director` |
| Storyboard | `storyboard` |
| Prompt | `prompt` |
| Video | `video` |
| Audio | `audio`、`audio_voice` |
| Editing | `editing` |
| Evaluation | `evaluation` |

业务模块声明自己提供的 Agent 实现，由启动应用统一注册到 AI runtime。AI runtime 不反向导入各业务模块。家族分组本身不增加父 Agent 动态指挥子 Agent 的行为。

Orchestrator 当前提供计划输出，生产流程仍由 YAML 驱动。场景参考图、完整服装与状态管理、音乐音效等任务书目标，按各自实际实现和验收状态管理，不能仅凭目录或角色已经存在认定完成。

## 3 当前 workspace 目录与模块内部结构

当前已建立以下同仓多包 workspace。源码通过成员安装后导入，仓库根项目负责统一开发工具与应用依赖：

```text
video_agent/
├── pyproject.toml                    workspace 与统一工具配置
├── uv.lock                          一套共同解析的依赖
├── .env                             本地环境配置，不提交
├── .env.example                     可提交的配置模板
├── config/                          Agent、Provider、提示词、工作流配置
├── apps/
│   └── studio_api/
│       ├── pyproject.toml
│       └── src/studio_api/
│           ├── main.py              应用入口
│           ├── bootstrap/           Agent/Schema/ORM/审核端口装配
│           ├── resource_root.py     统一资源定位
│           └── resources/           构建前同步的资源交付副本
├── packages/
│   ├── studio_projects/
│   ├── studio_story/
│   ├── studio_characters/
│   ├── studio_scenes/
│   ├── studio_production/
│   ├── studio_reviews/
│   ├── studio_workflow/
│   ├── studio_assets/
│   ├── studio_configuration/
│   ├── studio_ai_runtime/
│   ├── studio_platform/
│   └── studio_contracts/
├── backend/
│   ├── app -> ../apps/studio_api/src/app  旧路径兼容链接
│   └── tests/                       仓库级回归与架构检查
├── scripts/checks/                   跨模块验证入口
└── docs/
```

每个业务包采用相同、轻量的内部结构，以人物模块为例：

```text
studio_characters/
├── pyproject.toml
├── src/studio_characters/
│   ├── README.md
│   ├── public.py                    对其他模块开放的用例和查询
│   ├── contracts.py                 对外输入输出数据类型
│   ├── application/                 提取、描述、编辑等用例协调
│   ├── domain/                      身份、关系、版本等业务规则
│   └── infrastructure/
│       ├── persistence/             人物仓储与 ORM 适配
│       └── agents/                  人物相关 AI 实现
└── （对应回归仍集中在 backend/tests）
```

模块较小时可以先使用少量文件，不为形式创建空目录。公开用例变多后，再将 `public.py` 拆为公开 API 包。

uv workspace 中，每个成员有自己的 `pyproject.toml`，共同使用一个锁文件和兼容的依赖解；它不会给每个模块自动创建独立环境，也不自动提供部署或导入安全隔离。[uv workspace 机制与限制](https://docs.astral.sh/uv/concepts/projects/workspaces/)

`src` 布局用于区分可安装的代码与仓库工具、文档等文件，开发和测试通过 `uv sync --frozen --extra dev` 安装的成员包导入；标准启动、质量门禁和检查脚本不再注入 backend 路径。[Python 包布局说明](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)

## 4 依赖与数据所有权规则

### 4.1 公开接口规则

- 跨业务模块只调用公开用例、查询和数据契约，不导入对方的内部仓储、ORM 或私有函数。
- 新的跨业务读取返回 ID、版本引用、DTO 或明确结果。多数用例仍接受外层 Session 维持既有事务；旧 ORM 返回通过显式兼容接口保留，不能称全量 Session/ORM 解耦。
- 同一业务规则只保留一个权威实现。兼容入口转发调用，不复制逻辑。
- `studio_contracts` 仅保存稳定的跨模块协议，不集中所有业务 Schema，也不依赖数据库、HTTP 或业务模块。

### 4.2 模块内部依赖方向

```text
接口入口 → 应用用例 → 领域规则
                   → 能力接口
技术实现            → 能力接口

启动应用负责将技术实现装配到用例中。
```

领域规则不依赖 FastAPI、SQLAlchemy、HTTP 客户端或全局 AppRuntime。应用层协调读取、执行和提交；基础设施实现具体读写与调用。

数据库初期继续共享，模块划分先明确写入所有权。例如人物模块管理人物档案写入，审核模块管理审核记录，生产流程协调它们的公开操作。共同的数据库基类、连接和 Session 工厂由 platform 提供，保持单份 ORM 元数据。

### 4.3 工作流与 Agent 边界

工作流单向协调业务模块。业务模块完成自身操作，不反向依赖整条影片工作流。审核模块接收明确待审引用并返回决定，由应用用例按现有规则应用决定。

Agent 通过自己的输入输出契约返回候选产物与执行证据；资产归属、版本、canonical、审批状态和项目状态由业务用例处理。通用模型执行与具体角色实现分开，避免 AI runtime 变成所有业务逻辑的集中点。

模块依赖形成有向无环关系，并在 CI 中检查循环依赖、内部实现越界访问及未声明的依赖。可借鉴 [Spring Modulith 的结构验证规则](https://docs.spring.io/spring-modulith/reference/verification.html)，在 Python 中通过静态导入约束或架构测试落实。

## 5 现有代码的迁移归属

| 当前区域 | 目标归属与处理方式 |
| --- | --- |
| API 路由及序列化 | 保持 HTTP 契约，逐步调用业务模块公开用例；跨实体查询改为明确查询服务 |
| `services/documents.py`、剧本相关 pipeline 函数 | story 模块，集中导入解析、剧本生成、事件和版本操作 |
| 人物与场景相关 pipeline 函数 | characters、scenes 模块，分别拥有实体、档案和编辑用例 |
| 导演、分镜、提示词与 `services/media.py` | production 模块，内部按业务步骤拆分 |
| `services/reviews.py` | reviews 模块与对应业务模块的审批适配，保持当前审核语义 |
| `services/workflow.py` 与节点 handlers | workflow 模块，节点通过公开接口协调业务模块 |
| Agent 实现 | 迁入所属业务模块的 AI 适配部分；通用基类与 Provider 进入 ai_runtime |
| `services/agent_runner.py` | 分开通用执行和应用侧审计、预算协调，保持记录时机与结果契约 |
| 各业务 ORM 映射与仓储 | 所属业务模块的持久化适配，迁移期保留旧 models 导入路径 |
| 共享 ORM 基础、配置、存储、FFmpeg、TaskRunner | Base、metadata、连接和 Session 工厂等进入 platform，业务模块通过适配接口使用 |
| 模块 1～3 检查 | 保留仓库级入口，逐步使用公开接口和检查专用依赖注入 |

旧 `app.services.pipeline`、reviews、Agent、Schema 等导入路径在迁移期间保留兼容门面或重新导出。兼容入口保持原函数名、同步或异步形式、返回类型和异常语义；需要返回 ORM 对象时，在原 Session 中转换，不新增隐式提交或另开事务。

canonical 包实现不再反向调用旧 app 门面，主要跨模块输入改用公开 DTO、只读端口和 ID 命令。HTTP 适配与显式 legacy 接口仍有 ORM 返回；兼容文件只承担转发职责，删除旧入口作为单独兼容性变更处理。

## 6 配置与运行约束

启动应用统一定位并加载根目录 `.env`、`config` 和资源路径，然后装配各模块。模块不各自寻找 `.env`，也不复制凭据配置。

现有默认文字 Provider 标识 `fast_gateway` 保持，继续使用：

- `FAST_GATEWAY_BASE_URL`：接口地址。
- `FAST_GATEWAY_MODEL`：模型名。
- `FAST_GATEWAY_API_KEY`：密钥。

保留当前环境变量优先级、显式缺失引用的错误处理、有效配置指纹与 mock/live 区分。真实凭据不进入包、镜像、安装器、文档或报告。

多模块仍共同组成一个受管应用实例。TaskRunner 的调度与 Workflow 的业务推进分开管理；拆目录和 workspace 不自动带来可靠队列、独立进程或微服务。将来只有明确需要独立部署与扩容的部分，才另行规划服务拆分。

LangGraph、DSH、Pi 保持独立技术选项。后续若接入，位于工作流编排或 AI 执行适配边界，并继续使用业务模块公开接口；本方案不以框架接入为前提。

## 7 分阶段迁移与交付

| 阶段 | 实施结果 | 当前验收边界 |
| --- | --- | --- |
| 0 固定基线 | 记录源代码、API、表结构和既有测试；原源码备份与功能分支提交保留 | 历史记录与本次 workspace 验证分别标注 |
| 1 逻辑模块化 | 业务/技术职责分开，明确 public/contracts 与技术公开入口 | canonical 源码依赖 DAG、领域依赖与旧路径身份进入架构检查 |
| 2 分批迁用例 | 业务用例、ORM、Schema、Agent 已归属对应包；批准写入由所有者执行 | 主要读取使用 DTO，原 Session 事务和显式 legacy ORM 返回继续兼容 |
| 3 建立多包工程 | 13 成员 uv workspace、src、独立清单、共享锁文件与资源同步已实施 | 已安装成员回归通过；Docker daemon 不可用、Windows 原生交付未验收 |
| 4 收束调用关系 | 工作流、任务和主要业务消费者使用公开入口、DTO/ID/端口；检查脚本使用已安装包 | 保留旧导入转发和 HTTP/legacy ORM 适配；逐项收尾不等于已删除兼容层 |

结构迁移保持以下外部契约：

- HTTP 路由、请求响应字段、错误状态码与任务返回结构。
- 数据库表列、业务主键、档案版本与当前业务状态转换。
- 17 个 Agent ID、Provider 协议、Schema 名称、提示词变量和 YAML 配置路径。
- 模块 1～3 的脚本入口、CLI、模式说明、报告字段及真实/mock 来源判断。
- 单实例启动约定，以及当前节点事务的提交、回滚责任。

每一批迁移作为可独立验收和回退的变更，不将业务修复、目录移动、打包更换混在同一批。回退以该批源代码和包依赖变更为单位，不恢复或覆盖用户的业务数据库。

## 8 验收标准与阅读体验

以下标准保留为审查清单，完成状态以实际证据为准。当前 workspace 正式后端回归为 361 项通过；Docker 容器运行和 Windows 原生安装未执行，完整仓储/DTO 解耦也未覆盖所有历史接口。离线机制证据不替代这些交付验证。

### 8.1 结构验收

- 模块依赖无循环；跨模块访问只经过公开入口。
- 领域规则没有技术框架依赖；技术资源通过明确接口装配。
- 新用例不借道旧服务门面执行，兼容入口不复制业务实现。
- 公共包没有收纳人物、场景、审核等具体业务规则。
- 模块 README 说明职责、公开操作、允许依赖、数据所有权和测试入口。

### 8.2 行为与集成验收

- 迁移前后对照 API、数据库元数据、Schema 导出、权限、错误和配置契约。
- 各业务模块具有规则测试、用例测试和必要的数据访问合约测试。
- 模块 1～3 继续验证跨模块链路，保持沙箱隔离、清理与凭据脱敏。
- 审核暂停、驳回、批准和恢复等现有行为保持一致；新的审核规则另作验收。
- 移动执行位置时，同步迁移模块 3 的 Agent 调用观察点，确保禁止下游调用的检查仍然有效。
- 重构后的验证记录关联实际代码与配置版本，不能直接把历史通过报告作为新结构已通过的证据。
- 真实模型验收与离线机制测试分别记录，避免将 stub、规则补全或 mock 产物计为模型效果。

### 8.3 可读性验收

开发者打开一个业务模块，就能找到其公开能力、核心规则、数据访问、相关 Agent 和测试。一次人物业务修改主要落在人物模块；跨模块变化通过公开契约和工作流协调位置显式体现。

实现本方案后，阅读代码应从“按业务找到模块，再追踪一次用例”开始，而不是先在所有技术目录中搜索同一功能。

## 9 当前文档关系

- [现有架构说明](overview.md)描述当前实现，不因本提案而自动变成目标结构。
- [任务书](../../task.md)定义业务目标和 13 类角色。
- [Agent 说明](../agents/README.md)与[模型配置](../model_configs/README.md)继续作为现有契约参考。
- [测试说明](../testing/README.md)记录检查方式；重构实施时按实际入口同步更新。
- [架构决策记录](../decisions/README.md)保留现有历史。正式改变已有决策时，新增对应 ADR，不覆盖旧决策。
