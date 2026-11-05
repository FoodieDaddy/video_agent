# 逻辑业务模块

这里是模块化单体的当前实现。各模块共同运行在一个应用中，启动入口仍为 `app.main:app`；尚未拆成独立微服务或 uv workspace 成员。

## 应用组合与生命周期

应用入口采用明确的组合边界：`app.main` 负责创建 FastAPI、注册中间件/异常处理及挂载路由；`app.bootstrap.lifespan` 负责 Runtime、数据库与 Agent 的启动/关闭；`app.api.routes.system` 负责健康检查和本地媒体 HTTP 接口。新增系统 HTTP 接口应放在 `api/routes`，进程资源初始化应放在 `bootstrap`，不要重新堆回 `main.py`。

## 从哪里阅读代码

先打开对应模块的 `public.py` 查看公开能力，再进入 `application` 查找用例或读取投影。Agent 实现在所属业务模块的 `infrastructure/agents`；输入输出契约从模块 `contracts.py` 导出。

| 模块 | 主要职责 |
| --- | --- |
| `projects` | 项目、成员与权限边界 |
| `story` | 源文档、章节、剧本、事件与对白 |
| `characters` | 人物提取、档案、关系及人物相关 Agent |
| `scenes` | 场景提取、文字档案及场景 Agent |
| `production` | 导演、分镜、镜头、媒体、剪辑与评估 |
| `reviews` | 审核决定与批准处理；`domain` 保存现有纯状态判断 |
| `workflow` | 生产流程、节点、业务任务类型与分派 |
| `assets` | 资产登记、版本和存储引用，不承担底层字节存储 |
| `configuration` | 管理端配置版本账本，与配置文件解析分开 |
| `ai_runtime` | 公共 Agent 基类、Provider、注册表及执行审计协调 |
| `platform` | 配置解析、共享数据库基础、存储、媒体工具、技术任务运行器 |
| `contracts` | 不含业务规则的公共序列化协议 |

`assets` 独立出来，避免 story 的文档资产管理与 production 对 story 的读取构成循环。`configuration` 管理配置版本用例；`platform/configuration` 只负责配置类型、环境引用、YAML 和提示词加载。

## 依赖规则

- 跨业务模块只引用 `public` 或 `contracts`，不读取其他模块的私有函数或应用内部文件。
- 公共技术模块具有明确的命名接口，允许范围由 `backend/tests/test_modular_architecture.py` 检查。
- 所有模块依赖必须无环，新实现不再导入旧 `app.services`、`app.core` 等兼容入口。
- 领域规则只依赖标准库和自身领域代码。当前纯领域抽取先覆盖审核决定，其他业务规则后续分批提取。
- 具体 Agent 由 `app.bootstrap.agent_catalog` 组装，AI 注册表不静态依赖业务 Agent。13 类角色继续对应原有 17 个执行 ID。

## 兼容期边界

这批应用用例仍使用原有 Session 和 ORM 返回类型，事务继续由原调用方管理；完整仓储、DTO 边界和业务 ORM 归属尚未完成。旧 `models` 和 `schemas` 仍是唯一映射与 Pydantic 定义，模块契约仅重新导出，不复制类。

原 `services/pipeline.py` 是函数转发门面，其他已迁移旧入口通过模块别名指向唯一实现。这样旧导入、配置缓存、数据库元数据和测试 monkeypatch 继续使用同一对象。新增业务调用应直接使用本目录公开入口。

API 路由、工作流、任务和检查脚本已接入新模块；`ai_runtime.public.execution` 保留可观察的 Agent 创建入口，模块 3 的越界调用保护仍作用于真实执行链。

## 配置和验证

根目录 `.env`、`config` 与资源路径保持原约定。地址、模型和密钥仍使用 `FAST_GATEWAY_BASE_URL`、`FAST_GATEWAY_MODEL`、`FAST_GATEWAY_API_KEY`，不在模块内另建凭据。

在仓库根目录执行 `python -m pytest backend/tests` 可运行行为与架构检查；模块 1～3 的独立入口仍位于 `scripts/checks`。验证前以项目虚拟环境解释器运行，真实模型与 mock/stub 结果分别记录。
