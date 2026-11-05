# characters 业务模块

本模块是 uv workspace 成员 `studio-characters`，正式源码在
`packages/studio_characters/src/studio_characters/`，依赖声明位于成员 `pyproject.toml`。
在仓库根执行 `uv sync --frozen --extra dev` 后，通过 `studio_characters` 导入；旧
`app.modules.characters` 仅作转发兼容。回归位于 `backend/tests`，架构入口为
`uv run --frozen --extra dev python -m pytest backend/tests/test_modular_architecture.py`。

直接工作区依赖：`studio-ai-runtime`、`studio-assets`、`studio-platform`、`studio-projects`、`studio-story`；外部依赖见成员清单。

公开入口为 `public.py`；内部 `application` 按读取投影与业务用例分开。

人物图片生成、形象版本登记及审批写入归本模块持有，原 production 人物资产路径继续转发。
跨模块读取优先使用人物身份、声线和计数 DTO，头像查询只返回资产 ID；服装/状态归属由
本模块仓储核对。新人物图片调用传 `character_ids`，在模块内读取实体；旧 ORM 参数继续兼容。
制作读取使用 `list_character_snapshots()`，DTO 含身份、名称与生成 payload 深副本；其生成字段
复用原 `character_payload()`，缺档案默认值和人物排序保持一致。

用例保留调用方 Session 的事务责任；新跨模块读取使用公开 DTO，旧 ORM 返回仅按兼容契约保留。
跨业务依赖通过公开接口访问，Agent 实现在 `infrastructure/agents`，由启动目录装配。


## 标准包结构与职责

本模块遵循统一的 Java/Spring 风格分层约定（Python 包实现）：

- `domain/`：实体、值对象、领域规则和领域服务；不依赖 FastAPI、SQLAlchemy、Provider 或其他业务模块。
- `application/`：用例编排、命令/查询、事务边界协调；通过本模块公开契约调用领域能力。
- `infrastructure/`：SQLAlchemy 持久化适配、外部服务适配和本模块 Agent 实现。
- `interfaces/`：HTTP/API、CLI 等输入输出适配；只做参数校验、身份上下文转换和用例调用。
- `contracts.py`：跨模块稳定的数据契约；不得暴露内部 ORM 实体作为长期跨模块协议。
- `public.py`：唯一跨业务模块入口；其他模块禁止导入本模块的内部目录。

HTTP 适配位于 `studio_api`；业务 ORM 和 Schema 的唯一实现已归属各包。旧 `app.models`、
`app.schemas` 与服务路径继续导出同一对象。部分显式 legacy 公共接口仍接受 Session 或返回 ORM，
不能据此称完整仓储/DTO 解耦；删除兼容入口另作消费者审计与发布变更。
