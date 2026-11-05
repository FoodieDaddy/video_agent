# 第二轮：应用组合边界重构

## 本轮目标

将 FastAPI 应用入口从“所有事情都在 main.py”调整为清晰的组合根：

- `app.main`：创建 FastAPI、注册中间件/异常处理、挂载路由与静态控制台。
- `app.bootstrap.lifespan`：管理 Agent 注册、Runtime、数据库引擎/Schema、配置一致性以及关闭清理。
- `app.api.routes.system`：承载健康检查与本地媒体读取 HTTP 接口。
- `app.api.router`：继续聚合版本化业务 API。

## 变更文件

- 新增 `backend/app/bootstrap/lifespan.py`
- 新增 `backend/app/api/routes/system.py`
- 重构 `backend/app/main.py`
- 新增本说明文档

## 兼容性

- 保持 `app.main:app` 与 `create_app(settings)` 入口。
- 保持 `/health`、`/media/{storage_key:path}`、`/api/v1/**` URL。
- 保持启动顺序：Agent 注册 → Runtime 构建/注册 → 数据库引擎与 Schema → 配置一致性检查。
- 保持关闭顺序：任务 Runner 清理 → Runtime 重置 → Engine 释放。
- 系统媒体路由通过 `request.app.state.runtime` 获取当前应用 Runtime，避免在路由模块导入时捕获运行时单例。

## 设计边界

本轮仍是模块化单体，不引入微服务，不改变业务模块、ORM 映射、数据结构或前端 API 契约。`create_all()` 仍只负责创建缺失表，尚未替代正式数据库迁移；长事务、后台任务可靠性、媒体授权与对象存储迁移也不属于本轮已完成内容。

## 验证

已执行并通过：

- `python -m pytest backend/tests/test_api.py backend/tests/test_modular_architecture.py -q`
- `npm test -- --run`（web 目录，107 项）

全量后端测试尚未完成：`test_module2_checks.py` 的子进程集成用例在当前执行环境访问 `tests.invalid` 时出现 ConnectError/ConnectTimeout；排除该测试后全量运行超过执行时限。不能据此宣称全量后端回归通过。
