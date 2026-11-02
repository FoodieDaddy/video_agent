整体上，我建议将项目正式定义为一个可配置、可扩展、支持人工审核的多智能体 AI 视频生产平台（AI Film Studio）。

开发时不要把所有功能和模型写死在代码里，而是采用“核心工作流稳定、智能体独立、模型配置外置、能力通过接口扩展、生成结果可追溯”的工程架构。

这意味着：

- 后续更换大语言模型、图像模型、视频模型，不需要重写智能体业务逻辑。
- 每个智能体可以独立配置模型、参数、提示词、超时时间和备用模型。
- 人物设定、人物图片、场景、分镜、视频、配音和剪辑都作为独立模块开发。
- 用户可以在关键环节审核、修改和局部重新生成。
- 开发者可以增加新的智能体、模型供应商、工作流节点和前端功能，而不破坏已有系统。
- 每个生成任务都保留输入、模型版本、配置版本、提示词、输出和评估结果，方便复现和调优。

下面将整体方案按正式软件工程项目的方式组织，既能作为开发任务书，也能作为后续交给编程智能体或开发团队的实施依据。

## 1. 总体技术路线与架构原则

### 1.1 产品目标

系统最终应实现以下完整能力：

1. 小说与剧本处理：上传 TXT、DOCX、PDF 等文件，解析章节、人物、对白、事件和场景。
2. 人物设定：支持文字创建、图片上传、小说自动提取、AI 补全、人物图片生成、三视图、表情、服装和人物关系管理。
3. 场景设定：提取地点、时间、环境、建筑、光线、气氛，生成场景参考图。
4. 导演规划：将故事拆成章节、场景、镜头，规划节奏、景别、运镜、人物调度和镜头时长。
5. 分镜创作：每个镜头都有结构化描述、人物引用、场景引用、对白、动作和生成提示词。
6. 视频生成：根据分镜调用不同视频模型，支持文生视频、图生视频、首尾帧、参考图和局部重生成。
7. 声音制作：角色配音、旁白、环境音、音乐、音效和字幕。
8. 自动剪辑：合成镜头、音轨、字幕、转场和片头片尾。
9. 质量评估：检查剧情、人物一致性、场景一致性、画面质量、声音和字幕。
10. 人工审核与编辑：用户能够在关键步骤确认、修改、驳回、重新生成和恢复任务。

### 1.2 架构设计原则

| 原则    | 工程要求                   |
| ----- | ---------------------- |
| 模块化   | 每个智能体和业务模块有明确输入、输出和职责  |
| 配置驱动  | 模型、参数、提示词、工作流策略外置      |
| 接口解耦  | 业务层不直接依赖某一家模型供应商       |
| 数据可追溯 | 保存模型、提示词、输入、输出和版本      |
| 可恢复   | 长任务支持断点续跑、失败重试和人工中断    |
| 可扩展   | 支持新增 Agent、模型、工具、工作流节点 |
| 可测试   | 每个模块有单元测试、集成测试和评估集     |
| 可观测   | 记录耗时、成本、失败率、质量和调用日志    |
| 人机协作  | 重要资产和视频结果由用户审核         |
| 安全隔离  | 项目、用户、密钥和媒体文件隔离管理      |

### 1.3 推荐总体架构

\#chatgpt-mermaid-\_r_12o\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(13, 13, 13);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_12o\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_12o\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_12o\_ .error-icon{fill:rgb(243, 243, 243);}#chatgpt-mermaid-\_r_12o\_ .error-text{fill:rgb(13, 13, 13);stroke:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_12o\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_12o\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_12o\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_12o\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_12o\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_12o\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_12o\_ .marker{fill:rgb(143, 143, 143);stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_12o\_ .marker.cross{stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_12o\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_12o\_ p{margin:0;}#chatgpt-mermaid-\_r_12o\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_12o\_ .cluster-label text{fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_12o\_ .cluster-label span{color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_12o\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_12o\_ .label text,#chatgpt-mermaid-\_r_12o\_ span{fill:rgb(13, 13, 13);color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_12o\_ .node rect,#chatgpt-mermaid-\_r_12o\_ .node circle,#chatgpt-mermaid-\_r_12o\_ .node ellipse,#chatgpt-mermaid-\_r_12o\_ .node polygon,#chatgpt-mermaid-\_r_12o\_ .node path{fill:rgb(222, 234, 251);stroke:rgb(83, 154, 248);stroke-width:1px;}#chatgpt-mermaid-\_r_12o\_ .rough-node .label text,#chatgpt-mermaid-\_r_12o\_ .node .label text,#chatgpt-mermaid-\_r_12o\_ .image-shape .label,#chatgpt-mermaid-\_r_12o\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_12o\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_12o\_ .rough-node .label,#chatgpt-mermaid-\_r_12o\_ .node .label,#chatgpt-mermaid-\_r_12o\_ .image-shape .label,#chatgpt-mermaid-\_r_12o\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_12o\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_12o\_ .root .anchor path{fill:rgb(143, 143, 143)!important;stroke-width:0;stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_12o\_ .arrowheadPath{fill:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_12o\_ .edgePath .path{stroke:rgb(143, 143, 143);stroke-width:1px;}#chatgpt-mermaid-\_r_12o\_ .flowchart-link{stroke:rgb(143, 143, 143);fill:none;}#chatgpt-mermaid-\_r_12o\_ .edgeLabel{background-color:rgb(252, 252, 252);text-align:center;}#chatgpt-mermaid-\_r_12o\_ .edgeLabel p{background-color:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_12o\_ .edgeLabel rect{opacity:0.5;background-color:rgb(252, 252, 252);fill:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_12o\_ .labelBkg{background-color:rgba(252, 252, 252, 0.5);}#chatgpt-mermaid-\_r_12o\_ .cluster rect{fill:rgb(243, 243, 243);stroke:rgba(0, 0, 0, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_12o\_ .cluster text{fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_12o\_ .cluster span{color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_12o\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(243, 243, 243);border:1px solid rgba(0, 0, 0, 0.1);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_12o\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_12o\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_12o\_ .icon-shape,#chatgpt-mermaid-\_r_12o\_ .image-shape{background-color:rgb(252, 252, 252);text-align:center;}#chatgpt-mermaid-\_r_12o\_ .icon-shape p,#chatgpt-mermaid-\_r_12o\_ .image-shape p{background-color:rgb(252, 252, 252);padding:2px;}#chatgpt-mermaid-\_r_12o\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_12o\_ .image-shape .label rect{opacity:0.5;background-color:rgb(252, 252, 252);fill:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_12o\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_12o\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_12o\_ .node .neo-node{stroke:rgb(83, 154, 248);}#chatgpt-mermaid-\_r_12o\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_12o\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_12o\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_12o\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_12o\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_12o\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_12o\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_12o\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_12o\_ [data-look="neo"].node .neo-line path{stroke:rgb(83, 154, 248);filter:none;}#chatgpt-mermaid-\_r_12o\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_12o\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_12o\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_12o\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_12o\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_12o\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_12o\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_12o\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(0, 79, 153);}#chatgpt-mermaid-\_r_12o\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(0, 79, 153);}#chatgpt-mermaid-\_r_12o\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_12o\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_12o\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(245, 250, 255);stroke:rgb(206, 219, 229);stroke-width:1px;}#chatgpt-mermaid-\_r_12o\_ .node rect,#chatgpt-mermaid-\_r_12o\_ .node circle,#chatgpt-mermaid-\_r_12o\_ .node ellipse,#chatgpt-mermaid-\_r_12o\_ .node polygon,#chatgpt-mermaid-\_r_12o\_ .node path{fill:rgb(229, 243, 255);stroke:rgba(0, 0, 0, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_12o\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_12o\_ .mermaid-decision .label-container{fill:rgb(245, 250, 255);stroke:rgb(206, 219, 229);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_12o\_ .edgePaths .flowchart-link{stroke:rgb(143, 143, 143);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_12o\_ .marker{fill:rgb(143, 143, 143);stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_12o\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}用户 / Web 前端FastAPI API 层认证、权限、项目服务LangGraph 工作流编排PostgreSQLRedisS3 / MinIO 对象存储Agent 层剧本 Agent人物 Agent场景 Agent导演 Agent分镜 Agent视频 Agent音频 Agent剪辑 Agent评估 Agent模型注册表 / Provider 接口LLM ProviderImage ProviderVideo ProviderAudio ProviderVision ProviderCelery 任务队列GPU 推理 Worker媒体处理 Worker

这里要特别明确两个组件的分工：

- LangGraph：管理业务流程、智能体协作、状态流转、审核中断和恢复。
- Celery：执行耗时任务，例如图像生成、视频生成、音频生成、FFmpeg 合成和批量评估。

不要让两个系统同时承担同一套工作流调度职责。

### 1.4 技术栈建议

| 层次     | 推荐技术                             | 用途               |
| ------ | -------------------------------- | ---------------- |
| Web 前端 | Next.js、React、TypeScript         | 用户操作界面           |
| UI     | Tailwind CSS、shadcn/ui           | 页面组件             |
| 状态管理   | Zustand、TanStack Query           | 前端状态和请求          |
| 流程可视化  | React Flow                       | 分镜、工作流和人物关系      |
| 后端     | Python 3.12、FastAPI              | API 和业务服务        |
| 数据校验   | Pydantic 2                       | Agent 输入输出       |
| ORM    | SQLAlchemy 2                     | 数据访问             |
| 数据库    | PostgreSQL                       | 项目、人物、镜头、任务和版本   |
| 缓存和队列  | Redis                            | 缓存、Celery Broker |
| 工作流    | LangGraph                        | Agent 编排和审核      |
| 后台任务   | Celery                           | 模型调用和媒体处理        |
| 媒体处理   | FFmpeg、FFprobe、OpenCV            | 视频、音频、字幕合成       |
| 对象存储   | S3 / MinIO                       | 图片、视频、音频         |
| 部署     | Docker、Docker Compose、Nginx      | 开发和初期部署          |
| 测试     | pytest、Playwright                | 后端和前端测试          |
| 监控     | OpenTelemetry、Prometheus、Grafana | 日志、指标、追踪         |

建议先做模块化单体 + 独立 Worker，而不是一开始就拆成大量微服务。模块边界清晰，后续再按负载拆分。

## 2. 智能体体系设计

系统不应把所有职责放进一个“超级智能体”。建议采用一个总控 Agent，加上职责明确的专业 Agent。

| 智能体                    | 主要职责                    | 关键输出               |
| ---------------------- | ----------------------- | ------------------ |
| Orchestrator Agent     | 理解用户任务、安排工作流、协调其他 Agent | Workflow Plan      |
| Script Agent           | 小说解析、剧情提取、剧本改编          | Script、Story Event |
| Character Agent        | 人物提取、档案、关系、状态           | Character Profile  |
| Character Vision Agent | 分析人物上传图片                | Visual Description |
| Character Image Agent  | 生成人物设定图和视觉资产            | Character Images   |
| Scene Agent            | 场景提取、场景描述和参考图           | Scene Profile      |
| Director Agent         | 整体导演规划、节奏、视觉风格          | Directing Plan     |
| Storyboard Agent       | 镜头拆解、动作、运镜和镜头衔接         | Storyboard / Shot  |
| Prompt Agent           | 将结构化设定转成模型提示词           | Model Prompt       |
| Video Agent            | 视频生成、候选版本、重试            | Video Asset        |
| Audio Agent            | 配音、旁白、音乐、音效             | Audio Asset        |
| Editing Agent          | 镜头排序、字幕、音频混合和剪辑         | Editing Project    |
| Evaluation Agent       | 评估剧情、人物、画面、声音           | Quality Report     |

### 2.1 人物智能体需要独立设计

人物设定是整个平台的重要基础，不应仅仅依赖一个通用 Character Agent。

建议细分为：

- 人物提取：从小说和剧本识别人物。
- 人物描述：维护文字档案和属性。
- 人物图片理解：分析用户上传的参考图。
- 人物图片生成：头像、半身、全身、三视图。
- 人物服装：管理不同时间点、不同剧情阶段的服装。
- 人物表情：管理常见情绪和特殊表情。
- 人物关系：维护人物关系图。
- 人物状态：维护年龄、伤势、情绪、位置、持有物品等剧情状态。
- 人物一致性：检查图片、分镜和视频中的人物是否偏离设定。

### 2.2 智能体之间必须使用结构化数据

不要让 Agent 只通过自然语言互相传递关键数据。

例如分镜 Agent 输出应有固定 Schema：

```
{
  "shot_id": "shot_001",
  "scene_id": "scene_001",
  "characters": [
    {
      "character_id": "character_001",
      "costume_id": "costume_001",
      "state_id": "state_001",
      "action": "缓慢转身",
      "emotion": "警惕"
    }
  ],
  "camera": {
    "shot_type": "medium_shot",
    "movement": "slow_dolly_in",
    "angle": "eye_level"
  },
  "duration_seconds": 5,
  "dialogue": [],
  "visual_prompt": "",
  "negative_prompt": "",
  "reference_assets": []
}
```

每个 Agent 都应有独立的输入 Schema、输出 Schema、版本号和校验逻辑。输出不符合 Schema 时，先修复或重试，不要直接传给下游 Agent。

## 3. 模型配置：每个智能体独立配置文件

这是本项目必须优先落实的设计要求。

### 3.1 不要把模型名称写死在 Python 代码里

不推荐：

```
model = OpenAI(model="某个固定模型")
```

因为以后换模型时，可能需要修改很多 Agent 文件。

推荐：

```
config = model_registry.get_agent_config("character_description")model = provider_factory.create(config)
```

每个 Agent 只知道自己的配置 ID，不关心底层使用哪个供应商。

### 3.2 推荐配置目录

```
config/
├── app.yaml
├── environments/
│   ├── development.yaml
│   ├── staging.yaml
│   └── production.yaml
│
├── agents/
│   ├── orchestrator.yaml
│   ├── script.yaml
│   ├── character_extraction.yaml
│   ├── character_description.yaml
│   ├── character_vision.yaml
│   ├── character_image.yaml
│   ├── character_consistency.yaml
│   ├── scene.yaml
│   ├── director.yaml
│   ├── storyboard.yaml
│   ├── prompt.yaml
│   ├── video.yaml
│   ├── audio.yaml
│   ├── editing.yaml
│   └── evaluation.yaml
│
├── providers/
│   ├── llm.yaml
│   ├── vision.yaml
│   ├── image.yaml
│   ├── video.yaml
│   └── audio.yaml
│
├── workflows/
│   ├── novel_to_video.yaml
│   ├── character_creation.yaml
│   ├── storyboard_generation.yaml
│   └── video_generation.yaml
│
├── prompts/
│   ├── script/
│   ├── character/
│   ├── scene/
│   ├── director/
│   ├── storyboard/
│   ├── video/
│   └── evaluation/
│
└── schemas/
    ├── character.schema.json
    ├── scene.schema.json
    ├── storyboard.schema.json
    └── video_task.schema.json
```

每个智能体有单独 YAML 文件，模型供应商信息放在 Provider 配置中，避免重复写 API 地址和密钥。

### 3.3 Agent 配置文件示例

以下是推荐的配置形式，模型 ID 是可替换配置项。配置中的数值是初始调优建议，不是所有模型都支持的通用参数。

```

# config/agents/character_description.yaml

agent:
  id: character_description
  name: Character Description Agent
  enabled: true
  version: "1.0.0"

model:
  provider: openai
  model_id: gpt-6.1-sol
  capability: text_reasoning
  fallback:
    provider: openai
    model_id: gpt-6.1-terra

generation:
  temperature: 0.3
  max_output_tokens: 6000
  timeout_seconds: 120
  max_retries: 3

structured_output:
  enabled: true
  schema: character_profile
  validation_required: true

prompt:
  system: prompts/character/description_system.md
  user_template: prompts/character/description_user.md
  version: "1.0.0"

runtime:
  concurrency: 5
  cache_enabled: true
  human_review_required: true

evaluation:
  enabled: true
  checks:
    - completeness
    - source_consistency
    - contradiction
    - schema_validity

```

每个 Agent 的配置都应有相同的基本字段，但可以根据任务类型增加专属参数。

### 3.4 不同 Agent 的配置重点

| Agent                 | 重点配置                 |
| --------------------- | -------------------- |
| Orchestrator          | 推理能力、工具调用、任务规划       |
| Script                | 长上下文、结构化输出、剧情一致性     |
| Character Extraction  | 长文本处理、实体提取、结构化输出     |
| Character Description | 低随机性、事实追溯、结构化输出      |
| Character Vision      | 图片输入、视觉理解、图文联合分析     |
| Character Image       | 图像模型、参考图、尺寸、质量       |
| Character Consistency | 视觉理解、相似度阈值、参考资产      |
| Scene                 | 长文本理解、场景视觉描述         |
| Director              | 高质量推理、整体规划           |
| Storyboard            | 结构化输出、镜头逻辑           |
| Prompt                | 提示词优化、多模型适配          |
| Video                 | 视频模型、时长、分辨率、参考图、并发   |
| Audio                 | TTS、语音、音乐和音效模型       |
| Editing               | FFmpeg 参数、字幕、转场、音频混合 |
| Evaluation            | 视觉理解、规则评分、多维评估       |

### 3.5 模型参数必须经过 Provider 适配

不同供应商的参数不完全一致。不要把所有模型都强行套用 `temperature`、`top_p`、`seed` 等参数。

建议采用两层配置：

- `common`：超时、重试、最大输出、并发、预算、缓存。
- `provider_options`：对应供应商和模型支持的特殊参数。

Provider 负责检查参数是否受支持，不支持的参数应给出明确错误或按配置策略忽略，不能静默改变模型行为。

## 4. 推荐模型配置

模型推荐要分清楚两件事：模型能力推荐和工程部署推荐。一个系统不应该只依赖一家供应商，也不应该因为某个模型效果好，就让所有任务都调用它。

我建议采用“高能力模型负责复杂决策，中等成本模型负责常规结构化任务，专用生成模型负责图片、视频和声音”的组合。

### 4.1 大语言模型推荐

截至本方案编写时，OpenAI 官方模型目录将 GPT-6 Astra 定位为高复杂度任务模型，将 GPT-6.1 Sol 定位为较低成本的复杂工作模型，将 GPT-6.1 Terra 定位为高效率模型。具体模型 ID、参数和价格应在实际接入前再次验证。

[image](https://www.google.com/s2/favicons?domain=https://developers.openai.com\&sz=32)

OpenAI API



| 智能体                   | 推荐模型              | 推荐原因              | 备用策略            |
| --------------------- | ----------------- | ----------------- | --------------- |
| Orchestrator          | GPT-6 Astra       | 复杂任务规划和跨 Agent 协调 | GPT-6.1 Sol     |
| Script                | GPT-6 Astra / Sol | 长文本剧情理解、改编和推理     | GPT-6.1 Terra   |
| Character Extraction  | GPT-6.1 Sol       | 人物抽取、实体归纳和结构化输出   | GPT-6.1 Terra   |
| Character Description | GPT-6.1 Sol       | 人物档案生成，事实与推断区分    | GPT-6.1 Terra   |
| Character Vision      | 支持视觉输入的 GPT-6 系列  | 分析上传图片和文字联合设定     | 其他视觉模型 Provider |
| Scene                 | GPT-6.1 Sol       | 场景描述和资产规划         | GPT-6.1 Terra   |
| Director              | GPT-6 Astra       | 整体叙事、风格和镜头规划      | GPT-6.1 Sol     |
| Storyboard            | GPT-6.1 Sol       | 结构化镜头拆解           | GPT-6.1 Terra   |
| Prompt                | GPT-6.1 Terra     | 提示词生成和转换          | GPT-6.1 Sol     |
| Evaluation            | GPT-6.1 Sol       | 多维质量检查            | GPT-6 Astra     |

重要建议： 不要让所有 Agent 都使用最贵的模型。比如人物字段提取、提示词格式化、字幕检查，通常不需要调用最高级推理模型。复杂剧情改编、导演规划和疑难质量评估才更值得使用高能力模型。

模型选择应由离线测试集决定，而不是只凭模型名称或宣传指标决定。

### 4.2 图像模型推荐

人物图片生成是本项目的重点，建议把图像生成和图像理解分开。

| 任务       | 推荐方案                   | 说明            |
| -------- | ---------------------- | ------------- |
| 人物头像、定妆照 | GPT Image 2.5 系列       | 高质量人物设定和图片编辑  |
| 人物参考图编辑  | GPT Image 2.5 Sunburst | 更适合需要精细编辑的工作流 |
| 快速视觉草图   | GPT Image 2.5 Flare    | 用于快速生成和方案预览   |
| 三视图、表情图  | 图像模型 + 专用提示词模板         | 需要统一人物外观约束    |
| 本地可控生成   | ComfyUI + 兼容的开源图像模型    | 便于工作流、节点和模型扩展 |
| 上传图片理解   | 视觉语言模型                 | 分析外貌、服装和可见特征  |

OpenAI 官方图像文档当前列出了 GPT Image 2.5 Sunburst 和 Flare，并支持生成、编辑和多轮参考图工作流；Sunburst 偏向精细编辑，Flare 偏向快速生成。

[image](https://www.google.com/s2/favicons?domain=https://developers.openai.com\&sz=32)

OpenAI API+1



这里有一个关键工程问题：生成三视图不能只依靠一段文字提示词。

建议先生成并审核人物主视觉图，再将已确认的图片作为后续视图生成的参考。将人物面部、发型、服装、身材比例等约束写入统一的 Character Prompt Engine，并保存参考图片 ID、提示词版本和生成模型版本。

对于同一人物的不同图片，要保存资产之间的来源关系，例如：

```
character_001
  ├── profile_v1
  ├── portrait_v1
  ├── full_body_v1
  ├── turnaround_v1
  ├── expression_v1
  └── costume_v1
```

不能把不同生成结果都当成互不相关的图片。

### 4.3 视频模型推荐策略

视频模型变化快、调用限制和 API 能力差异较大，因此不要把某一个视频模型写成系统的固定依赖。

建议第一版先接入一个稳定的商业视频 API，再预留第二个供应商和本地视频模型适配器。

选择视频模型时，必须实测以下能力：

- 文本生成视频（Text-to-Video）。
- 图片生成视频（Image-to-Video）。
- 多张参考图或角色参考图。
- 首帧、尾帧控制。
- 视频时长和画幅选择。
- 生成任务状态查询。
- 失败重试和任务取消。
- 商业使用权限、内容限制和 API 稳定性。

推荐的架构：

| 方案         | 用途       | 建议                 |
| ---------- | -------- | ------------------ |
| 商业视频 API A | 主视频生成    | MVP 首选，先验证 API 和效果 |
| 商业视频 API B | 备用和效果对照  | 第二阶段接入             |
| Wan 系列本地模型 | 本地推理和实验  | 作为独立 GPU Worker    |
| 静态图动画      | 对话、旁白、过场 | 降低视频生成成本           |
| FFmpeg 合成  | 最终剪辑     | 作为稳定的媒体处理基础        |

此前讨论过 24GB 显存设备。建议把本地视频模型作为独立推理 Worker，先做显存、分辨率、时长和并发压测，不要假定 24GB 显存可以稳定运行所有模型配置。商业 API 和本地模型应共用 VideoProvider 接口，但各自保留不同参数和资源限制。

### 4.4 音频模型推荐

音频模块应拆分成：

- TTS：文本转语音。
- Voice Design：角色音色设计。
- Voice Management：人物声音资产管理。
- Music Generation：背景音乐生成。
- SFX：音效生成。
- ASR：语音识别和字幕时间戳。
- Audio Mixing：音量、混音和降噪。

可将 OpenAI TTS 作为一个候选 Provider。其官方文档提供语气、语速、情绪等控制能力，但当前文档也明确列出旧版 TTS 模型的弃用安排，因此应以实际接入时的官方支持模型为准。

[image](https://www.google.com/s2/favicons?domain=https://developers.openai.com\&sz=32)

OpenAI API



角色声音也要像人物图片一样有独立的 `character_voice_id`，并与人物档案和镜头对白绑定。克隆真实人物声音前必须取得合法授权和明确同意。

### 4.5 推荐的第一版模型组合

建议作为 MVP 初始配置

| 能力         | 初始配置                      |
| ---------- | ------------------------- |
| 复杂推理       | GPT-6 Astra               |
| 常规文本 Agent | GPT-6.1 Sol               |
| 快速文本任务     | GPT-6.1 Terra             |
| 图片理解       | 支持图像输入的 GPT-6 系列          |
| 人物图片生成     | GPT Image 2.5 Sunburst    |
| 快速图像草稿     | GPT Image 2.5 Flare       |
| 视频生成       | 一个经过 API 验证的商业视频 Provider |
| 本地视频实验     | Wan 系列 + ComfyUI          |
| 配音         | 当前可用的商业 TTS Provider      |
| 音频处理       | FFmpeg、librosa            |
| 字幕识别       | faster-whisper 或云端 ASR    |

这些是初始候选配置，不代表 API 已经接通或账号已具备调用权限。正式开发前应完成接口验证、费用测试、中文能力测试和输出质量测试。

## 5. 模型配置文件的完整设计

### 5.1 Provider 独立配置

例如：

```

# config/providers/llm.yaml

providers:
  openai:
    enabled: true
    api_key_env: OPENAI_API_KEY
    base_url_env: OPENAI_BASE_URL
    timeout_seconds: 120

  anthropic:
    enabled: false
    api_key_env: ANTHROPIC_API_KEY
    timeout_seconds: 120

  google:
    enabled: false
    api_key_env: GOOGLE_API_KEY
    timeout_seconds: 120

```

视频模型也单独配置：

```

# config/providers/video.yaml

providers:
  commercial_video_a:
    enabled: false
    api_key_env: VIDEO_A_API_KEY
    timeout_seconds: 900
    max_concurrency: 2

  commercial_video_b:
    enabled: false
    api_key_env: VIDEO_B_API_KEY
    timeout_seconds: 900
    max_concurrency: 2

  local_wan:
    enabled: false
    endpoint_env: WAN_WORKER_URL
    timeout_seconds: 1800
    max_concurrency: 1

```

这里的 `commercial_video_a` 和 `commercial_video_b` 是占位名称，接入真实供应商时再填入实际 Provider 和模型 ID。

### 5.2 每个 Agent 允许单独切换模型

例如，人物描述 Agent：

```
model:
  provider: openai
  model_id: gpt-6.1-sol
```

导演 Agent：

```
model:
  provider: openai
  model_id: gpt-6-astra
```

分镜 Agent：

```
model:
  provider: openai
  model_id: gpt-6.1-sol
```

人物图片 Agent：

```
model:
  provider: openai
  model_id: gpt-image-2.5-sunburst
```

视频 Agent：

```
model:
  provider: commercial_video_a
  model_id: YOUR_VERIFIED_VIDEO_MODEL_ID
```

这样，开发者只需要调整配置，就可以替换某个 Agent 的模型，而不必修改整个工作流。

### 5.3 配置管理必须有版本

建议数据库增加：

- `model_configs`：模型配置记录。
- `agent_configs`：Agent 配置记录。
- `prompt_templates`：提示词模板。
- `config_versions`：配置历史。
- `model_call_logs`：模型调用记录。
- `model_evaluations`：模型评估结果。

每个任务创建时固定记录使用的配置版本。否则开发者今天更改了模型配置，明天就无法解释为什么同一份小说生成结果不一样。

密钥不要放在 YAML 文件中。 YAML 只保存环境变量名，真正的密钥通过环境变量或 Secret Manager 注入。生产环境禁止把 API Key 提交到 Git。

## 6. 核心业务工作流

系统采用“自动执行 + 人工审核 + 局部返工”的模式。不是用户上传小说后就直接生成整部视频，而是将生产过程拆成可检查、可修改的阶段。

### 6.1 完整工作流

\#chatgpt-mermaid-\_r_167\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(13, 13, 13);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_167\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_167\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_167\_ .error-icon{fill:rgb(243, 243, 243);}#chatgpt-mermaid-\_r_167\_ .error-text{fill:rgb(13, 13, 13);stroke:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_167\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_167\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_167\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_167\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_167\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_167\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_167\_ .marker{fill:rgb(143, 143, 143);stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_167\_ .marker.cross{stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_167\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_167\_ p{margin:0;}#chatgpt-mermaid-\_r_167\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_167\_ .cluster-label text{fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_167\_ .cluster-label span{color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_167\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_167\_ .label text,#chatgpt-mermaid-\_r_167\_ span{fill:rgb(13, 13, 13);color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_167\_ .node rect,#chatgpt-mermaid-\_r_167\_ .node circle,#chatgpt-mermaid-\_r_167\_ .node ellipse,#chatgpt-mermaid-\_r_167\_ .node polygon,#chatgpt-mermaid-\_r_167\_ .node path{fill:rgb(222, 234, 251);stroke:rgb(83, 154, 248);stroke-width:1px;}#chatgpt-mermaid-\_r_167\_ .rough-node .label text,#chatgpt-mermaid-\_r_167\_ .node .label text,#chatgpt-mermaid-\_r_167\_ .image-shape .label,#chatgpt-mermaid-\_r_167\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_167\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_167\_ .rough-node .label,#chatgpt-mermaid-\_r_167\_ .node .label,#chatgpt-mermaid-\_r_167\_ .image-shape .label,#chatgpt-mermaid-\_r_167\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_167\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_167\_ .root .anchor path{fill:rgb(143, 143, 143)!important;stroke-width:0;stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_167\_ .arrowheadPath{fill:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_167\_ .edgePath .path{stroke:rgb(143, 143, 143);stroke-width:1px;}#chatgpt-mermaid-\_r_167\_ .flowchart-link{stroke:rgb(143, 143, 143);fill:none;}#chatgpt-mermaid-\_r_167\_ .edgeLabel{background-color:rgb(252, 252, 252);text-align:center;}#chatgpt-mermaid-\_r_167\_ .edgeLabel p{background-color:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_167\_ .edgeLabel rect{opacity:0.5;background-color:rgb(252, 252, 252);fill:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_167\_ .labelBkg{background-color:rgba(252, 252, 252, 0.5);}#chatgpt-mermaid-\_r_167\_ .cluster rect{fill:rgb(243, 243, 243);stroke:rgba(0, 0, 0, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_167\_ .cluster text{fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_167\_ .cluster span{color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_167\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(243, 243, 243);border:1px solid rgba(0, 0, 0, 0.1);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_167\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_167\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_167\_ .icon-shape,#chatgpt-mermaid-\_r_167\_ .image-shape{background-color:rgb(252, 252, 252);text-align:center;}#chatgpt-mermaid-\_r_167\_ .icon-shape p,#chatgpt-mermaid-\_r_167\_ .image-shape p{background-color:rgb(252, 252, 252);padding:2px;}#chatgpt-mermaid-\_r_167\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_167\_ .image-shape .label rect{opacity:0.5;background-color:rgb(252, 252, 252);fill:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_167\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_167\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_167\_ .node .neo-node{stroke:rgb(83, 154, 248);}#chatgpt-mermaid-\_r_167\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_167\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_167\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_167\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_167\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_167\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_167\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_167\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_167\_ [data-look="neo"].node .neo-line path{stroke:rgb(83, 154, 248);filter:none;}#chatgpt-mermaid-\_r_167\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_167\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_167\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_167\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_167\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_167\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_167\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_167\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(0, 79, 153);}#chatgpt-mermaid-\_r_167\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(0, 79, 153);}#chatgpt-mermaid-\_r_167\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_167\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_167\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(245, 250, 255);stroke:rgb(206, 219, 229);stroke-width:1px;}#chatgpt-mermaid-\_r_167\_ .node rect,#chatgpt-mermaid-\_r_167\_ .node circle,#chatgpt-mermaid-\_r_167\_ .node ellipse,#chatgpt-mermaid-\_r_167\_ .node polygon,#chatgpt-mermaid-\_r_167\_ .node path{fill:rgb(229, 243, 255);stroke:rgba(0, 0, 0, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_167\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_167\_ .mermaid-decision .label-container{fill:rgb(245, 250, 255);stroke:rgb(206, 219, 229);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_167\_ .edgePaths .flowchart-link{stroke:rgb(143, 143, 143);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_167\_ .marker{fill:rgb(143, 143, 143);stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_167\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}创建项目上传小说 / 剧本文本解析与章节切分Script Agent：剧情分析和改编剧本审核CharacterAgent：人物提取与设定SceneAgent：场景提取与设定人物和场景资产生成人物 / 场景审核Director Agent：导演规划Storyboard Agent：分镜生成分镜审核Video Agent：镜头视频生成镜头候选版本审核Audio Agent：配音 / 音乐 /音效Editing Agent：剪辑合成Evaluation Agent：质量评估最终审核导出 MP4修改通过修改通过修改通过局部重生成通过局部返工通过

### 6.2 每个阶段的输入和输出

| 阶段   | 输入           | 输出         | 用户操作   |
| ---- | ------------ | ---------- | ------ |
| 小说解析 | 原始文件         | 章节、段落、对白   | 检查解析   |
| 剧本改编 | 小说内容         | 剧本、事件、对白   | 修改剧情   |
| 人物设定 | 剧本、人物描述、参考图片 | 人物档案、人物图片  | 修改和确认  |
| 场景设定 | 剧本、地点信息      | 场景档案、场景图片  | 修改和确认  |
| 导演规划 | 剧本、人物、场景     | 风格、节奏、镜头规划 | 修改规划   |
| 分镜生成 | 导演规划         | 镜头列表和提示词   | 编辑镜头   |
| 视频生成 | 镜头、参考资产      | 视频候选       | 选片或重生成 |
| 音频生成 | 对白、人物声音设定    | 配音、音乐、音效   | 修改声音   |
| 剪辑合成 | 视频、音频、字幕     | 完整影片       | 调整时间线  |
| 质量评估 | 成片及项目数据      | 质量报告       | 最终审核   |

### 6.3 人物设定工作流

人物模块应支持三种入口：

1. 小说自动提取。
2. 用户手动输入文字。
3. 用户上传图片。

这三种方式最终都进入统一的 Character Profile 流程。

\#chatgpt-mermaid-\_r_16e\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(13, 13, 13);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_16e\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_16e\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_16e\_ .error-icon{fill:rgb(243, 243, 243);}#chatgpt-mermaid-\_r_16e\_ .error-text{fill:rgb(13, 13, 13);stroke:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_16e\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_16e\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_16e\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_16e\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_16e\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_16e\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_16e\_ .marker{fill:rgb(143, 143, 143);stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_16e\_ .marker.cross{stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_16e\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_16e\_ p{margin:0;}#chatgpt-mermaid-\_r_16e\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_16e\_ .cluster-label text{fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_16e\_ .cluster-label span{color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_16e\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_16e\_ .label text,#chatgpt-mermaid-\_r_16e\_ span{fill:rgb(13, 13, 13);color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_16e\_ .node rect,#chatgpt-mermaid-\_r_16e\_ .node circle,#chatgpt-mermaid-\_r_16e\_ .node ellipse,#chatgpt-mermaid-\_r_16e\_ .node polygon,#chatgpt-mermaid-\_r_16e\_ .node path{fill:rgb(222, 234, 251);stroke:rgb(83, 154, 248);stroke-width:1px;}#chatgpt-mermaid-\_r_16e\_ .rough-node .label text,#chatgpt-mermaid-\_r_16e\_ .node .label text,#chatgpt-mermaid-\_r_16e\_ .image-shape .label,#chatgpt-mermaid-\_r_16e\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_16e\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_16e\_ .rough-node .label,#chatgpt-mermaid-\_r_16e\_ .node .label,#chatgpt-mermaid-\_r_16e\_ .image-shape .label,#chatgpt-mermaid-\_r_16e\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_16e\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_16e\_ .root .anchor path{fill:rgb(143, 143, 143)!important;stroke-width:0;stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_16e\_ .arrowheadPath{fill:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_16e\_ .edgePath .path{stroke:rgb(143, 143, 143);stroke-width:1px;}#chatgpt-mermaid-\_r_16e\_ .flowchart-link{stroke:rgb(143, 143, 143);fill:none;}#chatgpt-mermaid-\_r_16e\_ .edgeLabel{background-color:rgb(252, 252, 252);text-align:center;}#chatgpt-mermaid-\_r_16e\_ .edgeLabel p{background-color:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_16e\_ .edgeLabel rect{opacity:0.5;background-color:rgb(252, 252, 252);fill:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_16e\_ .labelBkg{background-color:rgba(252, 252, 252, 0.5);}#chatgpt-mermaid-\_r_16e\_ .cluster rect{fill:rgb(243, 243, 243);stroke:rgba(0, 0, 0, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_16e\_ .cluster text{fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_16e\_ .cluster span{color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_16e\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(243, 243, 243);border:1px solid rgba(0, 0, 0, 0.1);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_16e\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_16e\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_16e\_ .icon-shape,#chatgpt-mermaid-\_r_16e\_ .image-shape{background-color:rgb(252, 252, 252);text-align:center;}#chatgpt-mermaid-\_r_16e\_ .icon-shape p,#chatgpt-mermaid-\_r_16e\_ .image-shape p{background-color:rgb(252, 252, 252);padding:2px;}#chatgpt-mermaid-\_r_16e\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_16e\_ .image-shape .label rect{opacity:0.5;background-color:rgb(252, 252, 252);fill:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_16e\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_16e\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_16e\_ .node .neo-node{stroke:rgb(83, 154, 248);}#chatgpt-mermaid-\_r_16e\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_16e\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_16e\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_16e\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_16e\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_16e\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_16e\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_16e\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_16e\_ [data-look="neo"].node .neo-line path{stroke:rgb(83, 154, 248);filter:none;}#chatgpt-mermaid-\_r_16e\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_16e\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_16e\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_16e\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_16e\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_16e\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_16e\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_16e\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(0, 79, 153);}#chatgpt-mermaid-\_r_16e\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(0, 79, 153);}#chatgpt-mermaid-\_r_16e\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_16e\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_16e\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(245, 250, 255);stroke:rgb(206, 219, 229);stroke-width:1px;}#chatgpt-mermaid-\_r_16e\_ .node rect,#chatgpt-mermaid-\_r_16e\_ .node circle,#chatgpt-mermaid-\_r_16e\_ .node ellipse,#chatgpt-mermaid-\_r_16e\_ .node polygon,#chatgpt-mermaid-\_r_16e\_ .node path{fill:rgb(229, 243, 255);stroke:rgba(0, 0, 0, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_16e\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_16e\_ .mermaid-decision .label-container{fill:rgb(245, 250, 255);stroke:rgb(206, 219, 229);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_16e\_ .edgePaths .flowchart-link{stroke:rgb(143, 143, 143);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_16e\_ .marker{fill:rgb(143, 143, 143);stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_16e\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}人物创建输入方式小说提取文字输入上传人物图片人物档案归一化视觉分析 Agent人物描述补全生成头像 / 全身图生成三视图 / 表情 / 服装人物审核保存人物正式版本绑定场景 / 分镜 / 视频修改确认

人物的核心原则是：一个人物只有一份正式档案，但可以拥有多个视觉版本和剧情状态版本。

例如，同一人物可以有不同年龄、服装和受伤状态，但这些都必须关联同一个 `character_id`，并且记录对应剧情时间点。

### 6.4 分镜和视频工作流

建议每个镜头都是独立任务，不要把整部视频当成一个大任务提交。

每个镜头保存：

- `shot_id`
- `scene_id`
- `character_ids`
- `reference_asset_ids`
- `storyboard_prompt`
- `video_prompt`
- `duration`
- `camera`
- `action`
- `dialogue`
- `generation_config_id`
- `video_versions`

例如，用户修改某个角色的发型，系统应先检索受影响的图片、分镜和视频镜头，标记需要重新生成的资产，而不是自动重新生成整部视频。

## 7. 数据库设计

建议采用 PostgreSQL 作为核心业务数据库，对象存储负责保存大型媒体文件。

### 7.1 核心业务表

| 模块    | 主要数据表                                                   |
| ----- | ------------------------------------------------------- |
| 用户和项目 | users、projects、project_members                          |
| 原始内容  | source_documents、story_chapters、story_paragraphs        |
| 剧情    | scripts、story_events、dialogues                          |
| 人物    | characters、character_profiles、character_traits          |
| 人物视觉  | character_assets、character_views、character_expressions  |
| 人物状态  | character_costumes、character_states、character_timelines |
| 人物关系  | character_relationships、character_appearances           |
| 场景    | scenes、scene_profiles、scene_assets                      |
| 导演规划  | directing_plans、visual_styles                           |
| 分镜    | storyboards、shots、shot_characters                       |
| 视频    | video_generations、video_versions                        |
| 音频    | character_voices、audio_tracks、sound_effects             |
| 剪辑    | editing_projects、timeline_tracks、timeline_clips         |
| 审核    | reviews、review_comments                                 |
| 任务    | tasks、task_events                                       |
| Agent | agent_runs、agent_messages                               |
| 模型配置  | model_configs、agent_configs、config_versions             |
| 提示词   | prompt_templates、prompt_versions                        |
| 评估    | evaluation_runs、evaluation_results                      |
| 版本    | asset_versions、project_versions                         |
| 工作流   | workflow_checkpoints、workflow_runs                      |

注意：`character_assets` 在原有设计中已经存在，应扩展其字段和关联，不要重复创建同名表。

### 7.2 数据关联设计

核心关联关系：

```
Project
 ├── SourceDocument
 ├── Script
 ├── Character
 │    ├── CharacterProfile
 │    ├── CharacterAsset
 │    ├── CharacterCostume
 │    ├── CharacterState
 │    └── CharacterRelationship
 ├── Scene
 │    └── SceneAsset
 ├── Storyboard
 │    └── Shot
 │         ├── ShotCharacter
 │         ├── VideoGeneration
 │         └── AudioTrack
 ├── EditingProject
 ├── Review
 └── WorkflowRun
```

### 7.3 媒体文件不要直接存入数据库

数据库保存：

- 文件 ID。
- 存储路径或对象存储 Key。
- 文件类型。
- 文件大小。
- 分辨率。
- 时长。
- 生成模型。
- 提示词版本。
- 关联人物、场景和镜头。
- 资产版本。

实际图片、音频和视频文件存放在 S3 或 MinIO。

### 7.4 必须支持版本管理

建议采用不可变版本策略：

- 用户确认的人物档案产生一个新版本。
- 修改人物图片产生一个新资产版本。
- 修改提示词产生一个新提示词版本。
- 重新生成视频产生一个新视频版本。
- 已经审核通过的版本不被直接覆盖。

这样可以回滚，也可以比较不同模型或配置生成的效果。

## 8. 工程目录结构

建议使用以下结构，尽量让后续开发者能明确知道应该在哪里增加功能。

```
ai-film-studio/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   └── v1/
│   │   ├── core/
│   │   │   ├── security.py
│   │   │   ├── permissions.py
│   │   │   └── exceptions.py
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── repositories/
│   │   ├── services/
│   │   ├── agents/
│   │   ├── workflows/
│   │   ├── providers/
│   │   │   ├── llm/
│   │   │   ├── vision/
│   │   │   ├── image/
│   │   │   ├── video/
│   │   │   └── audio/
│   │   ├── tasks/
│   │   ├── evaluators/
│   │   └── utils/
│   │
│   ├── migrations/
│   └── tests/
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   │   ├── projects/
│   │   ├── novels/
│   │   ├── scripts/
│   │   ├── characters/
│   │   ├── scenes/
│   │   ├── storyboards/
│   │   ├── video/
│   │   ├── audio/
│   │   ├── editing/
│   │   └── reviews/
│   ├── hooks/
│   ├── services/
│   └── stores/
│
├── config/
│   ├── agents/
│   ├── providers/
│   ├── workflows/
│   ├── prompts/
│   ├── schemas/
│   └── environments/
│
├── workers/
│   ├── gpu_worker/
│   └── media_worker/
│
├── deployment/
│   ├── docker/
│   ├── nginx/
│   └── monitoring/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── database/
│   ├── agents/
│   ├── model_configs/
│   ├── testing/
│   └── decisions/
│
├── scripts/
├── docker-compose.yml
├── .env.example
├── pyproject.toml
└── README.md
```

### 8.1 目录扩展规则

后续开发者新增一个 Agent 时，应遵循统一规范：

1. 在 `agents/` 增加 Agent 实现。
2. 在 `schemas/` 增加输入和输出结构。
3. 在 `config/agents/` 增加独立模型配置。
4. 在 `config/prompts/` 增加提示词模板。
5. 在 `workflows/` 注册工作流节点。
6. 在 `tests/` 增加测试。
7. 在 `docs/agents/` 增加说明文档。

新增模型供应商时，则增加 Provider 实现和 Provider 配置，不应修改每一个 Agent 的业务代码。

## 9. 前端功能页面设计

建议把前端拆成以下工作台。

| 页面    | 核心功能                       |
| ----- | -------------------------- |
| 项目首页  | 项目状态、生成进度、预算和任务            |
| 小说导入  | 文件上传、章节解析、内容检查             |
| 剧本工作台 | 剧情、对白、章节编辑                 |
| 人物中心  | 人物文字设定、图片、三视图、表情、服装        |
| 场景工作台 | 场景档案和场景图                   |
| 导演工作台 | 视觉风格、叙事节奏和镜头规划             |
| 分镜工作台 | 镜头卡片、提示词、动作和运镜             |
| 视频工作台 | 生成进度、候选视频、版本比较             |
| 音频工作台 | 配音、声音资产、音乐和音效              |
| 剪辑工作台 | 时间线、字幕、音轨和视频合成             |
| 质量评估  | 评估报告、问题定位和局部返工             |
| 模型配置  | Agent 模型、Provider、参数和提示词版本 |
| 系统管理  | 用户、权限、任务、日志和资源             |

特别建议增加模型配置管理页面。 这样开发者不必每次都直接修改 YAML 文件才能切换模型；可以先读取配置，再通过受权限控制的后台界面修改。配置修改后产生新版本，并支持回滚。

## 10. API 设计

API 统一使用 `/api/v1` 前缀，按资源划分。

| 模块    | 示例接口                                                |
| ----- | --------------------------------------------------- |
| 项目    | `POST /projects`、`GET /projects/{id}`               |
| 上传    | `POST /projects/{id}/upload`                        |
| 剧本    | `POST /projects/{id}/analyze`、`PATCH /scripts/{id}` |
| 人物    | `GET /projects/{id}/characters`                     |
| 人物生成  | `POST /characters/{id}/generate-images`             |
| 人物三视图 | `POST /characters/{id}/generate-views`              |
| 人物审核  | `POST /characters/{id}/approve`                     |
| 场景    | `GET /projects/{id}/scenes`                         |
| 导演    | `POST /projects/{id}/direct`                        |
| 分镜    | `POST /projects/{id}/storyboards`                   |
| 镜头修改  | `PATCH /shots/{id}`                                 |
| 视频生成  | `POST /shots/{id}/generate`                         |
| 视频版本  | `GET /shots/{id}/versions`                          |
| 音频    | `POST /projects/{id}/audio`                         |
| 剪辑    | `POST /projects/{id}/editing`                       |
| 导出    | `POST /projects/{id}/export`                        |
| 任务    | `GET /tasks/{id}`                                   |
| 审核    | `POST /reviews/{id}`                                |
| 模型配置  | `GET /admin/model-configs`                          |
| 配置更新  | `POST /admin/model-configs/{id}/versions`           |

长任务使用 WebSocket 或 SSE 推送状态。前端不能只显示一个“正在生成”，而应该能显示当前 Agent、任务阶段、完成比例、失败原因和预计后续步骤。

## 11. 科学的开发方法与项目管理

这一部分非常重要。建议采用领域驱动设计（DDD）+ 迭代式开发 + 测试驱动开发（TDD）+ 持续集成（CI）+ 数据驱动评估。

不要一开始就并行开发所有 Agent。那样容易出现接口不统一、数据库频繁修改、模块无法联调的问题。

### 11.1 第一阶段：需求和领域建模

先完成：

- 产品需求文档 PRD。
- 用户使用流程。
- 核心业务实体和状态机。
- Agent 职责和输入输出。
- 模型配置规范。
- API 规范。
- 数据库 ER 图。
- 系统架构图。
- 风险和验收标准。

每个功能要写成可验证的需求。例如：

“用户可以上传人物图片”太宽泛。

更合适的验收要求是：

- 用户可以上传 PNG、JPEG、WebP。
- 文件大小和尺寸有限制。
- 图片归属于指定项目和人物。
- 上传后能够看到预览。
- 视觉分析任务能追踪状态。
- 失败时能重新执行。
- 原始图片不会被覆盖。
- 其他项目用户无法访问该图片。

### 11.2 第二阶段：先定义接口，再并行开发

推荐先完成公共规范：

- Pydantic Schema。
- 数据库实体。
- Provider 接口。
- Agent 基类。
- 任务状态定义。
- 错误码。
- 配置文件 Schema。

然后才允许各个开发小组或编程 Agent 并行开发。

这样可减少后期返工。

### 11.3 第三阶段：测试驱动开发

每个模块至少有以下测试：

| 测试类别   | 检查内容                    |
| ------ | ----------------------- |
| 单元测试   | 单个函数、服务和数据校验            |
| 集成测试   | Agent、Provider、数据库之间的交互 |
| API 测试 | 请求、响应、权限、异常             |
| 工作流测试  | 正常路径、失败路径、人工审核恢复        |
| 前端测试   | 关键页面和交互                 |
| 端到端测试  | 从上传小说到导出视频              |
| 性能测试   | 并发、耗时、内存和显存             |
| 安全测试   | 文件访问、项目隔离、密钥泄漏          |

不要只测试“模型能否返回文字”，还要测试返回内容是否符合 Schema、是否忠实于原文、是否能被下游模块消费。

### 11.4 第四阶段：建立固定评估数据集

这是智能体项目容易忽略的部分。

建议准备一批固定测试素材：

- 5～10 段不同类型的小说。
- 20～50 个有代表性的人物。
- 10～20 个场景。
- 50～100 个分镜样例。
- 一组人物参考图片。
- 一组需要保持人物一致性的连续镜头。
- 一组中文配音和字幕样例。

这些数据用于测试模型和提示词更新后是否真正变好。

### 11.5 第五阶段：使用对照实验优化模型

每次优化只改变有限的变量。

例如测试人物描述 Agent：

- A 组：模型 A + 提示词版本 1。
- B 组：模型 B + 提示词版本 1。
- C 组：模型 A + 提示词版本 2。

对比：

- 人物属性提取准确率。
- 人物描述完整度。
- 原文事实一致性。
- 虚构信息比例。
- Schema 合格率。
- 平均耗时。
- 单次成本。

不要同时改变模型、提示词、温度和输入内容，否则很难判断是哪项修改带来了效果变化。

### 11.6 第六阶段：CI/CD 和版本管理

每次代码提交至少执行：

1. 代码格式检查。
2. 静态类型检查。
3. 单元测试。
4. Schema 校验。
5. API 集成测试。
6. Docker 构建。
7. 关键工作流回归测试。

建议所有重要设计决策写入 `docs/decisions/`，使用 Architecture Decision Records（ADR）记录为什么选用某项技术、放弃什么方案、未来什么条件下需要调整。

## 12. 开发阶段和排期

建议按可交付成果推进，而不是按“完成多少个 Agent”推进。

以下是一个小型团队的初步估算，不是保证工期。模型 API、视频生成能力、开发人数和前端剪辑复杂度都会影响实际时间。

| 阶段       | 预计周期  | 交付成果                  |
| -------- | ----- | --------------------- |
| 1. 需求和架构 | 1 周   | PRD、架构、Schema、ER 图    |
| 2. 基础工程  | 1 周   | 登录、项目、上传、数据库、任务系统     |
| 3. 小说和剧本 | 1～2 周 | 小说解析、剧情和剧本审核          |
| 4. 人物和场景 | 1～2 周 | 文字设定、图片设定、资产生成和审核     |
| 5. 导演和分镜 | 1～2 周 | 导演规划、镜头拆解和编辑          |
| 6. 视频生成  | 1～2 周 | 视频 Provider、镜头生成和版本管理 |
| 7. 音频和剪辑 | 1～2 周 | 配音、字幕、音轨、FFmpeg 合成    |
| 8. 评估和优化 | 1 周   | 质量评估、局部返工和回归测试        |
| 9. 部署和验收 | 1 周   | Docker 部署、监控、文档和验收    |

如果是一个开发者独立完成，建议把时间预期放宽，并优先完成可用的端到端 MVP，而不是一次性实现全部高级功能。

### 12.1 MVP 必须实现的功能

第一版只要能完整走通以下路径，就有实际价值：

1. 用户创建项目。
2. 上传小说。
3. AI 提取剧情、人物和场景。
4. 用户编辑人物文字设定。
5. 用户上传人物参考图片。
6. AI 生成人物基础设定图。
7. AI 生成场景和分镜。
8. 调用视频 API 生成若干镜头。
9. 生成配音和字幕。
10. FFmpeg 合成视频。
11. 用户审核、修改和重新生成。
12. 导出 MP4。

### 12.2 第二版增加的能力

- 人物三视图、表情和服装资产。
- 人物关系图和剧情时间线。
- 多视频模型切换。
- 视频参考图控制。
- 多镜头并行生成。
- 角色声音管理。
- 时间线剪辑工作台。
- 自动质量评估。
- 模型成本统计。

### 12.3 第三版增加的能力

- 多风格、多画幅和多分辨率。
- 复杂人物动作和多人交互。
- 更完整的镜头连续性分析。
- 模型自动路由和质量成本优化。
- 用户自定义 Agent。
- 工作流可视化编辑器。
- 插件化工具市场。
- 多用户协作和项目权限。

## 13. 为开发者预留的扩展空间

这一部分是整个架构能否长期维护的关键。

建议在第一版就预留扩展接口，但不要第一版就把所有高级功能实现出来。

### 13.1 预留五类扩展接口

| 扩展方向  | 预留接口               | 后续可以增加的功能            |
| ----- | ------------------ | -------------------- |
| 智能体扩展 | Agent Interface    | 新增剧本分析、导演、审核等 Agent  |
| 模型扩展  | Provider Interface | 接入新的 LLM、图像、视频和音频模型  |
| 工作流扩展 | Workflow Registry  | 新增漫画转视频、短剧生成、广告生成    |
| 工具扩展  | Tool Registry      | 新增搜索、素材库、字幕和剪辑工具     |
| 前端扩展  | Feature Modules    | 新增角色编辑器、镜头编辑器、时间线编辑器 |

### 13.2 Agent 统一基类

所有 Agent 应遵循统一接口：

```
class BaseAgent:    async def validate_input(self, input_data):        ...    async def load_config(self):        ...    async def execute(self, input_data, context):        ...    async def validate_output(self, output_data):        ...    async def evaluate(self, output_data):        ...
```

新增 Agent 时只需要实现对应业务逻辑，不必重新开发模型连接、日志、重试、任务状态和配置读取。

### 13.3 Provider 统一接口

不同模型供应商通过统一接口对外提供能力：

```
class ImageProvider:    async def generate(self, request):        ...    async def edit(self, request):        ...    async def generate_from_reference(self, request):        ...    async def get_task_status(self, task_id):        ...
```

视频 Provider：

```
class VideoProvider:    async def generate(self, request):        ...    async def generate_from_image(self, request):        ...    async def get_task_status(self, task_id):        ...    async def cancel(self, task_id):        ...
```

注意：并不是所有视频供应商都支持所有方法。具体能力应通过 `capabilities` 声明，调用前检查，而不是假设每个模型都支持参考图、首尾帧或任务取消。

### 13.4 工作流插件化

例如未来开发者增加“漫画转视频”功能，不应该改写原有小说转视频工作流。

建议：

```
workflows/
├── novel_to_video/
├── script_to_video/
├── comic_to_video/
├── image_to_video/
└── advertisement_to_video/
```

不同工作流共享人物系统、场景系统、模型系统、视频系统和剪辑系统。

### 13.5 开发者可调节的配置项

建议开放以下配置：

- 每个 Agent 使用哪个模型。
- 每个 Agent 使用哪个提示词版本。
- 每个 Agent 的最大输出长度。
- 每个 Agent 的超时时间和重试次数。
- 视频生成的最大并发数。
- 图片生成的质量等级。
- 每个项目的预算上限。
- 每个工作流的人工审核节点。
- 每个 Agent 的备用模型。
- 质量评估阈值。
- 不同模型的优先级。

但生产环境配置修改需要权限控制、版本记录、测试和回滚。不要允许普通项目用户直接修改系统级 API Key 或任意执行 Python 代码。

## 14. 部署和硬件资源规划

### 14.1 推荐部署结构

\#chatgpt-mermaid-\_r_180\_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(13, 13, 13);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-\_r_180\_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_180\_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-\_r_180\_ .error-icon{fill:rgb(243, 243, 243);}#chatgpt-mermaid-\_r_180\_ .error-text{fill:rgb(13, 13, 13);stroke:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_180\_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-\_r_180\_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-\_r_180\_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-\_r_180\_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-\_r_180\_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-\_r_180\_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-\_r_180\_ .marker{fill:rgb(143, 143, 143);stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_180\_ .marker.cross{stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_180\_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-\_r_180\_ p{margin:0;}#chatgpt-mermaid-\_r_180\_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_180\_ .cluster-label text{fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_180\_ .cluster-label span{color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_180\_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-\_r_180\_ .label text,#chatgpt-mermaid-\_r_180\_ span{fill:rgb(13, 13, 13);color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_180\_ .node rect,#chatgpt-mermaid-\_r_180\_ .node circle,#chatgpt-mermaid-\_r_180\_ .node ellipse,#chatgpt-mermaid-\_r_180\_ .node polygon,#chatgpt-mermaid-\_r_180\_ .node path{fill:rgb(222, 234, 251);stroke:rgb(83, 154, 248);stroke-width:1px;}#chatgpt-mermaid-\_r_180\_ .rough-node .label text,#chatgpt-mermaid-\_r_180\_ .node .label text,#chatgpt-mermaid-\_r_180\_ .image-shape .label,#chatgpt-mermaid-\_r_180\_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-\_r_180\_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-\_r_180\_ .rough-node .label,#chatgpt-mermaid-\_r_180\_ .node .label,#chatgpt-mermaid-\_r_180\_ .image-shape .label,#chatgpt-mermaid-\_r_180\_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-\_r_180\_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-\_r_180\_ .root .anchor path{fill:rgb(143, 143, 143)!important;stroke-width:0;stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_180\_ .arrowheadPath{fill:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_180\_ .edgePath .path{stroke:rgb(143, 143, 143);stroke-width:1px;}#chatgpt-mermaid-\_r_180\_ .flowchart-link{stroke:rgb(143, 143, 143);fill:none;}#chatgpt-mermaid-\_r_180\_ .edgeLabel{background-color:rgb(252, 252, 252);text-align:center;}#chatgpt-mermaid-\_r_180\_ .edgeLabel p{background-color:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_180\_ .edgeLabel rect{opacity:0.5;background-color:rgb(252, 252, 252);fill:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_180\_ .labelBkg{background-color:rgba(252, 252, 252, 0.5);}#chatgpt-mermaid-\_r_180\_ .cluster rect{fill:rgb(243, 243, 243);stroke:rgba(0, 0, 0, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_180\_ .cluster text{fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_180\_ .cluster span{color:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_180\_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(243, 243, 243);border:1px solid rgba(0, 0, 0, 0.1);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-\_r_180\_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(13, 13, 13);}#chatgpt-mermaid-\_r_180\_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-\_r_180\_ .icon-shape,#chatgpt-mermaid-\_r_180\_ .image-shape{background-color:rgb(252, 252, 252);text-align:center;}#chatgpt-mermaid-\_r_180\_ .icon-shape p,#chatgpt-mermaid-\_r_180\_ .image-shape p{background-color:rgb(252, 252, 252);padding:2px;}#chatgpt-mermaid-\_r_180\_ .icon-shape .label rect,#chatgpt-mermaid-\_r_180\_ .image-shape .label rect{opacity:0.5;background-color:rgb(252, 252, 252);fill:rgb(252, 252, 252);}#chatgpt-mermaid-\_r_180\_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-\_r_180\_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-\_r_180\_ .node .neo-node{stroke:rgb(83, 154, 248);}#chatgpt-mermaid-\_r_180\_ [data-look="neo"].node rect,#chatgpt-mermaid-\_r_180\_ [data-look="neo"].cluster rect,#chatgpt-mermaid-\_r_180\_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-\_r_180\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_180\_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-\_r_180\_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-\_r_180\_-gradient);stroke-width:1px;}#chatgpt-mermaid-\_r_180\_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_180\_ [data-look="neo"].node .neo-line path{stroke:rgb(83, 154, 248);filter:none;}#chatgpt-mermaid-\_r_180\_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-\_r_180\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_180\_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-\_r_180\_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-\_r_180\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_180\_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-\_r_180\_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-\_r_180\_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(0, 79, 153);}#chatgpt-mermaid-\_r_180\_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(0, 79, 153);}#chatgpt-mermaid-\_r_180\_ .node tspan[font-weight="normal"],#chatgpt-mermaid-\_r_180\_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-\_r_180\_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(245, 250, 255);stroke:rgb(206, 219, 229);stroke-width:1px;}#chatgpt-mermaid-\_r_180\_ .node rect,#chatgpt-mermaid-\_r_180\_ .node circle,#chatgpt-mermaid-\_r_180\_ .node ellipse,#chatgpt-mermaid-\_r_180\_ .node polygon,#chatgpt-mermaid-\_r_180\_ .node path{fill:rgb(229, 243, 255);stroke:rgba(0, 0, 0, 0.1);stroke-width:1px;}#chatgpt-mermaid-\_r_180\_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-\_r_180\_ .mermaid-decision .label-container{fill:rgb(245, 250, 255);stroke:rgb(206, 219, 229);stroke-dasharray:2,2;}#chatgpt-mermaid-\_r_180\_ .edgePaths .flowchart-link{stroke:rgb(143, 143, 143);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-\_r_180\_ .marker{fill:rgb(143, 143, 143);stroke:rgb(143, 143, 143);}#chatgpt-mermaid-\_r_180\_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}用户浏览器NginxNext.jsFastAPIPostgreSQLRedisMinIO / S3Celery QueueLLM / API WorkerGPU WorkerMedia Worker本地生成模型外部模型 APIFFmpeg

### 14.2 24GB 显存设备的使用建议

如果仍使用此前讨论过的 24GB 显存 GPU，建议：

- 将 GPU 推理和 Web/API 服务分开。
- 不要让多个大型视频任务无控制地同时占用显存。
- 先用小分辨率和短时长做推理测试。
- 对本地模型配置最大并发为 1，经过压测后再调整。
- 图像生成、视频生成、视觉分析应有独立资源队列。
- 采用任务优先级和 GPU 资源锁。
- 视频生成失败时，不应无限重试。

24GB 显存不应被视为能够运行任意大型视频模型的保证。必须以具体模型权重、精度、显存优化方式、输入尺寸和上下文长度进行实测。

### 14.3 开发和生产环境分离

建议至少准备三个环境：

| 环境          | 用途                |
| ----------- | ----------------- |
| Development | 开发者本地开发和单元测试      |
| Staging     | 模型 API 联调、完整工作流测试 |
| Production  | 正式用户和实际生成任务       |

不同环境使用不同数据库、对象存储桶和 API 密钥。

## 15. 质量评估和验收标准

不能只以“能否生成视频”判断系统是否开发成功。

应该建立量化指标，并通过固定测试集进行验收。

以下是建议的初始目标，不是已经实现或保证达到的模型能力。

| 指标              | 初始验收目标    | 验证方法        |
| --------------- | --------- | ----------- |
| 小说解析完整率         | ≥95%      | 人工标注测试集     |
| 人物信息抽取准确率       | ≥90%      | 人工标注对照      |
| 人物档案 Schema 合格率 | ≥98%      | 自动校验        |
| 场景信息抽取准确率       | ≥90%      | 人工标注对照      |
| 分镜 Schema 合格率   | ≥98%      | 自动校验        |
| 任务状态记录完整率       | ≥99%      | 后端任务日志      |
| 视频合成成功率         | ≥98%      | 自动化测试       |
| 任务失败恢复成功率       | ≥95%      | 故障注入测试      |
| 人物视觉一致性         | 建立基线并持续提升 | 人工盲评 + 视觉指标 |
| 剧情一致性           | 建立基线并持续提升 | 人工评分 + 规则检查 |

人物一致性尤其不能只看人脸相似度。还应检查发型、服装、年龄状态、身体特征、配饰等信息，并结合镜头连续性人工评价。

### 15.1 视频质量评估维度

建议 Evaluation Agent 输出：

```
{
  "shot_id": "shot_001",
  "scores": {
    "story_consistency": 0.92,
    "character_consistency": 0.85,
    "scene_consistency": 0.90,
    "motion_quality": 0.88,
    "visual_quality": 0.91,
    "audio_quality": 0.95
  },
  "issues": [
    {
      "type": "character_costume_mismatch",
      "severity": "medium",
      "description": "人物服装与设定不一致"
    }
  ],
  "recommendation": "regenerate_shot"
}
```

评分需要结合人工标注校准，不能直接把模型自评的分数当成客观质量。

## 16. 安全、成本和运维要求

### 安全

- 项目数据按用户和项目隔离。
- 上传文件检查格式、大小和内容。
- API Key 仅保存在服务端。
- 用户不能访问其他项目的媒体文件。
- 对小说和上传图片进行权限管理。
- 保存用户审核记录和关键操作日志。
- 确保用户有权使用上传的小说、图片、声音和素材。
- 真实人物肖像、声音克隆应取得相应授权。

### 成本控制

建议每个项目记录：

- LLM 调用成本。
- 图片生成成本。
- 视频生成成本。
- 音频生成成本。
- 媒体处理资源消耗。
- 失败任务成本。
- 单个镜头平均生成成本。
- 单分钟成片平均成本。

设置项目预算、任务预算和模型调用上限。视频生成通常是成本较高的部分，因此推荐先生成低成本预览，通过审核后再生成最终版本。

### 运维

- 所有后台任务有唯一 Task ID。
- 每个任务记录开始时间、结束时间和状态。
- 支持失败重试和人工重新执行。
- 对模型 API 错误、限流和超时进行分类。
- 采用指数退避重试。
- 设置任务最大执行次数。
- 支持任务取消和资源释放。
- 对数据库、对象存储和配置定期备份。

## 17. 最终开发验收清单

建议将下面的清单作为正式项目验收依据。

项目验收进度

### 0/37

1\. 基础平台

用户登录、注册和权限管理

项目创建、编辑和删除

小说文件上传和解析

PostgreSQL 和对象存储正常工作

后台任务和任务进度可追踪

2\. 人物和场景

支持文字创建人物设定

支持上传人物参考图片

支持小说自动提取人物

支持 AI 生成人物档案

支持人物头像、全身图和三视图

支持人物服装、表情和剧情状态

支持场景描述和场景参考图

人物和场景资产支持版本管理

3\. 剧本和分镜

支持剧情分析和剧本改编

支持人物关系和事件提取

支持导演规划

支持分镜自动生成

支持分镜手动修改

镜头引用人物和场景的正式资产

4\. 视频和音频

支持至少一个视频模型 Provider

支持镜头独立生成和重生成

支持视频候选版本管理

支持人物配音和旁白

支持字幕生成

支持 FFmpeg 合成和 MP4 导出

5\. 模型和扩展

每个 Agent 有独立模型配置文件

Provider 与 Agent 业务逻辑解耦

模型参数和提示词支持版本管理

支持备用模型配置

支持新增 Agent 和工作流

支持模型调用成本统计

6\. 质量和运维

支持关键阶段人工审核

支持失败重试和断点恢复

支持人物一致性检查

支持视频质量评估

支持项目数据隔离

支持日志、监控和备份

重置验收清单

## 18. 最终实施建议

我建议严格按照以下优先级推进：

第一优先级

先建立稳定的工程底座

数据库、模型配置管理、Provider 接口、Agent 基类、任务队列、版本管理、审核机制。

第二优先级

完成最小可用的视频生产链路

小说解析 → 人物设定 → 场景设定 → 分镜 → 视频 → 配音 → 剪辑 → 导出。

第三优先级

完善人物和视频质量

人物三视图、表情和服装，人物一致性，镜头连续性，质量评估和局部返工。

建设长期扩展能力

多模型路由、自定义 Agent、工作流编辑器、多用户协作和插件系统。

最关键的架构决定是：不要把“智能体”和“模型”绑定在一起。

智能体负责业务能力，模型 Provider 负责调用模型，配置文件负责选择模型，工作流负责安排执行顺序，数据库负责保存状态和版本。这样模型更新、供应商更换、开发者增加功能时，系统都不需要推倒重来。

建议将这份方案作为项目的总体技术基线，后续开发者在此基础上提交架构变更记录（ADR），而不是随意修改核心接口。正式进入开发前，再完成一次模型 API 可用性、实际成本、中文质量和 24GB GPU 部署能力验证。