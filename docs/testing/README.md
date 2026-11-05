# 测试与质量检查

项目区分代码质量检查、mock/stub 回归和真实模型验证。交流和新增测试说明默认使用中文。完整开发约定见[工程规范](../development/engineering-standards.md)与[贡献指南](../../CONTRIBUTING.md)。

## 统一入口

在项目根目录执行：

```bash
uv sync --frozen --extra dev
uv run --frozen --extra dev python scripts/checks/quality_gate.py
uv run --frozen --extra dev python scripts/checks/quality_gate.py --scope tests
```

质量门禁检查 Ruff lint、格式、选定范围的类型和模块架构。它不启动独立服务，不请求真实模型。具体子检查和选项可查看：

```bash
uv run --frozen --extra dev python scripts/checks/quality_gate.py --help
```

`pyproject.toml` 设置 `pythonpath = ["backend"]` 和 `testpaths = ["backend/tests"]`，通常不需要手动设置 `PYTHONPATH`。已安装全部开发依赖时，也可直接使用当前虚拟环境中的 Python 运行同一脚本；可复现安装以锁文件为准。

格式调整不是只读检查，需要时主动执行并审查差异：

```bash
uv run --frozen --extra dev ruff format backend scripts/checks
```

## 检查层次与证据

| 层次 | 主要位置 | 验证范围 |
| --- | --- | --- |
| 静态质量 | `scripts/checks/quality_gate.py`、`pyproject.toml` | 语法风格、格式、渐进类型检查、模块导入与兼容边界 |
| 纯规则与工具 | `test_review_domain.py`、`test_narrative.py` | 审核决定、错误映射、章节/人物/场景等处理规则 |
| 配置与 Provider 契约 | `test_config.py`、`test_*provider*.py`、`test_model_env_refs.py` | 环境引用、配置错误、结构化响应和供应商边界；具体网络替身由测试定义 |
| 应用与 API | `test_api.py`、`test_workflow_service.py` | 权限、项目隔离、版本、SSE、审核暂停与恢复 |
| 完整 mock 流程 | `test_pipeline_api.py` | HTTP 入口至媒体导出、审核关卡和状态流转 |
| 模块检查脚本 | `scripts/checks/module1_config_llm.py` 至 `module3_characters_scenes.py` | 可独立运行的模块验证；默认真实模式与显式离线模式分开 |
| 独立 smoke | `quality_gate.py --scope smoke` 调用 `scripts/smoke_pipeline.py` | 在隔离环境中执行 mock 全流程；不作为真实生成质量证据 |

mock 媒体仍会通过 FFmpeg 写出 PNG、MP4、WAV，因此完整回归需要 FFmpeg 和 ffprobe。测试通过证明对应契约与样例流程，不能证明真实供应商可用、人物一致性准确或任意崩溃都可恢复。

需要单独执行完整离线 smoke 时使用：

```bash
uv run --frozen --extra dev python scripts/checks/quality_gate.py --scope smoke
```

旧 `scripts/smoke_pipeline.py` 直接执行时可能继承已有模型、数据库和存储覆盖，且保留产物；共享入口会强制 mock、隔离数据库/存储/临时目录，并在结束时清理，因此本地和 CI 均推荐共享入口。

## 隔离、模式与清理

`backend/tests/conftest.py` 的应用 fixture 使用临时 SQLite 和存储目录，设置测试环境、mock Provider 及非敏感假地址/模型名，并清理配置缓存。新增应用测试复用这些 fixture；专门测试环境或 Provider 的用例应自己明确替身和隔离方式。

- 默认自动检查不依赖开发机密钥，不连接真实供应商。不能仅凭环境名叫 `test` 就假定所有自建脚本都已隔离。
- 不依赖 mock 的具体文案；优先断言结构、数量关系、版本、状态、文件存在和错误边界。
- 工作流测试通过入口推进到所需关卡，不绕过前置条件构造不存在的业务状态。
- 使用 `wait=true` 的用例等待目标任务完成；SSE 使用专门断言。不要通过随意睡眠掩盖未等待的任务。
- 测试只管理自己创建的资源。网页测试先确认单实例，结束及异常时关闭自己启动的进程；不要停止已有服务。
- 模块 2、3 默认在独立沙箱中运行并清理。需要保留证据时使用脚本明确提供的报告/保留选项，先查看 `--help`。

## 模块 1～3

这些检查不需要启动网页服务。离线验证：

```bash
uv run --frozen --extra dev python scripts/checks/module1_config_llm.py --offline
uv run --frozen --extra dev python scripts/checks/module2_script_agent.py --offline
uv run --frozen --extra dev python scripts/checks/module3_characters_scenes.py --offline
```

模块 1 的 `--offline` 跳过真实探针，其余本地配置检查仍按脚本规则执行；模块 2、3 用 mock/stub 验证相应边界。

真实验证使用以下命令，会访问供应商并可能产生费用：

```bash
uv run --frozen --extra dev python scripts/checks/module1_config_llm.py
uv run --frozen --extra dev python scripts/checks/module2_script_agent.py
uv run --frozen --extra dev python scripts/checks/module3_characters_scenes.py
```

三个脚本自动读取项目根 `.env` 中的地址、模型和密钥，无需命令行传密钥。已有进程环境变量优先于 `.env`，因此记录验证配置时应说明是否存在覆盖。模块 3 使用 mock 上游剧本，目标人物/场景 Agent 在真实模式下访问供应商；不能将它描述为全部上游也已真实验证。

真实报告至少记录模式、供应商/模型、样例范围、通过/失败项、耗时和来源证据。人物或场景数量是结构结果，不是准确率。公开日志和报告必须脱敏。

## 持续检查

GitHub Actions 安装锁定依赖后运行统一门禁、完整 pytest、Schema 一致性和离线 smoke；Docker 另做构建和健康探测，临时容器在失败时也清理。Windows 安装器构建及 selftest 仅手动触发。

GitHub 的 `main`、`master` push、PR 和手动触发配置不等于 Gitee 已启用 CI。实际托管平台需要配置 runner、相同检查命令和合并条件，并保留运行记录。Docker/Windows 的完整锁定安装还需独立改造和验收。

类型检查采用渐进范围，以 `pyproject.toml` 中的配置为准；当前不代表整个应用已达到严格类型检查。需要扩大范围时，先解决真实类型问题，不能通过全局忽略错误使检查变绿。

## 修改后的验证选择

```bash
# 针对性的回归
uv run --frozen --extra dev python -m pytest backend/tests/test_api.py
uv run --frozen --extra dev python -m pytest backend/tests/test_modular_architecture.py

# 结构化模型变更：导出后检查已提交 Schema 差异
uv run --frozen --extra dev python scripts/export_schemas.py
git diff --exit-code -- config/schemas

# 有需要时查看覆盖率，优先审查关键失败分支
uv run --frozen --extra dev python -m pytest --cov=app --cov-report=term-missing
```

行为变更添加能暴露该问题的回归。注释和格式变更不增加重复实现的测试，可结合现有回归及去除文档字符串后的执行结构对照。完成相关检查后，不在没有新改动或未解决疑点时反复运行昂贵测试。

## 需要保持的回归边界

- 工作流游标：JSON 状态变更后重新赋值，保证 ORM 能持久化检查点。
- Provider 查询：使用 Agent 实际 capability，而非任意模型配置字段。
- 兼容入口：配置缓存、Session、Base、注册表保持同一对象，不产生两套全局状态。
- 审核：明确 pending 校验、重复审核错误和当前版本语义；完整版本快照另作行为改造。
- 资源：FFmpeg 不可用时给出明确失败，不静默跳过媒体验证。
- 环境：设置或修改进程级环境、缓存和 engine 的测试应负责恢复，避免影响后续用例。

## 默认真实模式联调

当前前端默认连接真实项目，`/?mode=demo` 才进入内存示例。新建、编辑、审核的浏览器实测与后端回读结果见[2026-11-05 联调记录](frontend-live-2026-11-05.md)。

## 模块2剧本工作区扩展

手写、导入、版本恢复、AI润色/续写使用 `scripts/checks/module2_script_workspace.py`。默认离线，`--live`显式读取既有YAML/.env并执行两次有界模型请求，不启动服务、不写正式数据。原 `module2_script_agent.py` 保持原8组解析检查，扩展检查独立10组。

```bash
uv run --frozen --extra dev python scripts/checks/module2_script_workspace.py --offline
uv run --frozen --extra dev python scripts/checks/module2_script_workspace.py --live --report-json /tmp/script-workspace.json
```

接口、正文与追加语义、工作流旧基线保护见[实现说明](../development/script-workspace.md)。

后续保存状态、移动端、真实 409 冲突、导入重试、真实 AI 与 DOCX 表格保真复核见[2026-11-05 剧本工作区交互验收](script-ux-iteration-2026-11-05.md)。该轮全量后端 229 项、前端 44 项通过；模块四仍暂停，前端预留不代表真实导演历史接口已经完成。

继续迭代的专注写作、弹窗焦点生命周期、2px 焦点线、66px 手机保存栏与面板键盘往返，见[2026-11-05 写作体验验收](script-writing-refinement-2026-11-05.md)。该轮前端 50 项、架构边界 16 项、静态资源 3 项通过；未重复调用模型或写入已有项目。

全局概览、键盘搜索、手机首屏和只读故事预览的后续迭代见[2026-11-05 概览与导航验收](overview-navigation-2026-11-05.md)：前端 58 项通过，既有 6 个项目数据指纹保持一致；剧本编辑流程与模块四未改。

项目库、素材分类和连续详情浏览的三轮实测见[2026-11-05 项目与素材库验收](project-asset-libraries-2026-11-05.md)：前端 74 项通过，保存三轮前后截图、失败操作定位和可见鼠标复测；本轮没有业务写入或模型调用。

## 模块四：导演、分镜与第二轮审核

范围按用户确认，见[模块交付对照](../development/module-delivery-map.md)。检查入口：

```bash
uv run --frozen --extra dev python scripts/checks/module4_directing_storyboard.py --offline
uv run --frozen --extra dev python scripts/checks/module4_directing_storyboard.py --max-tokens 4096 --timeout 150 --report-json /tmp/module4-live.json
```

默认真实目标为导演／分镜，上游采用 mock 夹具，关闭额外精化且停在第二审核，不生成媒体。离线及真实各 13/13；完整真实网页闭环、297 项后端／107 项前端结果、首次传输失败及重试修复见[模块四验收](module4-workspace-2026-11-05.md)。
