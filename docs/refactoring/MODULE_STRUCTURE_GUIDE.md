# Video Agent 模块结构规范（本轮）

## 1. 目标：模块化单体，而不是微服务

所有业务模块在同一个 FastAPI 进程中运行，共享当前数据库和运行时。
模块边界通过 Python 包、公开接口和架构测试执行。暂不引入网络 RPC、
消息总线、独立数据库或多进程 Agent 调度。

## 2. 业务模块统一目录

```text
app/modules/<module>/
├── domain/                  # 业务规则：Entity、Value Object、Domain Service
├── application/             # Use Case、Command、Query、流程编排
├── infrastructure/          # Repository 实现、ORM 映射适配、Provider/Agent 适配
│   ├── persistence/
│   └── agents/
│       ├── <agent>.py
│       └── catalog.py       # 本模块 Agent 清单
├── interfaces/              # 入站/出站适配器
│   └── http/
├── contracts.py             # 稳定的跨模块数据协议
├── public.py                # 唯一业务模块门面
└── README.md
```

并非每个目录现在都必须有业务代码。空层是约定边界，不代表预先实现了 Repository、
领域事件、HTTP Controller 或其他功能。只有真实需求出现时才填充。

## 3. Java/Spring 概念映射

| Java / Spring | 本项目 Python 对应 | 责任 |
|---|---|---|
| Maven/Gradle module | `app/modules/<module>` | 业务模块边界 |
| Controller | `interfaces/http`；现阶段部分仍在 `app/api/routes` | HTTP 协议适配 |
| DTO | `contracts.py` / `app.schemas`（迁移期） | 输入输出数据结构 |
| Service / UseCase | `application/` | 完成一个业务用例 |
| Entity / Value Object | `domain/` | 核心业务规则和状态 |
| Repository interface | `domain/` 或 `application/ports.py`（按需） | 定义持久化能力 |
| Repository implementation | `infrastructure/persistence/`（逐步迁移） | SQLAlchemy 等技术实现 |
| `@Configuration` / DI | `bootstrap/` | 创建对象并注入依赖 |
| SPI / Plugin | `infrastructure/agents/catalog.py` + `ai_runtime.registry` | 注册模块内 Agent |

Python 没有 Spring 容器。本项目使用显式构造和启动组装，不引入装饰器扫描或隐式魔法。

## 4. Agent 的归属与协作

Agent 是业务模块的基础设施适配器，不是全局业务服务：

- 剧本 Agent 属于 `story/infrastructure/agents`。
- 人物 Agent 属于 `characters/infrastructure/agents`。
- 场景 Agent 属于 `scenes/infrastructure/agents`。
- 导演、分镜、视频、音频、剪辑、评估 Agent 属于 `production/infrastructure/agents`。
- 总控/流程协调 Agent 属于 `workflow/infrastructure/agents`。
- `ai_runtime` 只定义 BaseAgent、上下文/结果、Provider 协议、执行和注册机制，不知道具体业务 Agent 类。

每个模块的 `catalog.py` 声明 `执行 ID -> Agent 类`。`bootstrap/agent_catalog.py`
只负责汇总各模块 catalog、检查重复 ID 并交给 ai_runtime 注册。新增 Agent 的流程：

1. 在所属业务模块新增 Agent 类。
2. 实现 BaseAgent 约定的输入输出和执行方法。
3. 在本模块 `catalog.py` 声明唯一执行 ID。
4. 在本模块测试中验证 Agent 输入、输出、异常和 Provider 能力。
5. 在应用组合测试中验证全局执行 ID 唯一。

Agent 之间不要直接互相实例化或导入对方私有类。跨 Agent 协作由 Application Use Case、
Workflow Handler 或 Orchestrator 通过稳定的执行 ID 和契约完成。Agent 不直接访问数据库，
不持有 FastAPI Request，也不负责事务提交。

## 5. 依赖方向

允许的主方向：

```text
interfaces  ---> application ---> domain
                     |
                     v
              infrastructure adapters

bootstrap ---> 各模块 public/catalog
ai_runtime ---> Agent 基类、Provider 协议和注册机制
```

更准确地说，Application 定义需要什么能力，Infrastructure 提供实现；
由 bootstrap 或 Runtime 将实现组装进用例。Domain 不反向依赖 Application、
Infrastructure、API 或 ORM。

跨业务模块只能依赖对方 `public.py` 或 `contracts.py`。禁止：
`from app.modules.other.application...`、
`from app.modules.other.infrastructure...`、
`from app.modules.other.domain...`。

## 6. 当前兼容边界

本轮没有大规模移动 API 路由、ORM Model、Pydantic Schema 或 service 兼容入口。
这些仍是历史兼容层：
- `app/api/routes`：当前统一 HTTP 路由聚合位置。
- `app/models`：当前 SQLAlchemy 映射的唯一来源。
- `app/schemas`：当前 Pydantic Schema 的唯一来源。
- `app/services`、`app/agents`、`app/providers`、`app/core`：旧导入兼容层。

不得复制第二份 ORM Model 或 Schema。后续迁移时保留旧导入路径作为转发 shim，
直到所有调用方和外部使用者完成迁移。

## 7. 预留项（不在本轮实现）

- Repository 完整抽象与 ORM 隔离。
- 每个模块独立数据库 Schema / 事务边界。
- Celery/Redis、分布式任务、事件总线。
- Agent 动态发现、热插拔和独立进程执行。
- OIDC、复杂 RBAC、多租户。
- OpenTelemetry、Prometheus 等完整观测栈。

这些列入 TODO/技术路线，不作为当前模块结构的前置依赖。
