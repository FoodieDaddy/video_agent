# 前端接口与演示资料约定

当前工作台采用原生浏览器 ES module，无需 Node 构建或 npm 安装。页面从 `web/api.js` 读取接口，从 `web/demo-data.js` 获取纯内存示例。模块本身不挂载 DOM，不启动后台任务，也不在导入时请求服务。

## 模式、连接与身份

```js
import studioApi, { createStudioApi, ApiError, resolveMode } from "/api.js";

// 默认连接真实项目；仅 ?mode=demo 或显式 mode:'demo' 使用演示资料。
const connection = studioApi.getConnection();
// { mode: "live", isDemo: false, baseUrl: "/api/v1",
//   userId: "user_demo", userRole: "admin" }

// 导入、创建实例或切换连接本身均不请求后端；调用读取方法才发出请求。
const projects = await studioApi.getProjects();

const previewApi = createStudioApi({ mode: "demo" });
const previewProjects = await previewApi.getProjects(); // 仅当前实例内存中的示例
```

命名导出为 `createStudioApi`、`studioApi`、`ApiError`、`resolveMode`；默认导出也是 `studioApi`。`createStudioApi({ mode, baseUrl, userId, userRole, fetch })` 可创建独立实例。`fetch` 用于测试替身；正常页面无需传入。

页面与接口层共用 `resolveMode(search)` 解析 URL 模式。省略 `search` 时读取当前 `location.search`；没有浏览器 `location` 时按空查询处理。只有精确的 `?mode=demo` 返回 `demo`；无参数、`?mode=live`、空值或未知查询值均返回 `live`，不会隐式切到演示。页面直接调用 `createStudioApi()` 即可，不应另写一套默认模式逻辑。

显式 `createStudioApi({mode})` 或 `configure({mode})` 的配置优先于 URL，且只接受 `demo/live`；非法值抛出 `ApiError(code="invalid_mode")`，失败配置不改变现有连接。这与 URL 的宽容解析有意区分：地址中的未知查询值回到真实模式，而主动提交的错误配置需要被纠正。后续 `configure()` 不传 `mode` 时保留当前模式。

- `mode` 与 `isDemo` 是只读属性，修改连接使用 `configure()`。连接仅保存在内存，刷新页面后恢复默认值或 URL 指定的模式。
- `baseUrl` 接受 `/api/v1` 之类的同源绝对路径，或完整 HTTP(S) API 根地址。仅传 `https://example.com` 时补 `/api/v1`；已有路径原样保留。地址不接受用户名、密码、查询参数或片段。跨域部署还需要后端自行配置 CORS；适配层不会绕过浏览器限制。
- 请求统一设置 `Accept`，JSON 请求由适配层设置 `Content-Type`。文件上传使用 `FormData`，由浏览器设置 multipart 边界。
- 发送 `X-User-Role`，对非空且不是 `user_demo` 的身份发送 `X-User-Id`。这是当前后端开发鉴权的实际约定：省略默认用户 ID 才能使用开发模式默认管理员。该约定不能作为生产身份认证方案。
- 本适配器不读取 `.env`，不接收供应商密钥，也不把连接、配置或密钥写入 `localStorage`。供应商密钥继续由服务端 `.env` 管理。管理接口中的 `has_api_key` 仅表示配置存在，不证明供应商可用。
- live 请求失败不会自动换成演示数据。UI 应显示明确错误，并让用户主动切换模式。

## 真实生成的确认约定

live 下的工作流启动、恢复、各制作阶段、人物图片、镜头生成都要求最后一个参数 `options.confirmed === true`。审核如果显式请求 `resume_workflow: true`，也要求该标记。缺失时抛出 `ApiError`，`code` 为 `confirmation_required`，**不会发出请求**。

页面必须先由用户点击生成按钮，再显示包含项目、操作、真实供应商调用提示的确认界面；只有用户确认后才传入此标记。读取页面、切换项目、切换到 live 模式、编辑配置、导入原文均不能自动执行生成。`confirmed` 是避免演示误触的前端契约，服务端仍负责鉴权和执行控制。

```js
// UI 完成二次确认后调用；切勿在页面初始化时自动执行。
await studioApi.startWorkflow(projectId, {}, { confirmed: true, signal });
await studioApi.runStage(projectId, "storyboard", {}, { confirmed: true, signal });

// 默认只保存审核结果，不续跑，不调用模型。
await studioApi.decideReview(reviewId, { status: "approved", comment: "节奏通过" });
// 若 UI 明确提供“通过并继续”，需另一次确认，并显式请求续跑。
await studioApi.decideReview(reviewId,
  { status: "approved", resume_workflow: true },
  { confirmed: true });
```

演示操作只改变当前实例的内存资料，任务会标记 `demo/simulated`，不会产生真实模型结果。新建演示项目默认没有剧本、人物、场景、分镜；导入样例仅加入原文和章节，不伪造生成产物。`resetDemo()` 可重置当前演示实例。

## Workspace 聚合结构

`getWorkspace(projectId, options)` 返回：

```js
{
  project,                  // 项目对象
  dashboard,                // 保留后端原始 dashboard 对象
  summary, workflow, pending_reviews, tasks,
  script,                   // 尚未生成时为 null
  characters: [], scenes: [], shots: [], assets: [], reviews: [],
  directing, storyboard,    // 产物对象，尚未生成时为 null
  editing, evaluation,
  documents: [], chapters: [],
  activities: [], agentCatalog: [], demo: false
}
```

live 先读取 `/projects/{id}/dashboard` 验证项目存在和访问权限，再并行读取剧本、人物、场景、镜头、素材、审核、导演计划、分镜、原文与章节。`dashboard` 保留后端原始字段，含 `project/summary/workflow/pending_reviews/tasks/editing/film/evaluation`。

只有剧本接口返回 `404 + error.code=not_found + message=该项目还没有剧本`，且 `details.project_id` 与所读项目一致时，转换成 `script: null`。项目不存在、权限失败、未知 URL、网络失败和其他 404 都继续抛出。导演计划、分镜、剪辑、评估没有产物时后端本来就返回 200/null。

live 不补造项目进度、活动记录、人物形象或镜头缩略图。`activities` 与 `agentCatalog` 聚合字段在 live 暂为空；角色页面单独调用 `getAgentCatalog()`；管理员可读取配置，普通成员在配置接口返回 403 时改读 `/meta` 的注册目录。后端尚未提供图片 URL 的人物、场景、镜头应由 UI 显示正常占位，不应把演示图片混入真实数据。素材 URL 来自真实 Asset 的 `url`，不能根据本地路径猜测。

DEMO 的主项目 `demo-rainy-bookstore` 为“雨夜书店”，包含 3 位人物、3 个场景、6 个镜头，人物与场景已确认、分镜审核待处理，示例进度为 0.62。另有“雪线来信”“最后一班渡轮”可切换。所有示例图片为 `data:image/svg+xml` 内联插图，无外部图片请求。

### 演示卡片最小字段

```js
// 人物。live 同类字段来自 profile / appearance_keywords；未提供 image_url 时用占位。
{
  id: "demo-char-lin", name: "林简", status: "approved",
  summary: "32 岁，旧书店继承人。",
  profile: {
    name: "林简", appearance: "短黑发、深色针织衫、旧腕表",
    personality: "内敛、克制、心思细腻",
    visual_keywords: ["短黑发", "深色针织衫"],
    source_facts: ["旧书店继承人"]
  },
  image_url: "data:image/svg+xml;..."
}

// 场景。真实 Scene 响应不保证含 status，审批可参考 approved_version。
{
  id: "demo-scene-shop", name: "旧书店 · 主厅", chapter_index: 1,
  summary: "暖黄台灯、木质书架与玻璃上的雨痕。",
  profile: {
    description: "狭长的老书店，深色木书架围住旧柜台",
    time_of_day: "雨夜", mood: "安静、怀旧、温暖",
    visual_prompt: "旧书店暖光，电影感自然光"
  },
  image_url: "data:image/svg+xml;..."
}

// 分镜。真实 camera 为对象，dialogue 为对象数组，characters 为 ID 数组。
{
  id: "demo-shot-1", order_index: 1,
  description: "雨落在橱窗上，书店的灯还亮着",
  action: "林简在窗后收拾最后一摞书。",
  camera: { shot_size: "远景", movement: "缓慢推进", angle: "平视" },
  duration_seconds: 5, scene_id: "demo-scene-street", characters: [],
  dialogue: [], visual_prompt: "雨夜暖光，低饱和电影质感",
  status: "pending_review", image_url: "data:image/svg+xml;..."
}
```

## 方法目录与端点

所有异步方法的最后一个 `options` 均支持 `signal: AbortSignal`。列表方法解包后端 `{items,count}` 为数组。详情、任务、版本选中等复合响应保留原始结构。以下路径均相对 `baseUrl`，`id` 经过 URL 编码。

| 方法 | live 端点与返回约定 |
| --- | --- |
| `getProjects({limit})` / `createProject(payload)` | GET / POST `/projects`；数组 / Project |
| `getProject(id)` / `updateProject(id,payload)` | GET / PATCH `/projects/{id}`；Project |
| `getDashboard(id)` / `getSummary(id)` | GET 项目下 `/dashboard` / `/summary` |
| `getWorkspace(id)` | 聚合只读请求，结构见上文 |
| `importSample(projectId)` | POST 项目下 `/upload?sample=true`；`{document,chapters}`，不调用模型 |
| `uploadDocument(projectId,file)` | POST 项目下 `/upload`；FormData 字段 `file`；没有文件时前置报错 |
| `parseDocument(projectId,documentId,{wait})` | POST 项目下 `/documents/{documentId}/parse`；后台任务，确定性章节解析 |
| `getDocuments(id)` / `getChapters(id)` | GET 项目下 `/documents` / `/chapters`；数组 |
| `getScript(projectId)` / `getScripts(projectId)` | GET 项目下 `/script` / `/scripts`；可空剧本 / 版本数组 |
| `getScriptVersion(scriptId)` / `updateScript(scriptId,payload)` | GET / PATCH `/scripts/{scriptId}`；Script |
| `createScript(projectId,payload)` | POST 项目下 `/scripts`；新增版本，payload为title/logline/synopsis/script_text/base_script_id |
| `importScript(projectId,file,{base_script_id})` | POST 项目下 `/scripts/import`；multipart，TXT/MD/JSON/DOCX，2MiB |
| `restoreScriptVersion(projectId,scriptId,{base_script_id})` | POST 项目下 `/scripts/{scriptId}/restore`；复制为新版本 |
| `assistScript(projectId,payload,{confirmed,wait})` | POST 项目下 `/scripts/assist`；operation为polish或continue，须传base_script_id，返回任务体 |
| `getCharacters(id)` / `getScenes(id)` / `getShots(id)` | GET 项目下对应集合；数组 |
| `getCharacter(id)` / `updateCharacter(id,payload)` / `approveCharacter(id)` | GET / PATCH `/characters/{id}`；POST `/characters/{id}/approve` |
| `getScene(id)` / `updateScene(id,payload)` / `approveScene(id)` | GET / PATCH `/scenes/{id}`；POST `/scenes/{id}/approve` |
| `getShot(id)` / `updateShot(id,payload)` / `approveShot(id)` | GET / PATCH `/shots/{id}`；POST `/shots/{id}/approve` |
| `getCharacterAssets(id)` / `getAssets(projectId,{kind,limit})` | GET `/characters/{id}/assets` / 项目下 `/assets`；数组 |
| `getDirecting(id)` / `getStoryboard(id)` | GET 项目下 `/directing` / `/storyboards`；`{plan,versions}` / `{board,versions}` |
| `getShotVersions(shotId)` | GET `/shots/{id}/versions`；`{shot_id,selected_video_id,items,count}` |
| `selectShotVersion(shotId,versionId)` | POST `/shots/{id}/versions/{versionId}/select`；`{shot,video}`；versionId 是 VideoGeneration ID |
| `getAudio(id)` / `getEditing(id)` / `getExport(id)` / `getEvaluation(id)` | GET 项目下 `/audio` / `/editing` / `/export` / `/evaluation` |
| `getWorkflows(projectId)` / `getWorkflow(projectId,runId)` | GET 项目下 `/workflows` / `/workflows/{runId}`；数组 / `{run,checkpoints}` |
| `startWorkflow(projectId,payload,{confirmed,wait})` | POST 项目下 `/workflows/start`；任务启动体 |
| `resumeWorkflow(projectId,runId,{confirmed,wait})` / `cancelWorkflow(projectId,runId)` | POST 运行下 `/resume` / `/cancel`；任务启动体 / Run |
| `getTasks(projectId,{limit})` / `getTask(projectId,taskId)` | GET 项目下 `/tasks` / `/tasks/{taskId}`；数组 / `{task,events}` |
| `getTaskEvents(projectId,taskId,{after,limit})` / `cancelTask(projectId,taskId)` | GET 任务下 `/events`；数组。POST `/cancel`；`{task}` |
| `streamTaskEvents(projectId,taskId,{after,timeout,signal})` | 异步迭代 SSE，见下文 |
| `getReviews(projectId,{status})` / `getReview(reviewId)` | GET 项目下 `/reviews` / `/reviews/{id}`；数组 / Review |
| `decideReview(reviewId,payload,{confirmed,wait})` | POST `/reviews/{id}`；`{review,...可能的任务启动体}` |
| `getReviewComments(reviewId)` / `addReviewComment(reviewId,body)` | GET / POST `/reviews/{id}/comments`；数组 / Comment |
| `getMeta()` / `getProjectMeta(projectId)` | GET `/meta` / 项目下 `/meta` |
| `getProviders()` / `getSystemStatus()` / `getWorkflowConfigs()` | GET `/admin/providers` / `/admin/status` / `/admin/workflows` |
| `getAgentCatalog()` / `getAgents()` | 相同的 13 职责目录；live 从 `/admin/model-configs` 聚合 |
| `getAgentConfigs()` / `getAgentConfig(agentId)` | GET `/admin/model-configs` / `/admin/model-configs/{id}` |
| `updateAgentConfig(agentId,payload,{note})` | POST `/admin/model-configs/{id}/versions`，请求体 `{payload,note}`；保存并激活新版本 |
| `getAgentConfigVersions(agentId)` / `rollbackAgentConfig(agentId)` | GET 配置下 `/versions`；数组。POST `/rollback`；返回激活结果 |
| `activateAgentConfigVersion(versionId)` | POST `/admin/model-config-versions/{id}/activate` |
| `resetAgentConfig(agentId)` | DELETE `/admin/model-configs/{id}/override`；恢复服务端 YAML 来源 |
| `runStage(projectId,stage,payload,{confirmed,wait})` | 按下表调用真实存在的阶段路由。当前路由不接收业务请求体，payload 位置保留；兼容第三参直接传 options |
| `generateCharacterImages(id,payload,{confirmed,wait})` | POST `/characters/{id}/generate-images`，payload 可含 `kinds` |
| `generateCharacterViews(id,payload,{confirmed,wait})` | POST `/characters/{id}/generate-views`；后端固定生成 turnaround，payload 位置保留 |
| `generateShot(shotId,{confirmed,wait})` | POST `/shots/{id}/generate` |

`runStage` 的真实路由映射：

| stage | 项目下 POST 路径 |
| --- | --- |
| `script` / `analyze` | `/analyze` |
| `directing` / `director` | `/direct` |
| `storyboard` / `storyboards` | `/storyboards` |
| `video` | `/shots/generate` |
| `audio` | `/audio` |
| `editing` | `/editing` |
| `render` | `/render` |
| `export` | `/export` |
| `evaluation` / `evaluate` | `/evaluate` |

当前后端没有项目级 `/characters/extract`、`/scenes/extract` 或 `/character-assets` 路由，适配层不会创建这些假入口。人物与场景提取由工作流执行；人物图像生成使用人物级方法。

`updateScript` 的输入仍为 `title/logline/synopsis/content/status`，作为旧PATCH兼容入口原位更新。新版正文编辑器使用 `createScript` 追加版本，正文为顶层 `script_text`；完整Script同时返回 `workspace_meta`，历史摘要也提供来源。已有稿件时保存、导入、恢复都须匹配最新基线，409不能自动覆盖草稿。人物、场景和镜头输入沿用原字段。详细规则见[剧本工作区](script-workspace.md)。

`assistScript`在live模式必须显式确认。Task的 `result.script_id/version` 指向成功生成的新版本；失败或仍在运行不等于已生成。DEMO只记录模拟任务，不创建伪造的AI结果版本。未保存正文以sessionStorage草稿保留，发起AI前必须明确保存。

四格式导入的完整解析由live后端执行，JSON同时支持同项目API导出体。DEMO只读TXT、MD和顶层包含script_text的JSON，DOCX会提示改用真实后端；不会伪造Word解析结果。

## 智能体目录

角色卡片为扁平对象：`{id,name,category,description,status,model_id,enabled,agent_ids}`。13 个职责与后端配置 ID 不是一对一：人物设定对应提取、描述、一致性三个配置；场景设定对应提取、描述两个配置；声音设计对应 audio 与 audio_voice。目录可在没有项目时读取。

DEMO 状态为 `demo`；live 配置可读时为 `configured/disabled/unconfigured`，并含 `config_access: true`，只说明已读到启用配置，不能称为在线或健康。普通成员仅在配置接口 403 时改读 `/meta`；状态为 `registered/unregistered`，`config_access: false`，保留职责的 `agent_ids`，以 `registered_agent_ids` 标明已注册实例。此时 `enabled/model_id/provider` 为 null，UI 应说明配置不可读；不能据此推断模型在线。其他错误继续抛出。配置可读时 `model_id` 为职责成员去重后的显示值；没有配置时为 null。

## 错误、任务与事件

`ApiError` 含 `name/message/status/code/details/url`，其中网络失败 `status=0, code=network_error`；服务端业务错误保留原 `code/details`；非 JSON 响应为 `invalid_response`。取消请求保持原始 `AbortError` 或 AbortSignal 的 reason，调用方可据此避免显示失败提示。

生成接口返回的是 `{task_id,status,task}`。即使 HTTP 成功，`task.status` 也可能是 `failed`，或仍为 `pending/running`。即使任务 `succeeded`，`result.failures` 也可能记录局部失败，工作流也可能停在 `awaiting_review`。页面必须同时检查任务状态、错误、结果及工作流状态，不能仅凭 `response.ok`、SSE 的 `end` 或任务 `succeeded` 宣称成片完成。

```js
const controller = new AbortController();
try {
  for await (const item of studioApi.streamTaskEvents(projectId, taskId, {
    signal: controller.signal, after: lastEventId
  })) {
    // item = { event: "task" | "end" | "timeout", data }
    // task 事件的 data 是 TaskEvent，而不是完整 Task。
    if (item.event === "task") lastEventId = item.data.id;
  }
  // 结束后再读取完整任务，判断成功、失败、取消及局部失败。
  const { task } = await studioApi.getTask(projectId, taskId);
} finally {
  controller.abort();
}
```

SSE 使用带身份头的 `fetch`，支持 `after` 事件 ID、`AbortSignal`、跨块 CRLF，退出迭代时取消 reader 并释放锁。默认没有自动轮询、自动重连或常驻计时器；页面切换项目、关闭面板或卸载时应取消正在进行的读取与监听。

## 本地验证

```bash
node --test web/tests/api-contracts.test.mjs
```

测试使用 Node 内置测试框架和替身 fetch，不启动项目服务，不连接外网或模型。覆盖默认真实模式不自动请求、URL 与显式配置模式解析、显式演示零请求、内存读写隔离、真实生成确认、审核默认不续跑、后端字段/端点、空剧本 404 的精确区分、任务失败/局部失败保留、AbortSignal、网络错误、SSE 解析与 reader 释放。Node 需要提供 fetch/Headers/Response/FormData/File/ReadableStream 等 Web API；本次在 Node 26 验证。
