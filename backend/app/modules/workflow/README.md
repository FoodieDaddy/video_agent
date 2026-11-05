# 生产流程模块

现有YAML流程引擎、节点协调、检查点、暂停与恢复。

- 公开入口：`public.py`。
- 用例实现：`application/`。
- 边界：节点经其它业务模块公开入口调用；本批不改变执行顺序、事务提交或取消语义。
- 兼容：旧 `app.services` 入口指向同一实现模块，保留签名、ORM返回与monkeypatch观察点。
- 事务：沿用调用方提供的Session；不因迁移额外提交或另开Session。
- 验证：现有API、工作流和模块检查回归；本批不新增网络服务。


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
