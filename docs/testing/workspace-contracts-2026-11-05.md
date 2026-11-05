# workspace 迁移契约独立对照

- 日期：2026 年 11 月 5 日。
- 迁移前基线：`520282fdbf43b75ca7614e10b3f192896f40dd15`，通过 `git archive` 提取到临时目录。
- 对照对象：当前已安装 workspace 的未提交工作区；执行时 HEAD 仍为上述基线，不能将本报告表述为新提交的验收。
- 源码快照：569 个 Python 源码、成员清单与锁文件；抓取前后 SHA-256 均为 `5f3629efe20e5b158be6a9016e41e1dd2750494b78217417b4366f47a140671a`，抓取过程中未变化。
- 机器可读证据：[workspace-contracts-2026-11-05.json](workspace-contracts-2026-11-05.json)。

## 执行方式与隔离

基线和当前版本分别在全新进程及临时工作目录中构建 `create_app()` 并生成完整 OpenAPI。基线使用明确指向归档 `backend/app` 的 namespace，防止当前已安装的兼容 `app` 包遮蔽基线源码；当前版本直接导入已安装的 `studio_api`，不注入 `PYTHONPATH`。

两个进程均使用 `APP_ENV=test`、`AGENT_MODEL_PROVIDER=mock`、实际存在的空临时 `APP_ENV_FILE`、临时数据库地址与存储目录。仅导入并注册 ORM 映射，未执行 lifespan、未创建数据库、未启动服务器。检查进程主动禁止 socket `connect`、`bind` 和 `create_connection`，实际调用数为 0。未读取本地 `.env`，报告未包含凭据。临时归档及数据目录在完成后删除。

## HTTP 与 ORM 对照结果

| 对照范围 | 结果 |
| --- | --- |
| 完整 OpenAPI 文档 | 完全一致；71 个路径、20 个 Schema 组件，差异 0 项 |
| OpenAPI SHA-256 | `a5d1f11ddc752fafd698198f6d3befc9dab99941f2c8db8dcc514e812a09d41e`，基线与当前相同 |
| ORM 表数 | 基线和当前均为 39 张 |
| ORM 原始签名 | 156 处差异，全部为 Python 默认值/更新时间 callable 的 `__module__` 路径迁移 |
| ORM 业务签名 | 仅规范 callable 的模块名前缀后完全一致；剩余差异 0 项 |
| 规范后 ORM SHA-256 | `af4a727f6d93eb92f7ac1d9e41fe0a4aa28b46dcc2cb11bcc7a122beeae6d042`，基线与当前相同 |

ORM 签名覆盖表名、列及顺序、类型、可空性、主键、唯一标记、索引标记、自增、默认值、更新时间、服务端默认值、列注释、约束、外键选项和索引表达式。callable 默认值还比较字节码、常量、闭包及默认参数，未仅按函数名判断。

唯一允许的非业务差异是 `app.modules.platform.*` 改为 `studio_platform.*` 的 Python 模块路径。例如 ID 默认值的 `app.modules.platform.persistence.base` 改为 `studio_platform.persistence.base`，更新时间的 `app.modules.platform.ids` 改为 `studio_platform.ids`。未忽略实际默认值或数据库字段；完整 156 处差异保存在 JSON 中。

## workspace 与方案对应关系

当前有一个应用包与十二个模块包，合计 13 个 workspace 成员，均使用 `src` 布局，并共同使用根目录的 `uv.lock`。

| 方案角色 | 当前成员 |
| --- | --- |
| 应用与组合根 | `apps/studio_api` |
| 项目与权限 | `packages/studio_projects` |
| 文档、章节与剧本 | `packages/studio_story` |
| 人物 | `packages/studio_characters` |
| 场景 | `packages/studio_scenes` |
| 制作 | `packages/studio_production` |
| 审核 | `packages/studio_reviews` |
| 工作流 | `packages/studio_workflow` |
| 资产 | `packages/studio_assets` |
| 配置账本 | `packages/studio_configuration` |
| AI 执行机制 | `packages/studio_ai_runtime` |
| 技术平台 | `packages/studio_platform` |
| 跨模块契约 | `packages/studio_contracts` |

成员清单与方案完全对应，无缺失或额外模块。声明的内部包依赖无循环；所有内部版本约束包含实际版本。扫描 canonical 包源码中的绝对导入和常量形式动态导入，未发现使用了未声明的其他 workspace 包。

## 证据边界

本对照证明当前 workspace 迁移保持完整 HTTP Schema 与数据库元数据契约，并满足本次检查覆盖的包数量、布局和依赖声明。它没有启动应用生命周期或执行模型、数据库读写、容器及 Windows 安装；相应运行与交付证据由其他专项验收提供。
