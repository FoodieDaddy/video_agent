# 架构预留与 TODO（本轮不实现）

本文件仅记录未来可能需要的工程能力。不要为了清空 TODO 提前引入依赖。

## P1：代码边界完善
- [ ] 将共享 `app/api/routes` 中的路由逐步迁入各模块 `interfaces/http`；迁移时保留旧 import shim。
- [ ] 将共享 `app/schemas` 按业务模块归属迁入各模块 `contracts.py`，保持单一 Pydantic 类型来源。
- [ ] 将共享 `app/models` 的 ORM 映射按模块迁入 `infrastructure/persistence`，维持唯一 SQLAlchemy MetaData。
- [ ] 为每个模块补充 domain/application/infrastructure 的依赖规则测试。

## P2：持久化边界
- [ ] 在确有价值的用例中引入 Repository Port 与 SQLAlchemy Adapter。
- [ ] 明确事务由 Application Unit of Work 统一协调；Agent 不管理事务。
- [ ] 不为简单 CRUD 机械增加 Repository 抽象。

## P3：运行时能力（暂不实施）
- [ ] 评估任务队列、Worker 和崩溃恢复需求。
- [ ] 评估多进程 Agent 执行与模型调用并发控制。
- [ ] 评估 OTel/指标和结构化审计。

## 当前不做
- 不拆微服务。
- 不引入 Celery、Redis、Kafka、服务网格。
- 不做动态扫描式 Agent 自动发现。
- 不重写所有业务流程或数据库模型。
