# 业务资产基础能力模块

本模块是 uv workspace 成员 `studio-assets`，正式源码在
`packages/studio_assets/src/studio_assets/`，依赖声明位于成员 `pyproject.toml`。
在仓库根执行 `uv sync --frozen --extra dev` 后，通过 `studio_assets` 导入；旧
`app.modules.assets` 仅作转发兼容。回归位于 `backend/tests`，架构入口为
`uv run --frozen --extra dev python -m pytest backend/tests/test_modular_architecture.py`。

直接工作区依赖：`studio-platform`；外部依赖见成员清单。

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

HTTP 适配位于 `studio_api`；业务 ORM 和 Schema 的唯一实现已归属各包。旧 `app.models`、
`app.schemas` 与服务路径继续导出同一对象。部分显式 legacy 公共接口仍接受 Session 或返回 ORM，
不能据此称完整仓储/DTO 解耦；删除兼容入口另作消费者审计与发布变更。
