# 人工审核模块

待审记录、审核意见、决定与按当前业务规则应用批准。

- 公开入口：`public.py`。
- 用例实现：`application/`。
- 纯规则：`domain/decisions.py` 判断审核结论是否合法、当前记录是否仍待审，
  不依赖数据库或 HTTP；应用用例将违规原因映射回原异常并执行原来的状态写入。
- 边界：审核通过与工作流恢复是两个操作，不在此启动后续模型任务。
- 写入归属：人物、场景、分镜、镜头和剪辑的批准标记分别由所属模块的公开 approval 用例写入，reviews 只协调决定与项目阶段；每批仍由调用方统一 flush/提交。
- 分镜目标：提审和批准使用 production 返回的快照与 `StoryboardApprovalTargets` ID DTO。旧 `assert_review_snapshot` 保留 ORM 元组返回，新的审批和工作流续跑调用 `assert_review_targets`。
- 工作流读取：reviews 定义 `WorkflowReviewReader` 端口，由 `bootstrap/review_dependencies.py` 注入 workflow 的只读投影；正式启动与旧兼容服务入口显式装配。独立使用 canonical 用例时须注入 reader 或应用 loader，未装配时明确报错；审核模块不导入工作流模型、引擎或应用 bootstrap。
- 兼容：旧 `app.services` 入口指向同一实现模块，保留签名、ORM返回与monkeypatch观察点。
- 事务：沿用调用方提供的Session；不因迁移额外提交或另开Session。
- 验证：`backend/tests/test_review_domain.py` 直接验证状态规则与异常映射；
  现有 API、工作流和模块检查继续验证集成行为。本批不新增网络服务。


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
