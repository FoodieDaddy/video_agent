# AI Film Studio 操作手册

本手册面向**日常操作人员**：说明如何启动系统、在控制台里把一部小说做成成片、如何审核、
如何切换模型、如何排障与备份。架构与接口细节不在这里展开，见文末「相关文档」。

适用版本：1.0.0（`config/app.yaml` 中的 `app.version`）。

---

## 1. 五分钟跑通一遍

首次接触时按这个顺序走一遍，能覆盖 80% 的操作路径：

1. 启动服务（第 2 章），浏览器打开 <http://127.0.0.1:8010/>。
2. 左侧输入项目名（例如「雨夜书店」）→ 点 **新建项目**。
3. 点 **导入示例小说**（或用「剧本」页签的 **上传小说** 传自己的文件）。
4. 点 **一键完整流程**，下方「任务与日志」会实时滚动每个阶段。
5. 流程会停在 4 个审核关卡：在「任务与日志」上方的 **待审核** 卡片里点 **通过并继续**
   （也可在「审核」页签处理），直到工作流 `completed`。
6. 在「剪辑」页签看成片，「质量评估」页签看评分，`GET /projects/{id}/export` 拿导出文件。

离线演示可显式设置 `AGENT_MODEL_PROVIDER=mock`，无需 API Key，产出 PNG / MP4 / WAV / SRT。
正常启动使用 `fast_gateway`，程序自动读取项目根目录 `.env` 中的
`FAST_GATEWAY_BASE_URL`、`FAST_GATEWAY_MODEL`、`FAST_GATEWAY_API_KEY`；地址、模型
和密钥配置一次后无需重复输入或手动 export。修改 `.env` 后需重新启动。

---

## 2. 安装与启动

### 2.1 前置条件

| 依赖 | 版本 / 说明 | 是否必需 |
| --- | --- | --- |
| Python | 3.11+（推荐 3.12）；用 `install.exe` 安装时**无需自备** | 必需 |
| FFmpeg / ffprobe | 合成、时长探测、字幕烧录 | 必需（缺失时只能生成时间线） |
| Docker | 使用容器方式启动时 | 可选 |
| 模型 API Key | 只有切换到真实 provider 时才需要 | 可选 |

FFmpeg 安装（Windows）：

```powershell
winget install Gyan.FFmpeg
ffmpeg -version
ffprobe -version
```

若装在非 PATH 目录，用 `FFMPEG_BIN` / `FFPROBE_BIN` 指定绝对路径即可；
程序也会尝试 `C:/ffmpeg/bin`、`D:/ffmpeg/bin`、`~/ffmpeg/bin`、`/usr/local/bin`、`/opt/homebrew/bin`。

### 2.2 Windows 一键安装（install.exe）

不想碰命令行时，用发行包里的两个 exe：

| 文件 | 作用 |
| --- | --- |
| `install.exe` | 一键部署：本机没有 Python 3.11+ 时自动下载并安装一份私有副本，自动 `pip` 安装依赖，写启动脚本、桌面/开始菜单快捷方式，并在注册表登记卸载项 |
| `uninstall.exe` | 卸载：停掉正在运行的服务，删除快捷方式、注册表项、虚拟环境与应用文件；默认**保留**用户数据，加 `--purge` 才连数据一起删 |

操作步骤：

1. 把 `install.exe` 与 `uninstall.exe` 放在同一个文件夹（`install.exe` 会把同目录的卸载程序复制进安装目录）。
2. 双击 `install.exe`，等它跑完（首次约 2～5 分钟，取决于网速），成功后浏览器会自动打开控制台。
3. 之后从桌面快捷方式 **AI Film Studio** 启动；关闭控制台窗口或按 `Ctrl+C` 即停止。
4. 卸载：`开始菜单 → AI Film Studio → Uninstall AI Film Studio`，或 `设置 → 应用 → AI Film Studio`，
   或直接双击安装目录里的 `uninstall.exe`（需要输入 `YES` 确认）。

默认安装到 `%LOCALAPPDATA%\AIFilmStudio`：

```
%LOCALAPPDATA%\AIFilmStudio\
  app\               应用（backend + web + config）
  venv\              独立虚拟环境，依赖都装在这里
  python\            仅当本机没有 3.11+ 时才会出现的私有 Python 副本
  data\              SQLite 数据库、上传、生成媒体（卸载时保留）
  start-studio.cmd   快捷方式指向的启动脚本（写入了端口与 APP_ENV）
  install.json       安装清单：版本、端口、路径
  studio.ico
  uninstall.exe
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--dir <路径>` | 换安装目录 |
| `--port <端口>` | 显式选择 HTTP 端口；默认 8010，占用时报错并要求先处理已有实例 |
| `--extras s3,pdf` | 额外安装可选依赖（可选值见 `pyproject.toml` 的 `optional-dependencies`） |
| `--python <路径>` | 指定用哪个 Python 建虚拟环境 |
| `--with-ffmpeg` | 尝试用 `winget` 安装 FFmpeg |
| `--no-launch` | 装完不自动启动（脚本化安装/升级时常用） |
| `--no-shortcuts` / `--no-registry` | 不建快捷方式 / 不写卸载注册表项 |
| `--dry-run` | 只打印计划，不改动任何东西 |

- 装到非默认目录后，卸载时也要带同样的 `--dir <路径>`。
- 失败信息会留在窗口里（`Press Enter to close`）；应用依赖使用载荷内 `uv.lock` 冻结同步，uv 引导由 pip 获取，应用包由 uv 获取；网络代理与索引设置需要同时适用于两者。
- 安装器验证完整 workspace，复制所有成员后再安装，启动器通过已安装包运行。FFmpeg 若缺失会在第 7 步给出明确提示。

### 2.3 首次安装（源码方式）

```powershell
cd C:\Users\liumiao\Desktop\video_make\video_agent
python -m pip install uv==0.12.9
uv sync --frozen --extra dev
Copy-Item .env.example .env           # 可选，.env 会被自动读取；不要提交进仓库
```

### 2.4 启动与停止

```powershell
.\.venv\Scripts\python.exe -m uvicorn studio_api.main:app --host 127.0.0.1 --port 8010 --workers 1
```

也可以用桌面启动器：启动前先确认没有已有项目实例，等 `/health` 通了再打开浏览器：

```powershell
.\.venv\Scripts\python.exe backend\app\desktop.py --port 8010
.\.venv\Scripts\python.exe backend\app\desktop.py --port 8010 --no-browser   # 只起服务
```

- 停止：在该终端按 `Ctrl+C`。
- 端口以命令行的 `--port` 为准（`config/app.yaml` 里的 `server.port` 不会自动生效）。
- `--reload` 仅用于开发；生产请固定单 worker（见 11 章）。
- 入口地址：

| 地址 | 用途 |
| --- | --- |
| `/` | 控制台（HTML/CSS/JS，无需构建） |
| `/docs` | Swagger UI，可直接调试所有接口 |
| `/health` | 健康检查，返回 `{"status":"ok","storage":"local"}` |
| `/media/...` | 生成文件的静态访问（本地存储时） |
| `/api/v1/...` | 业务接口前缀 |

### 2.5 启动自检

1. `/health` 返回 200 且 `status=ok`。
2. 控制台右上角徽标显示 **服务正常**，环境标签形如 `development · local · 17 agents`。
3. 打开「模型配置」页签（需 admin 身份），确认：
   - `FFmpeg` 一行显示「可用」；
   - `任务` 一行显示 `inline · 4 workers`；
   - `智能体` 显示 `17/17 启用`。

### 2.6 用 Docker 启动

```powershell
docker compose up --build          # 打开 http://127.0.0.1:8000/
docker compose logs -f api         # 看日志
docker compose down                # 停止，保留数据卷
docker compose down -v             # 停止并清空数据库与生成媒体
```

容器内固定：SQLite 在 `/data/studio.db`、媒体在 `/data/storage`、任务 inline、单 uvicorn worker，
`/data` 挂在命名卷 `studio-data` 上，重建镜像不丢数据。

### 2.7 常用环境变量

配置文件与变量的优先级：`config/app.yaml` < `config/environments/<APP_ENV>.yaml` < 环境变量。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `development` | `development` / `test` / `production` |
| `APP_CONFIG_DIR` | `<repo>/config` | 配置目录 |
| `APP_DATA_DIR` | `<repo>/data` | 数据库、上传、媒体根目录 |
| `DATABASE_URL` | `sqlite:///<data>/studio.db` | 也可指向 PostgreSQL |
| `STORAGE_BACKEND` / `STORAGE_ROOT` | `local` / `<data>/storage` | 也可切 `s3`（需装 `s3` extra） |
| `APP_INLINE_TASKS` | `1` | 任务在同一进程内跑；**目前请保持 1** |
| `APP_MAX_WORKERS` | `4` | 并发任务线程数 |
| `APP_ALLOW_DEV_AUTH` | `1` | 关闭后必须提供 `X-User-Id` 请求头 |
| `APP_DEMO_USER_ID` | `user_demo` | 演示身份 ID |
| `FFMPEG_BIN` / `FFPROBE_BIN` | `ffmpeg` / `ffprobe` | 二进制路径 |
| `FAST_GATEWAY_API_KEY` | 从根目录 `.env` 自动读取 | 默认文字模型供应商凭据 |
| `FAST_GATEWAY_BASE_URL` | 从根目录 `.env` 自动读取 | 默认文字模型供应商接口地址 |
| `FAST_GATEWAY_MODEL` | 从根目录 `.env` 自动读取 | 12 个文字 Agent 共用的模型名 |
| `OPENAI_API_KEY` 等 | 空 | 只在对应 provider 启用后才被读取 |

模型密钥只通过环境变量提供，`config/providers/*.yaml` 里只写**变量名**，不写密钥。

### 2.8 数据落盘位置

| 路径 | 内容 |
| --- | --- |
| `data/studio.db` | SQLite 数据库（业务表与任务/事件表） |
| `data/uploads/` | 上传的原始小说文件 |
| `data/storage/` | 生成资产：人物图、镜头视频、配音、字幕、成片、导出 |
| `config/` | 应用/智能体/provider/工作流/prompt/schema 配置 |
| `samples/novel_sample.txt` | 「导入示例」使用的样例小说 |

---

## 3. 控制台使用

### 3.1 界面结构

```
顶部栏：环境标签 · 健康状态 · 开发者身份(X-User-Id) · 角色(X-User-Role)
├─ 左栏：项目列表（新建 / 刷新 / 选择项目）
└─ 中栏
   ├─ 项目首页 Dashboard：摘要、成片播放、待审核卡片、最近任务、阶段按钮
   ├─ 任务与日志：状态胶囊 + 进度条 + 实时日志（可清空）
   └─ 工作台 11 个页签：剧本 / 角色 / 场景 / 导演 / 分镜 / 视频 /
      配音字幕 / 剪辑 / 质量评估 / 审核 / 模型配置
```

### 3.2 身份与权限

| 你想成为 | 操作 |
| --- | --- |
| 演示管理员（默认） | 身份框保持 `user_demo`。此时浏览器**不发送** `X-User-Id`，服务端按 demo 身份处理，角色为 admin |
| 某个普通用户 | 身份框填其它名字，角色选 `user` |
| 某个管理员 | 身份框填名字，角色选 `admin` |

规则（与代码一致）：

- 请求不带 `X-User-Id` → 使用 demo 身份，且**固定为 admin**。
- 请求带 `X-User-Id` → 该 ID 即当前用户；`X-User-Role` 只有在带了 `X-User-Id` 时才被采用。
- 项目可见性：`所有者` 或 `ProjectMember` 成员可见；无成员关系时返回 403。
- 修改类操作（上传、解析、生成、审核、导出）要求 `所有者` 或 `editor` 成员身份。
- 「模型配置」页签与 `/api/v1/admin/*` 需要 `admin`（或 `owner`）角色，否则提示「需要管理员身份」。

> 多用户协作目前没有 HTTP 接口：成员关系需要调用服务层的
> `app.services.projects.invite_member(db, project, user_id, role)` 写入。

### 3.3 新建项目

1. 左栏输入项目名 → **新建项目**。
2. 项目自动选中，Dashboard 显示 `项目 状态`、`题材/语言`、成本、工作流状态。
3. 需要的话可通过 API 补充字段：`PATCH /projects/{id}` 支持 `description`、`aspect_ratio`、
   `budget_limit_usd`、`settings`。

项目状态含义：

`draft` → `ingested`（已入库章节）→ `script_ready`（剧本）→ `characters_ready`（人物场景）→
`storyboard_ready`（分镜）→ `video_ready`（镜头视频）→ `edited`（成片）→ `completed`（已导出）；
另有 `archived`。

### 3.4 导入小说

两种方式，效果相同（都返回章节列表，解析是同步完成的）：

- 「剧本」页签 → 选择文件 → **上传小说**；
- 控制台 **导入示例小说**（Dashboard 按钮或「剧本」页签的「导入示例」）。

约束与行为：

| 项 | 说明 |
| --- | --- |
| 支持格式 | `.txt` / `.md` / `.docx`（其它后缀按纯文本解码，不保证成功） |
| 大小上限 | **20 MB**（`MAX_UPLOAD_BYTES` 硬限制，超出报「文件超过 20MB 上限」） |
| 章节切分 | 识别「第 N 章 / Chapter N / 1. 标题」等短标题行（≤40 字）；超长章节按约 8000 字再切分；切不出章节会报错 |
| 重复导入 | 不覆盖旧文档，会新增一份源文档与对应章节 |

导入后可在「剧本」页签核对章节卡片（序号、标题、字数、摘要）。若切分不理想，修正原文件后重新上传。

### 3.5 一键完整流程与四个审核关卡

```
导入小说 → 章节切分 → 剧本解析 → 人物/场景提取 → 【关卡1 人物与场景】
   → 导演规划 → 分镜 → 【关卡2 分镜】
   → 角色形象 → 镜头视频 → 【关卡3 镜头视频】
   → 配音字幕 → 剪辑 → 合成 → 质量评估 → 【关卡4 成片】→ 导出
```

点击 **一键完整流程** 后：

- 工作流与任务同时启动，日志区滚动显示 `[event_type] message`；
- 到达关卡时任务变为 `awaiting_review`，工作流暂停，等待人工决定；
- 在关卡卡片点 **通过并继续** 会自动恢复工作流，继续跑下一段；
- 同一项目**同时只允许一个**进行中/待审工作流，重复启动会报
  「该项目已有进行中的工作流，请先完成或取消」。

其中「角色形象」节点配置为 `continue_on_error`：个别角色出图失败不会中断整个流程，
可在「角色」页签单独重试。

### 3.6 任务与日志

| 任务状态 | 含义 |
| --- | --- |
| `pending` | 已入队 |
| `running` | 执行中（进度条 0~100%） |
| `succeeded` | 成功 |
| `failed` | 失败（日志里有 `[error]` 行与错误摘要） |
| `cancelled` | 已取消 |

- 日志来自 SSE 事件流，事件类型包括 `started`、`progress`、`succeeded`、`failed`、`cancelled`
  等；流结束时会打印「事件流结束（end 或 timeout）」。
- 刷新页面后日志清空，但任务不会中断——用 Dashboard 的「最近任务」或
  `GET /projects/{id}/tasks` 查看状态。
- 控制台没有「取消」按钮，取消任务用接口（见 6.3）。

---

## 4. 分步生产（每步做什么）

Dashboard 上的一排按钮就是流水线的单个阶段，也可以只跑其中几步。推荐顺序：

| # | 按钮 | 任务类型 | 前置条件 | 产出 |
| --- | --- | --- | --- | --- |
| 1 | 导入示例小说 / 上传小说 | 同步解析 | 项目存在 | 源文档 + 章节 |
| 2 | 剧本解析 | `script` | 已有可解析章节 | 剧本 v1 + 故事事件 |
| 3 | （仅工作流内）人物/场景提取 | `characters` / `scenes` | 已有剧本 | 人物档案 + 场景档案 |
| 4 | 导演规划 | `directing` | 已有剧本 | 导演规划 v1（镜头语言/情绪基调/统一风格） |
| 5 | 生成分镜 | `storyboard` | 剧本 + 导演规划 | 分镜 v1（镜头列表/时长/运镜/台词/提示词） |
| 6 | 角色形象 | `character_images`（逐人） | 已有人物 | 每个人物的 portrait / full_body / turnaround |
| 7 | 生成视频 | `video` | 已有分镜 | 每个镜头一个视频版本 |
| 8 | 生成配音 | `audio` | 已有分镜 | 台词配音音轨 + 字幕 |
| 9 | 编排时间线 | `editing` | 已选镜头视频 | 剪辑工程 v1（时间线 JSON） |
| 10 | 合成成片 | `render` | 已有时间线 | 成片资产（MP4） |
| 11 | 质量评估 | `evaluation` | 已有分镜/成片 | 评估报告（评分 + 问题清单） |
| 12 | 导出 MP4 | `export` | 已渲染成片 | 导出资产，项目置为 `completed` |

> 第 3 步只有工作流节点、没有独立按钮：人物与场景在「一键完整流程」里生成
> （规则是 `extract_characters` / `extract_scenes`）。所以纯手工分步时，「角色」「场景」
> 页签会是空的——需要人物素材时，请让一键流程先跑到【关卡1】再停下来返工。

### 4.1 剧本解析

产出结构化剧本（标题、一句话梗概、剧情梗概、结构化内容）与故事事件列表，项目状态变为
`script_ready`。未先导入章节时会报「请先上传并解析小说文本，再进行剧本解析」。

- 本步**只写剧本**：人物与场景是工作流里紧随其后的两个节点（见第 4 章表格第 3 行）。
- 再次点击会生成**新版本**（v2、v3…），旧版本保留。

### 4.2 剧本工作台

「剧本」页签可编辑：标题、一句话梗概、剧情梗概、结构化内容（JSON）。

- **保存剧本** 是**就地更新当前版本**（不新增版本），并把状态置为 `edited`；
  修改过程只校验 JSON 语法，不校验剧本 schema，写错结构下游会读不到字段。
- 需要保留旧内容时，先重跑「剧本解析」生成新版本，再在新版本上改。
- 修改后建议重跑「导演规划」「生成分镜」，否则下游仍是旧内容。

### 4.3 角色

每个角色卡片可以：

- 改 **人物小传**（`summary`）与 **外形关键词**（逗号分隔）→ **保存**；
- **生成形象**：一次性生成 `portrait` / `full_body` / `turnaround`；
- **三视图**：单独重生成 turnaround；
- **通过**：把该角色标记为 `approved`，并写入 `approved_version`。

生成的图片按 `kind + version` 排列在卡片下方，带「已通过」标记的是已确认版本。

### 4.4 场景

每个场景卡片可改场景说明并 **通过**；卡片标题会显示「已通过 / 草稿」以及该场景的视觉提示词。
场景审核会随【关卡1 人物与场景】一起通过；单独点「通过」只是提前确认。

### 4.5 导演规划

只读展示（内容为 JSON）：版本号、状态、是否通过、生成用的模型 ID、历史版本胶囊。
修改方式有两种：重跑「导演规划」出新版本，或调整 `config/agents/director.yaml` 与 prompt 后再跑。

### 4.6 分镜

顶部显示分镜版本、审批状态、镜头数量。每个镜头卡片显示：

`#序号 画面描述` + 状态胶囊；`时长 · 运镜 · 出场角色`；动作；可编辑的 **视觉提示词**。

操作：

- **保存提示词**：只改当前镜头（`PATCH /shots/{id}`），可直接影响后续视频生成；
- **通过**：单镜头批准（与关卡3 的批量通过等效）；
- **生成视频**：只为这个镜头生成一个视频版本。

### 4.7 镜头视频

「视频」页签按镜头列出**所有视频版本**，每个版本可播放、可 **选用**（`selected`）。
批量生成用 Dashboard 的 **生成视频**；单个重生成用「分镜」页签里该镜头的 **生成视频**。

规则：

- 只有生成完成的版本才能选用（否则报「该候选视频尚未生成完成」）；
- 选用后该镜头 `selected_video_id` 指向它，剪辑只用被选用的版本；
- 历史版本不删除，随时切换。

### 4.8 配音与字幕

「生成配音」按镜头台词逐句合成音轨（显示类型、状态、时长、起始时间、文本），
并产出字幕资产（SRT）。未生成分镜时会报「还没有分镜，无法生成配音」。

### 4.9 剪辑与合成

- **编排时间线**：把选用的镜头视频按时长串成时间线（显示版本、时长、时间线 JSON）。
  无分镜时提示「还没有分镜，无法编排时间线」。
- **合成成片**：用 FFmpeg 拼接画面、混入配音、烧录字幕，产出成片（`film` 资产），
  「剪辑」页签会直接播放，并提供「下载字幕 SRT」。

无时间线时合成会报「还没有时间线，无法合成成片」；FFmpeg 缺失时不会崩，
剪辑工程保留时间线与错误信息（「FFmpeg 不可用，已保留时间线清单，安装后可重新合成」），
装好 FFmpeg 后重新点「合成成片」即可。

### 4.10 导出

**导出 MP4** 会把当前成片复制为 `export` 资产（元数据里带 `<项目名>.mp4`），
剪辑版本状态变为 `exported`，项目状态变为 `completed`。

- 控制台不直接给出导出链接；用 `GET /api/v1/projects/{id}/export` 取 `film.url` 下载，
  或在「质量评估」完成后于 Dashboard 的「成片 / Film」播放。
- 未渲染就导出会报「还没有可导出的成片，请先完成合成」。

### 4.11 质量评估

数据指标由数据库统计（不由模型臆造），评估智能体只负责解释与打分。控制台展示：

- 总分与建议（`accept` / `regenerate` 等）、摘要；
- 维度评分（阈值来自 `config/agents/evaluation.yaml`：`story_consistency` 0.75、
  `character_consistency` 0.75、`visual_quality` 0.7、`audio_quality` 0.65）；
- 问题清单（severity + type + description）；
- 原始指标 JSON（`Metrics` 区）。

常用指标含义：

| 指标 | 含义 |
| --- | --- |
| `shots` / `shots_with_video` | 镜头总数 / 已选用视频的镜头数 |
| `video_coverage` | 覆盖率 = 已选用视频镜头数 ÷ 镜头总数 |
| `video_candidates` | 生成的候选视频总数（含未选用） |
| `approved_shots` | 已通过镜头数 |
| `audio_tracks` / `dialogue_lines` | 音轨数 / 台词行数 |
| `subtitles` | 是否已有字幕资产 |
| `character_count` / `character_profiles` / `character_assets` | 人物数 / 档案数 / 人物素材数 |
| `character_consistency` | 人物一致性粗估（素材覆盖全时更高） |
| `total_duration_seconds` | 镜头时长合计 |
| `render_status` / `rendered` / `final_video` | 剪辑状态、是否已渲染出成片 |
| `budget_usd` | 当前累计成本 |

评估结果只作决策参考：需要重做时，改提示词/换视频版本后重新「生成视频 → 编排时间线 → 合成 →
质量评估」，再走最终审核。

---

## 5. 审核（人工关卡）

### 5.1 四个关卡

| 关卡 | `stage` | 通过时写回什么 |
| --- | --- | --- |
| 人物与场景 | `characters_scenes` | 所有人物档案/素材/场景置为 approved，项目 → `characters_ready` |
| 分镜 | `storyboard` | 分镜与导演规划 approved，全部镜头 approved，项目 → `storyboard_ready` |
| 镜头视频 | `shots` | 镜头 approved、有选中视频的镜头置 `approved`，项目 → `video_ready` |
| 成片 | `final` | 剪辑版本 `rendered` → `approved`，项目 → `edited` |

### 5.2 通过

在 Dashboard 的 **待审核** 卡片或「审核」页签里填写意见（可留空）→ **通过并继续**。
通过后会自动恢复工作流继续跑下一段（接口参数 `resume_workflow` 默认 `true`）。

### 5.3 驳回与重新提审

驳回**不会**自动恢复工作流：工作流停在 `awaiting_review`，该条审核变为 `rejected`
（已处理的审核不能再改结论，重复提交会报「该审核已经处理」）。

标准处理流程：

1. 按意见返工：改镜头提示词、重生成某个视频版本、重新「生成分镜」等；
2. 让工作流重新排队到该关卡，二选一：
   - **恢复原工作流**（推荐，保留前面所有产物）：
     `POST /api/v1/projects/{id}/workflows/{run_id}/resume`
     引擎发现该关卡没有 approved 记录，会为同一关卡**新建一条待审记录**；
   - **取消并重跑**：先 `POST /api/v1/projects/{id}/workflows/{run_id}/cancel`，
     再点「一键完整流程」。新 run 从第一个节点重新执行，会产出新的剧本/分镜/视频版本
     （旧版本仍保留在库里）。
3. 新的待审卡片出现在「审核」页签，重新决定。

> 控制台目前没有「恢复工作流」按钮，驳回后请按上面的接口操作（或让管理员协助）。

### 5.4 审核评论

每条审核支持多条评论：`GET/POST /api/v1/reviews/{review_id}/comments`，
正文不能为空（最长 4000 字）。审核卡片上会显示评论条数。

---

## 6. 任务、进度与取消

### 6.1 看任务

| 目的 | 接口 |
| --- | --- |
| 项目任务列表 | `GET /projects/{id}/tasks?limit=50` |
| 单个任务 + 历史事件 | `GET /projects/{id}/tasks/{task_id}` |
| 只拉事件（增量） | `GET /projects/{id}/tasks/{task_id}/events?after=<event_id>` |
| 实时事件流（SSE） | `GET /projects/{id}/tasks/{task_id}/events/stream?timeout=900` |

SSE 帧格式：首次 `: connected`，随后 `event: task` + 一行 JSON（`event_type`、`message`、
`progress`、`level` 等），结束时 `event: end`，超过 `timeout`（默认 900 秒）则 `event: timeout`。
超时只断开连接，任务继续跑；重新订阅即可继续看。

### 6.2 任务类型对照

`workflow`、`workflow_resume`、`script`、`characters`、`scenes`、`parse_document`、`directing`、
`storyboard`、`character_images`、`video`、`shot_video`、`audio`、`editing`、`render`、`export`、
`evaluation`。

### 6.3 取消任务

```powershell
$base = "http://127.0.0.1:8010/api/v1"
$pid = "<project_id>"
$tasks = Invoke-RestMethod "$base/projects/$pid/tasks"
$tid = $tasks.items[0].id
Invoke-RestMethod -Method Post -Uri "$base/projects/$pid/tasks/$tid/cancel"
```

只有 `pending` / `running` 的任务可以取消；已入库的产物不会被回滚。

### 6.4 工作流状态

`pending` / `running` / `awaiting_review` / `completed` / `failed` / `cancelled`。
查看：`GET /projects/{id}/workflows`（列表）与 `/workflows/{run_id}`（含每个节点的 checkpoint、
摘要、错误、输出）。失败排障时先看 `run.error` 与失败节点的 `error`。

---

## 7. 模型配置（管理员）

### 7.1 查看运行状态

「模型配置」页签顶部（或 `GET /admin/status`）：环境、数据库、存储、FFmpeg 可用性、
任务模式与并发、启用智能体数、各 scope 的配置版本。
`GET /admin/providers` 列出 provider 是否启用、是否已配置密钥（`has_api_key`）。

### 7.2 修改某个智能体的模型配置

1. 「模型配置」页签 → 找到 agent（例如 `script`）→ **版本编辑**；
2. 编辑完整配置 JSON（`model`、`generation`、`structured_output`、`prompt`、`runtime`、`evaluation`）；
3. 填 **变更说明** → **保存为新版本**：立即生效，并写入 `config_versions` 记录；
4. 想撤销：**回退到 YAML**（删除数据库覆盖，回到 `config/agents/<agent>.yaml`）。

其他相关接口：

| 用途 | 接口 |
| --- | --- |
| 查看当前生效配置 + 版本列表 | `GET /admin/model-configs/{agent_id}` |
| 写一个新版本（立即生效） | `POST /admin/model-configs/{agent_id}/versions`，body `{"payload": {...}, "note": ""}` |
| 主动回滚到上一个非激活版本 | `POST /admin/model-configs/{agent_id}/rollback`（无 body） |
| 删除数据库覆盖，回到 YAML | `DELETE /admin/model-configs/{agent_id}/override` |
| 全局配置版本账本 | `GET /admin/model-config-versions?scope=&key=` |
| 激活指定版本 | `POST /admin/model-config-versions/{version_id}/activate` |

注意：配置版本会在**任务创建时冻结**并记录在任务上（`task.config_versions`），
所以改配置只影响之后新建的任务；正在跑的任务仍按旧配置完成。

### 7.3 接入真实模型（示例：把剧本智能体换到 OpenAI 兼容网关）

1. 在 `config/providers/llm.yaml` 把目标 provider 的 `enabled` 改为 `true`
   （`openai` 或 `openai_compatible`），并把 `url` / `api_key` 填成自己的地址和密钥：
   `url` 可直接写 `https://api.deepseek.com/v1`，`api_key` 建议写 `env:OPENAI_COMPAT_API_KEY`；
2. 如果 `api_key` 用的是 `env:名字`，就在 `.env` 里补一行（如 `OPENAI_COMPAT_API_KEY=你的密钥`,
   勿提交）；直接粘贴密钥则不需要 `.env`；
3. 把 `config/agents/script.yaml` 的 `model.provider` / `model.model_id` 改成该 provider 与模型，
   或在控制台用「版本编辑」改（无需重启）；
4. 重启服务让 provider YAML 生效（provider 配置不走数据库覆盖）；
5. 验证：`GET /admin/providers` 中该 provider `enabled=true` 且 `has_api_key=true`，然后跑一次
   「剧本解析」，在任务日志里确认模型 ID 与耗时；
6. 成本：provider YAML 的 `extra.input_cost_per_1k` / `output_cost_per_1k` 参与计费，
   Dashboard「成本」显示累计 `spent_usd`。

默认文字 provider 是 `fast_gateway`；`openai`/`openai_compatible`/`qwen` 保留但默认禁用。
其他能力可选 provider：图片 `openai`/`local_comfy`、
语音 `openai`/`local_tts`、视觉 `openai`/`local_vision`、视频 `openai_videos`（本机 `minimax`）/
`local_worker`/`hosted`。每个 provider 只看三个字段：`url`（接口地址）、`api_key`
（`env:环境变量名` 或直接写密钥）、`models`（可用模型名）。

排障要点：

- provider 未启用或缺少密钥 → 接口返回 provider 不可用类错误，日志含 `ProviderUnavailableError`；
- 模型 ID 不在该 provider 的 `models` 列表、或传了 `extra.supported_params` 之外的生成参数 → 配置类错误；
- 不想全链路接真模型时，可用 `AGENT_MODEL_PROVIDER` / `AGENT_MODEL_ID` 强制统一到某个 provider（仅开发环境）。

### 7.4 默认文字模型与独立视频服务

文字与视频来自不同厂商完全没问题——它们分属 `config/providers/llm.yaml` 与
`config/providers/video.yaml` 两个文件，互不影响。当前默认配置如下：

| 用途 | provider | 文件 | 地址 | 模型 |
| --- | --- | --- | --- | --- |
| 12 个文字类智能体 | `fast_gateway` | `config/providers/llm.yaml` | `.env: FAST_GATEWAY_BASE_URL` | `.env: FAST_GATEWAY_MODEL` |
| 视频智能体 | `minimax` | `config/providers/video.yaml` | `http://127.0.0.1:8090/v1` | `minimax-h3` |

密钥放在 `.env`（已被 `.gitignore` 忽略）：

```ini
FAST_GATEWAY_API_KEY=你的文字供应商密钥
FAST_GATEWAY_BASE_URL=https://fast.sbbbbbbbbb.xyz/v1
FAST_GATEWAY_MODEL=gpt-6.1-terra
# 视频服务需要时单独配置
# MINIMAX_API_KEY=你的视频供应商密钥
```

要点：

1. `fast_gateway` 使用通用 Chat Completions 参数。原本机 `qwen` 配置保留但禁用，
   其中 vLLM 专用的 `reasoning_effort`、`chat_template_kwargs` 不用于当前默认供应商；
2. 视频服务是「提交 → 轮询 → 取文件」：`POST /v1/videos` → `GET /v1/videos/{id}` →
   `GET /v1/videos/{id}/content`，对应 `protocol: openai_videos` 与 `extra.content_suffix: /content`；
3. 该服务是纯文生视频（传参考图会 400），适配器默认只发 `prompt` / `duration_seconds` /
   `width` / `height`，参考图会被忽略并记在 `meta.dropped_inputs`；
4. 单条最长 14.375 秒，`extra.max_duration_seconds: 14` 会先截断再提交（`meta.duration_clamped_from`）；
5. 显存吃紧时在 `minimax` 的 `extra.request_defaults` 里加 `width: 848, height: 480`，
   或降低 `steps`（默认 8，越小越快）；
6. 改完 provider YAML 需重启服务；智能体的 provider/model 可以用控制台「模型配置」改，不必重启。

---

## 8. API 速查（PowerShell）

演示管理员身份下不需要任何鉴权头（不带 `X-User-Id` 即 demo admin）。带身份时加头：
`-Headers @{"X-User-Id"="alice"; "X-User-Role"="admin"}`。

```powershell
$base = "http://127.0.0.1:8010/api/v1"

# 1) 建项目
$p = Invoke-RestMethod -Method Post -Uri "$base/projects" `
      -ContentType "application/json" -Body '{"name":"雨夜书店"}'

# 2) 导入内置样例小说，返回章节
$up = Invoke-RestMethod -Method Post -Uri "$base/projects/$($p.id)/upload?sample=true"

# 3) 启动完整工作流（异步，返回 task_id）
$run = Invoke-RestMethod -Method Post -Uri "$base/projects/$($p.id)/workflows/start" `
       -ContentType "application/json" -Body '{}'

# 4) 看任务与事件
Invoke-RestMethod "$base/projects/$($p.id)/tasks" | Select-Object -ExpandProperty items |
  Format-Table id, type, status, progress, message

# 5) 处理待审
$pending = Invoke-RestMethod "$base/projects/$($p.id)/reviews?status=pending"
Invoke-RestMethod -Method Post -Uri "$base/reviews/$($pending.items[0].id)" `
  -ContentType "application/json" -Body '{"status":"approved","comment":"可以"}'

# 6) 误驳后重新提审
$runs = Invoke-RestMethod "$base/projects/$($p.id)/workflows"
Invoke-RestMethod -Method Post -Uri "$base/projects/$($p.id)/workflows/$($runs.items[0].id)/resume"

# 7) 取导出文件地址
(Invoke-RestMethod "$base/projects/$($p.id)/export").film.url
```

常见步骤的对应接口：`/analyze`、`/direct`、`/storyboards`、`/shots/generate`、`/audio`、
`/editing`、`/render`、`/evaluate`、`/export`；单个镜头 `POST /shots/{id}/generate`，
单个角色 `POST /characters/{id}/generate-images`。

---

## 9. 数据备份、清理与升级

### 9.1 备份

```powershell
# 1) 先停服务（避免 SQLite 写入过程中拷走）
# 2) 打包数据库与生成媒体
Compress-Archive -Path data\studio.db, data\storage -DestinationPath backup-studio.zip
```

Docker 方式：`docker compose stop` → 复制卷 `ai-film-studio_studio-data`（或
`docker run --rm -v ai-film-studio_studio-data:/data -v ${PWD}:/out alpine tar czf /out/backup.tgz -C /data .`）。

### 9.2 恢复

停服务 → 用备份覆盖 `data/studio.db` 与 `data/storage` → 启动。
数据库表在启动时自动创建，不需要迁移脚本。

### 9.3 清理

- 单个项目：目前没有删除接口，需要自行清理数据库行与 `data/storage/<project_id>/`；
- 全部重置：停服务后删除 `data/studio.db` 与 `data/storage/*`，重启即得到空库；
  注意 `samples/`、`config/` 不受影响。

### 9.4 升级

源码方式：

```powershell
git pull
uv sync --frozen --extra dev
python scripts/export_schemas.py     # 配置 schema 变更时，让 config/schemas 与代码一致
python -m pytest                     # 可选，升级前自检
```

一键安装方式：直接运行新版 `install.exe`。它会先停掉正在运行的服务，复用已有的 `venv`，
重装依赖并覆盖 `app\`，`data\` 原样保留。装到自定义目录时要带上同样的 `--dir`。

重启后检查 `/health` 与控制台「模型配置」页签的 `配置版本` 是否更新。

---

## 10. 常见问题

| 现象 / 报错 | 原因 | 处理 |
| --- | --- | --- |
| `403` `Role 'editor' required for this action` / `You do not have access to this project` | 当前身份不是该项目所有者且不是 editor 成员 | 切回项目所有者身份；或让管理员用 `invite_member` 加成员 |
| 「需要管理员身份」 | 角色不是 `admin`/`owner` | 顶部把角色切到 `admin`（演示身份的默认角色就是 admin） |
| 「该项目已有进行中的工作流，请先完成或取消」 | 该项目已有 `running`/`awaiting_review` 工作流 | 先处理审核；或取消该 run 后再启动 |
| 「请先上传并解析小说文本，再进行剧本解析」 | 没有可解析章节 | 上传小说或点「导入示例小说」 |
| 「生成分镜前需要先完成剧本解析与导演规划」 | 缺剧本或导演规划 | 依次跑「剧本解析」→「导演规划」 |
| 「还没有分镜，无法生成镜头视频 / 配音 / 编排时间线」 | 分镜缺失 | 先「生成分镜」并通过关卡2 |
| 「还没有时间线，无法合成成片」 | 未编排时间线 | 先「编排时间线」 |
| 「还没有可导出的成片，请先完成合成」 | 未渲染 | 先「合成成片」，确认成片可播放 |
| 剪辑状态保留但无成片，错误「FFmpeg 不可用…」 | 找不到 ffmpeg | 安装 FFmpeg 或设 `FFMPEG_BIN`，重启后重新「合成成片」 |
| 上传报「文件超过 20MB 上限」 | 超过硬限制 | 拆分或压缩文本；PDF/超大文件请先转成 txt |
| 上传报「无法从文档中切分出章节」 | 没有章节标题 | 在文本中补「第一章 …」这类标题后重传 |
| 上传 docx 报需要 `python-docx` | 依赖缺失 | `uv sync --frozen` 重新同步锁定依赖 |
| 「该审核已经处理」 | 审核已通过/驳回 | 驳回后按 5.3 重新提审，不要再重复提交同一 review |
| 事件流长时间无输出后结束 | SSE 默认 900 秒超时 | 任务仍在跑；刷新页面或重新订阅事件流即可 |
| 页面一直「离线」 | 服务未启动或端口不对 | 确认 `uvicorn` 进程与端口，检查 `/health` |
| 端口被占用 | 已有旧进程 | `netstat -ano` 找到监听 8010 的 PID 后结束该进程，或换 `--port` |
| 控制台中文乱码（终端日志） | Windows 终端代码页 | `chcp 65001`，或设 `$env:PYTHONIOENCODING="utf-8"` |
| 「未注册的工作流 handler 'xxx'，可用: …」 | 工作流节点引用了不存在的 handler/agent | 核对 `config/workflows/*.yaml` 的 `handler` 与 `config/agents/` 下的 agent id |
| 双击 `install.exe` 后窗口一闪而过 | 版本不匹配/权限/被杀软拦截 | 在命令行里运行 `install.exe --no-pause` 看完整输出；SmartScreen 选「更多信息 → 仍要运行」 |
| `install.exe` 卡在 `[3/7] Dependencies` | PyPI 不可达（公司网络/代理） | 设 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` 后重跑（脚本自己下的 Python 同理需要能出国/走代理） |
| `uninstall.exe` 提示文件夹被占用 | 控制台窗口还开着 | 关掉正在运行的控制台窗口后重试；或重启电脑再卸载 |

---

## 11. 上线前检查清单

- [ ] `APP_ENV=production`，`APP_ALLOW_DEV_AUTH=0`，鉴权由网关/OIDC 统一完成（见 ADR 0005）。
- [ ] 数据库切到 PostgreSQL（`DATABASE_URL`），并配置备份策略。
- [ ] 存储切到 S3/兼容对象存储（`STORAGE_BACKEND=s3`，装 `.[s3]` extra），生产环境不共享本地磁盘。
- [ ] 固定**单** uvicorn worker：外部任务 worker 尚未提供，`tasks.inline` 必须保持开启。
- [ ] FFmpeg 已安装，`/admin/status` 显示可用；容器镜像已内置。
- [ ] 反向代理按 `deployment/nginx/default.conf` 关闭 SSE 与 `/media/` 的缓冲，并放大超时。
- [ ] 模型密钥只放在环境变量/密钥管理里，`.env` 不进仓库（`.gitignore` 已覆盖）。
- [ ] 审核角色与流程明确：谁负责四个关卡的通过/驳回。
- [ ] 预算：按项目设置 `budget_limit_usd`，定期看 Dashboard 成本与 `budget_events`。

---

## 12. 术语表

| 术语 | 含义 |
| --- | --- |
| Agent / 智能体 | 单个可配置的模型调用单元（17 个），配置在 `config/agents/<agent>.yaml` |
| Provider / Provider 桶 | 模型供应商，按能力分为 `llm` / `vision` / `image` / `video` / `audio` |
| Workflow / 工作流 | YAML 定义的节点序列，带持久化游标与 checkpoint |
| Gate / 关卡 | 需要人工决定的节点，对应 `Review` 记录 |
| Task / 任务 | 一次具体执行（阶段或整个工作流），事件写 `task_events` 供 SSE 推送 |
| Storyboard / 分镜 | 镜头列表：序号、时长、运镜、台词、视觉提示词 |
| Shot / 镜头 | 分镜中的单个镜头，可多版本视频、可单独通过 |
| Editing / 剪辑工程 | 时间线 JSON + 渲染输出 + 字幕资产 |
| Film / 成片 | 渲染产出的 MP4 资产；`export` 资产是它的导出副本 |
| Config version | 智能体配置的版本化记录，任务创建时冻结 |

---

## 相关文档

- [../architecture/overview.md](../architecture/overview.md) — 分层、请求/任务流、工作流引擎
- [../api/README.md](../api/README.md) — 接口清单、鉴权、SSE 帧格式、错误码
- [../agents/README.md](../agents/README.md) — 智能体清单与新增步骤
- [../model_configs/README.md](../model_configs/README.md) — 配置分层、参数、版本与回滚
- [../database/schema.md](../database/schema.md) — 数据表分组
- [../testing/README.md](../testing/README.md) — 测试与 CI
- [../decisions/README.md](../decisions/README.md) — 架构决策记录
