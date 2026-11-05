# scenes 业务模块

制作模块通过 `list_scene_snapshots()` 读取场景身份、名称与生成配置深副本；既有档案投影、
visual_prompt 和场景排序由原查询复用。旧 `list_scenes()`、`scene_payload()` 继续供所属模块
及 API 兼容调用，制作模块不再接收 Scene ORM。

公开入口为 `public.py`；内部 `application` 按读取投影与业务用例分开。

`application/approval.py` 拥有当前场景档案批准写入。reviews 通过公开入口协调第一关，保留 canonical 档案及缺档案的现有语义；阶段用例不提交，兼容单场景入口按原约定 flush。

本批迁移保留调用方 Session 和原有返回对象，未改变事务与业务规则。
跨业务依赖通过公开接口访问，Agent 实现在 `infrastructure/agents`，由启动目录装配。


## 标准包结构与职责

本模块遵循统一的 Java/Spring 风格分层约定（Python 包实现）：

- `domain/`：实体、值对象、领域规则和领域服务；不依赖 FastAPI、SQLAlchemy、Provider 或其他业务模块。
- `application/`：用例编排、命令/查询、事务边界协调；通过本模块公开契约调用领域能力。
- `infrastructure/`：SQLAlchemy 持久化适配、外部服务适配和本模块 Agent 实现。
- `interfaces/`：HTTP/API、CLI 等输入输出适配；只做参数校验、身份上下文转换和用例调用。
- `contracts.py`：跨模块稳定的数据契约；不得暴露内部 ORM 实体作为长期跨模块协议。
- `public.py`：唯一跨业务模块入口；其他模块禁止导入本模块的内部目录。

目前部分历史逻辑仍保留在兼容目录或共享 `app.api`、`app.models`、`app.schemas` 中。
新增代码按上述结构落位；旧代码按依赖风险逐批迁移，不为追求目录整齐一次性搬迁。
