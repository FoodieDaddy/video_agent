# 公共技术基础模块

本模块是 uv workspace 成员 `studio-platform`，正式源码在
`packages/studio_platform/src/studio_platform/`，依赖声明位于成员 `pyproject.toml`。
在仓库根执行 `uv sync --frozen --extra dev` 后，通过 `studio_platform` 导入；旧
`app.modules.platform` 仅作转发兼容。回归位于 `backend/tests`，架构入口为
`uv run --frozen --extra dev python -m pytest backend/tests/test_modular_architecture.py`。

直接工作区依赖：`studio-contracts`；外部依赖见成员清单。

此模块保存配置读取、共享数据库基础、存储、媒体工具和确定性文本处理的唯一实现。业务用例、审核决定和业务 ORM 映射不集中到此处。

| 区域 | 职责 |
| --- | --- |
| `configuration` | settings、环境引用解析、ConfigStore 与提示词缓存 |
| `persistence` | 单份 Base/metadata、engine、Session 工厂、版本查询和任务事件记录 |
| `media` | FFmpeg/ffprobe 技术调用 |
| `text` | 不含模型调用的文本处理规则 |
| `storage` | 本地与 S3 存储实现 |
| `execution` | AppRuntime 资源容器，以及只接收处理函数的 TaskRunner |
| `resources` | 消费应用提供的资源根；源码开发保留根目录回退 |
| `security` | 现有请求身份解析与权限入口 |
| `constants`、`exceptions`、`ids` | 迁移期保留的状态定义、错误与 ID 基础工具 |

旧 `app.core`、`app.db.session`、`app.models.base`、`app.utils` 下的相应模块通过模块别名兼容。新旧导入指向同一模块对象，因此配置缓存、数据库全局状态及测试中的 monkeypatch 不产生第二份实现。

`public.py` 提供运行时、配置和 ID 的最小公共入口。旧 `app.services.runtime` 同样是模块别名；版本号的当前查询语义由 `persistence.versions.next_version` 保留，事务仍由原调用方管理。

任务记录、线程执行和业务分派分开：`persistence.task_records` 保存任务与事件读写，`execution.task_runner` 运行传入的处理函数，业务任务类型由 workflow 模块解释。运行器不导入 workflow 或 AI 执行实现；旧 `app.services.tasks` 经 workflow 分派入口重导出记录与运行器能力。

应用统一定位仓库或 wheel 内资源，并支持显式 `STUDIO_RESOURCE_ROOT`。platform 只消费该配置；根 `.env`、config 和 data 的配置语义保持，测试可独立指定目录。

`init_schema()` 只使用已装配的映射；应用 `studio_api.bootstrap.model_catalog` 聚合业务映射并提供注册入口。platform 不导入应用或旧 `app.models`，共享 Base/metadata 始终只有一份；独立使用时由调用方负责映射装配。
