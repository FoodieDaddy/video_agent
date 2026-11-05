# 业务资产基础能力模块

资产记录、版本、存储key、读取与对外表示。

- 公开入口：`public.py`。
- 用例实现：`application/`。
- 读取边界：`application/queries.py` 投影只读 `AssetReference`；SQL 查询集中在 `infrastructure/persistence/repository.py`。空 ID/记录缺失继续返回 None；按项目和类型查询最近资产保留创建时间倒序规则。
- 兼容返回：`get_legacy_asset()`、`latest_legacy_asset()` 只供尚未迁移的成片 ORM 返回接口使用；新跨模块读取使用 DTO。DTO 不负责访问授权或证明存储文件存在。
- 边界：story 与 production 都依赖本模块；本模块不反向依赖业务生成模块。
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
- 新资产写入跨模块优先使用 `save_asset_reference()` 返回不可变 `AssetReference`；旧 `save_asset()` 保留 ORM 返回给暂未迁移的调用方。
- `public.py`：唯一跨业务模块入口；其他模块禁止导入本模块的内部目录。

目前部分历史逻辑仍保留在兼容目录或共享 `app.api`、`app.models`、`app.schemas` 中。
新增代码按上述结构落位；旧代码按依赖风险逐批迁移，不为追求目录整齐一次性搬迁。
