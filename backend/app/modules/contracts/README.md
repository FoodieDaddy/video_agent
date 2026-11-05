# 跨模块契约

当前只提供无业务状态的序列化能力，供任务基础设施与 AI 执行协调共同使用。具体剧本、人物、场景、制作和工作流的 Pydantic 输入输出，分别通过各业务模块的 `contracts.py` 命名接口公开，类型定义仍以原 Schema 为单一来源。

## 公开接口

`public.py` 导出 `json_safe`、`serialize_output`、`dumps`。这些函数保留原审计序列化行为：二进制输入只记录长度，媒体 dataclass 输出不把 content 字节复制进数据库，嵌套数据转换为 JSON 列可接收的值。

本模块不导入业务模块、SQLAlchemy、网络客户端或 Agent 执行器。不把审核、版本、人物身份等业务规则放入此处。旧 AgentRunner 继续重新导出同一函数对象，兼容现有调用方。
