# 第三批重构：工作流定义快照

## 背景
此前 WorkflowRun 只保存工作流 ID、版本号和执行游标。恢复时重新读取当前 YAML，因此工作流定义在运行期间修改后，暂停中的任务可能用新节点继续执行，产生不可预测的流程漂移。

## 实施
- 新建 WorkflowRun 时，将实际 WorkflowConfig 序列化到 `state.workflow_definition`。
- 恢复时优先从该快照验证并重建 WorkflowConfig。
- 兼容旧记录：没有快照的历史 WorkflowRun 仍读取当前配置。
- 新增回归测试，确保带快照的恢复不访问可变的当前工作流配置。
- 不新增数据库列，不需要迁移现有数据库。

## 边界
当前只冻结工作流定义本身。Agent/Prompt/Provider 配置、环境变量、模型供应商实际版本和外部服务行为仍可能变化；需要后续增加完整执行配置快照与模型调用幂等/补偿设计。

## 验证
- `backend/tests/test_workflow_service.py` 与 `backend/tests/test_modular_architecture.py` 联合运行通过，20 项。
- 全量后端测试曾尝试运行，但超出当前执行时限，因此不宣称全量通过。
