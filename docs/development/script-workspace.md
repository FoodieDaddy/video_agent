# 剧本工作区：手动创作、导入、AI编辑与版本

本次将模块2从“小说解析结果查看”扩展为可独立工作的剧本编辑模块。沿用原生前端、现有script Agent和Provider，不接入新框架，不新增数据库列或智能体ID。

## 网页操作

进入项目的“剧本”页即可：

1. 没有剧本时，填写标题和正文，直接保存第一版；不要求上传小说，不调用模型。
2. 导入已有TXT、Markdown、JSON或DOCX剧本。导入直接产生新版本，不走小说切章或模型解析。
3. 编辑正文后保存为新版本；历史版本始终保留，可只读预览或复制恢复为新的最新版本。
4. 在已保存的当前稿上选择“润色现稿”或“接着续写”，填写可选创作要求，确认后提交独立AI任务。
5. 需要小说改编时，使用下方独立的小说原文区域上传/导入/解析。已有剧本时仍保留重新解析入口。

未保存草稿保存在当前标签页的sessionStorage，按模式、API根地址、开发身份与项目隔离。刷新可恢复草稿；保存或后台生成期间继续输入的内容不会被返回结果覆盖。版本冲突时保留草稿，用户核对最新稿后明确处理。

旧历史稿没有正文时，不拿梗概冒充全文；页面保留元信息并要求先补正文。导入和人工写作不产生虚构的模型出处。

## 正文与AI契约

`Script.content.script_text` 是正文的持久化位置，API同时在顶层返回 `script_text`。结构化事件、对白和章节摘要与正文分别显示。人工更改正文且未提供新结构时清除旧衍生结构，标为 `needs_analysis`，避免将旧事件当作新稿事实。

正文编辑表单不暴露genre/tone；保存时未显式提供这两个字段，会保留基线或已提供结构中的值，初稿类型默认取项目类型。AI省略一句话故事、梗概、类型或基调时保留原值，避免只改正文却丢掉已有元信息。

script Agent继续使用同一执行ID，新增三种操作：

| operation | 输入 | Agent输出正文 | 应用保存 |
| --- | --- | --- | --- |
| analyze | 小说章节 | 模型正文；旧兼容输出缺正文时从结构化摘要/事件/对白整理草稿 | 新Script与所属StoryEvent |
| polish | 已保存完整正文、结构上下文、创作要求 | 完整润色稿，不能为空 | 新版本，原稿保留 |
| continue | 已保存完整正文、结构上下文、续写要求 | 仅新增片段，不能为空或回显整稿 | 原稿逐字保留 + 两个换行 + 新片段，保存新版本 |

现稿全文进入提示词，不使用固定字符截断；供应商上下文和HTTP超时仍是实际运行限制。润色不保证内容质量或事实正确，生成后须由创作者检查。模型、提示词和重试参数仍由现有配置驱动。

## 新接口

| 方法与路径 | 用途 |
| --- | --- |
| POST `/api/v1/projects/{id}/scripts` | 手动新建/另存版本 |
| POST `/api/v1/projects/{id}/scripts/import` | multipart剧本文件导入 |
| GET `/api/v1/projects/{id}/scripts` | 历史版本摘要，增加workspace_meta来源信息 |
| GET `/api/v1/scripts/{script_id}` | 指定版本完整内容 |
| POST `/api/v1/projects/{id}/scripts/{script_id}/restore` | 复制历史稿为新版本 |
| POST `/api/v1/projects/{id}/scripts/assist` | 排队润色/续写；返回任务体，`wait=true`可等待首个结果 |

手动保存体使用 `title/logline/synopsis/script_text/base_script_id`。已有剧本时保存、导入、恢复都必须提供最新 `base_script_id`，过期返回409；AI请求使用 `operation/base_script_id/instruction`。HTTP202仅代表任务已接受，实际结果查看 `task.status/error/result`。

所有写入口校验项目编辑权限。新接口新增版本且 `approved=False`；旧 `PATCH /scripts/{id}` 保留原位更新行为供兼容调用方，新工作区不用它保存正文。不要将旧PATCH称为不可变版本接口。

文件最多2MiB，正文最多200000字符且UTF-8不超过2MiB。TXT/MD/JSON使用UTF-8或BOM；DOCX按顺序读取正文段落、表格及嵌套表格，保留角色和对白文本，合并单元格去除重复来源，不处理OCR或保留Word版式；解压后大小/目录数量也有限制。JSON可用 `title/script_text/...` 的结构，或同项目API导出体；旧ID、批准状态和模型出处不会沿用。

上述完整文件解析属于真实后端。DEMO仅在内存读取TXT、MD及顶层含script_text的JSON，不解析DOCX，也不把AI模拟任务当成真实正文输出。

## 工作流与并发边界

新工作流遇到已保存的手写、导入或AI修订稿时，复用该稿，不重新调用小说解析。独立“解析小说”任务仍会重新生成新版本。

保存新稿不会自动重建人物、场景、分镜和媒体，也不会暗中撤销历史批准。需要重新核对后续产物。流程保存剧本基线ID/内容指纹，恢复和关联审核批准前核对；新稿或旧PATCH原位改文都会阻止旧流程继续批准。已记录script_id但缺少指纹的旧流程要求取消后重新开始；没有script输出的流程保持兼容。

应用在AI前后检查版本和内容快照，发生冲突不创建AI结果版本。最终冲突在写Script前发生时，任务派发层单独提交已完成模型的审计/预算，再记录失败；其他异常沿用现有外层回滚。模型费用不能随数据库回滚撤销。

版本号分配仍没有数据库唯一约束或分布式锁，SQLite模型等待可能持有写事务。本轮的基线检查不能被描述为任意并发场景下的完整事务治理。

## 验证

保持原模块2检查脚本，新增工作区扩展检查：

```bash
# 默认离线，独立沙箱，禁止HTTP请求
uv run --frozen --extra dev python scripts/checks/module2_script_workspace.py --offline

# 使用现有YAML/.env，真实润色和续写各一次，可能计费
uv run --frozen --extra dev python scripts/checks/module2_script_workspace.py --live --report-json /tmp/script-workspace.json

# 自动回归
uv run --frozen --extra dev python scripts/checks/quality_gate.py --scope all --scope tests
node --test web/tests/*.test.mjs
```

扩展检查复用原模块2的沙箱和脱敏机制，不访问正式数据，也不启动第二个应用实例。真实模式限定一个候选、一次尝试、最多2048输出token；所有上限只在检查进程内设置，不修改正式YAML。
