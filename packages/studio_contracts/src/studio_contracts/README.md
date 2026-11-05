# 跨模块契约

本模块是 uv workspace 成员 `studio-contracts`，正式源码在
`packages/studio_contracts/src/studio_contracts/`，依赖声明位于成员 `pyproject.toml`。
在仓库根执行 `uv sync --frozen --extra dev` 后，通过 `studio_contracts` 导入；旧
`app.modules.contracts` 仅作转发兼容。回归位于 `backend/tests`，架构入口为
`uv run --frozen --extra dev python -m pytest backend/tests/test_modular_architecture.py`。

直接工作区依赖：无；外部依赖见成员清单。

当前提供无业务状态的序列化能力和最小 ProjectIdentity 协议，供任务基础设施与 AI 执行协调共同使用。具体剧本、人物、场景、制作和工作流的 Pydantic 输入输出，分别通过各业务模块的 `contracts.py` 命名接口公开，类型定义由各业务包 schemas 目录持有，旧路径只作转发。

## 公开接口

`public.py` 导出 `ProjectIdentity`、`json_safe`、`serialize_output`、`dumps`。这些函数保留原审计序列化行为：二进制输入只记录长度，媒体 dataclass 输出不把 content 字节复制进数据库，嵌套数据转换为 JSON 列可接收的值。

本模块不导入业务模块、SQLAlchemy、网络客户端或 Agent 执行器。不把审核、版本、人物身份等业务规则放入此处。旧 AgentRunner 继续重新导出同一函数对象，兼容现有调用方。
