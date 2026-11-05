# HTTP 适配器收束：完整 OpenAPI 对照

- 日期：2026 年 11 月 5 日。
- 基线：`0a2060d5196f257579f9f707f67c7b5f96b97251`，即已提交的 workspace 版本。
- 当前对象：该提交之后、尚未提交的 HTTP 适配器与所属模块查询改动。
- 抓取前后 571 个源码、成员清单和锁文件的指纹均为 `4ea5e02523ba0ca0d2f39f328ecb94045f93cc7674de2177ca6647d3572668dd`。
- 机器可读证据：[api-boundaries-2026-11-05.json](api-boundaries-2026-11-05.json)。

## 精确对照

基线由 `git archive` 提取到临时目录，在独立进程中优先导入归档内各成员的 `src`；当前版本在另一个临时工作目录中直接导入已安装的 workspace，没有 `PYTHONPATH` 覆盖。两个进程都校验了所有已加载 `studio_` 模块确实来自对应源码树，避免旧版本检查意外使用当前安装包。

调用 `create_app().openapi()` 后逐项比较完整 JSON，结果为：

| 范围 | 基线 | 当前 | 差异 |
| --- | --- | --- | --- |
| 路径数量 | 71 | 71 | 0 |
| Schema 组件数量 | 20 | 20 | 0 |
| 完整 OpenAPI JSON | 相同 | 相同 | 0 |

两份完整文档的 SHA-256 都是 `a5d1f11ddc752fafd698198f6d3befc9dab99941f2c8db8dcc514e812a09d41e`。未规范模块名、未删除组件或忽略任何字段；本次 HTTP 边界收束没有改变 OpenAPI 中的路径、方法、参数、请求体、响应声明、错误响应 Schema 或操作标识。

对照进程使用 test 环境、mock Provider、实际存在的空临时 `APP_ENV_FILE` 和临时数据路径；禁止 socket 连接及绑定，实际调用数为 0。未执行应用 lifespan、启动服务器或创建数据库，临时目录已清理。

## 动态错误与顺序回归

OpenAPI 本身不能证明所有动态错误文本和返回值。为本批读取迁移新增了 `backend/tests/test_api_owned_queries.py`，实际执行 13 项通过，并覆盖：

- 未知人物、场景、镜头、审核和任务先返回原有 404 与对应 `details`，随后才可能进入项目授权。
- 已存在实体仍要求项目访问权限，跨用户访问返回 403。
- 导演、分镜和剪辑版本保持倒序，仅返回当前项目记录。
- SSE 先回放已有事件，再输出完成/失败/取消的终态标记；不在终态继续等待。
- SSE 轮询时任务已删除，继续沿用超时返回语义，不突然抛出新的 404。

执行命令：`.venv/bin/python -m pytest backend/tests/test_api_owned_queries.py`。结果：`13 passed`，另有一条第三方 Starlette TestClient 弃用提醒。现有 API、导演/分镜工作区、工作流、完整 Pipeline API 与剧本基线聚焦回归另有 69 项通过；整体验收以主进程统一门禁结果为准。

本报告只记录 HTTP 契约对照及本批相关行为回归，没有重复数据库元数据、wheel 安装、容器或 Windows 交付验收。
