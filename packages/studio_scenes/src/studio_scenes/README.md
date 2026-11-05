# scenes 业务模块

本模块是 uv workspace 成员 `studio-scenes`，正式源码在
`packages/studio_scenes/src/studio_scenes/`，依赖声明位于成员 `pyproject.toml`。
在仓库根执行 `uv sync --frozen --extra dev` 后，通过 `studio_scenes` 导入；旧
`app.modules.scenes` 仅作转发兼容。回归位于 `backend/tests`，架构入口为
`uv run --frozen --extra dev python -m pytest backend/tests/test_modular_architecture.py`。

直接工作区依赖：`studio-ai-runtime`、`studio-platform`、`studio-projects`、`studio-story`；外部依赖见成员清单。

制作模块通过 `list_scene_snapshots()` 读取场景身份、名称与生成配置深副本；既有档案投影、
visual_prompt 和场景排序由原查询复用。旧 `list_scenes()`、`scene_payload()` 继续供所属模块
及 API 兼容调用，制作模块不再接收 Scene ORM。

公开入口为 `public.py`；内部 `application` 按读取投影与业务用例分开。

`application/approval.py` 拥有当前场景档案批准写入。reviews 通过公开入口协调第一关，保留 canonical 档案及缺档案的现有语义；阶段用例不提交，兼容单场景入口按原约定 flush。

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
