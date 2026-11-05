# production 业务模块

本模块是 uv workspace 成员 `studio-production`，正式源码在
`packages/studio_production/src/studio_production/`，依赖声明位于成员 `pyproject.toml`。
在仓库根执行 `uv sync --frozen --extra dev` 后，通过 `studio_production` 导入；旧
`app.modules.production` 仅作转发兼容。回归位于 `backend/tests`，架构入口为
`uv run --frozen --extra dev python -m pytest backend/tests/test_modular_architecture.py`。

直接工作区依赖：`studio-ai-runtime`、`studio-assets`、`studio-characters`、`studio-platform`、`studio-projects`、`studio-scenes`、`studio-story`；外部依赖见成员清单。

公开入口为 `public.py`；内部 `application` 按读取投影与业务用例分开。制作媒体用例按镜头视频、配音字幕、剪辑渲染拆分；人物资产实现归 studio_characters，旧制作入口转发；旧 `application.media` 只保留同一函数对象的兼容重新导出。

用例保留调用方 Session 的事务责任；新跨模块读取使用公开 DTO，旧 ORM 返回仅按兼容契约保留。

`application/approval.py` 拥有制作产物批准写入。reviews 的分镜校验只接收 `StoryboardApprovalTargets` ID DTO，批准仍作用于已验证的分镜、导演和镜头；当前镜头/成片关卡保持原有选择范围。
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
