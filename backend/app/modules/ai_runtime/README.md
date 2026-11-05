# AI 运行模块

本模块提供通用 Agent 执行机制与模型能力适配。具体剧本、人物、场景、制作和总控 Agent 的实现位于各业务模块的 `infrastructure/agents`，本模块不静态导入这些实现。

## 公开接口

- `public.py`：应用侧执行协调 `run_agent`、Agent 上下文与结果、执行 ID 查询与创建。
- `base.py`：`BaseAgent`、`StructuredLLMAgent`、`StructuredVisionAgent`、`MediaAgent` 及输入输出协议，供业务 Agent 实现使用。
- `providers/base.py`：文字、视觉、图像、视频、音频能力协议与请求结果类型。
- `providers/registry.py`：按配置选择模型能力的工厂及参数检查；具体 HTTP 和 mock Provider 为内部实现。

`application/execution.py` 在本次迁移中保留原有 Session、审计、预算和事务责任。它先记录已校验输入，再执行 Agent，最后按原时机写入结果与用量；不额外提交或另开 Session。后续持久化接口的进一步拆分应单独验收。

## 注册与生命周期

应用组合根 `app.bootstrap.agent_catalog.register_agents()` 显式装配 13 类业务角色对应的 17 个执行 ID。正常启动和旧入口惰性装配调用同一函数，同一实现可重复注册，冲突不会静默覆盖。

配置仍来自现有 ConfigStore 和项目 `.env`，模型引用、环境变量优先级、有效指纹、显式环境 URL 缺失时停止构造等行为保持。

## 兼容与检查

旧 `app.agents`、`app.providers` 和 `app.services.agent_runner` 路径保留兼容入口。迁移文件通过模块别名指向同一 canonical 对象，尤其保留 `agent_runner.create_agent` 和 Provider `_client` 的测试观察点；没有复制第二套类或注册表。

验证重点为 17 个执行 ID、旧新模块对象同一性、Provider 合约、配置环境引用、模块 1～3 的 mock/live 来源判断及越界 Agent 检查。相关回归继续位于 `backend/tests` 和 `scripts/checks`，本模块本身不启动服务或工作进程。
