# story 业务模块

公开入口为 `public.py`；内部 `application` 按读取投影与业务用例分开。剧本正文和工作流基线指纹规则位于纯 `domain` 层；application 负责将 ORM 行投影为不可变指纹输入并执行数据库读取。剧本、章节、源文档和故事事件的 ORM 映射归 story 模块持有，旧 `app.models.story` 路径转发到同一映射模块。

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
