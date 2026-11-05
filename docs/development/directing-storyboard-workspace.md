# 模块四：导演、分镜与第二轮审核

范围以用户明确选择为准：导演规划＋分镜创作＋第二轮审核。编号对应见[交付模块对照](module-delivery-map.md)。继续使用现有模块化单体、Provider、任务队列与审核服务，不新增执行框架或数据库列。

## 页面与操作

1. 在项目保存剧本后，进入导演页，填写目标镜头数与创作要求，确认文字模型调用。成功追加导演方案版本。
2. 导演页结构化展示视觉风格、色彩、光线、镜头语言、叙事节奏、镜头策略与连续性；历史只读，来源状态由后端判定。
3. 在分镜页基于当前有效导演方案生成镜头。基础提示词随分镜生成；逐镜精化为可选额外调用，新页面默认关闭，旧通用 API／工作流仍保留原默认。
4. 可以编辑当前镜头的描述、动作、景别、运镜、角度、焦距、时长、关联场景、已有台词和提示词；历史分镜只读。
5. 核对后提交第二轮审核，查看绑定版本与镜头数，明确通过或退回。保存结论不自动续跑图片、视频或音频。

长页的步骤导航保持可见，手机可以直接跳至创作要求、审核或历史，并返回方案主区。键盘焦点随跳转移动；任务接受后显示排队状态，错误与历史任务保留。

## API 契约

| 方法与路径 | 行为 |
| --- | --- |
| POST `/api/v1/projects/{id}/direct` | 可选 `base_script_id / instruction / shots_target`；旧空请求体兼容 |
| GET `/api/v1/projects/{id}/directing` | 最新方案与版本摘要 |
| GET `/api/v1/directing-plans/{plan_id}` | 单版本完整方案，按所属项目校验权限 |
| POST `/api/v1/projects/{id}/storyboards` | 可选 `base_script_id / base_plan_id / refine_prompts`；旧空请求体兼容 |
| GET `/api/v1/projects/{id}/storyboards` | 最新分镜、完整镜头及历史摘要 |
| GET `/api/v1/storyboards/{board_id}` | 指定分镜的完整历史内容 |
| GET／PATCH `/api/v1/shots/{shot_id}` | 当前镜头读取／编辑；PATCH 可携带 `base_storyboard_id / base_shot_fingerprint` |
| POST `/api/v1/projects/{id}/storyboards/{board_id}/review` | 提交绑定当前内容的第二审核 |
| POST `/api/v1/reviews/{review_id}` | 明确通过／退回；新版页面始终发送 `resume_workflow=false` |

导演目标数为 1～120 的整数，创作要求最多 8000 字符。请求目标和模型给出的规划值分别记录，不用前端数值冒充实际输出。

## 来源、版本与镜头编辑

导演内容保存服务端生成的 `source_script={id,version,title,fingerprint}` 和 `generation_request`。客户端和模型不能伪造这些来源。排队时冻结脚本指纹，执行前后再次核对；同一 ID 的旧 PATCH 原位改文也会使基线失效。

导演、分镜、版本摘要返回 `source_status=current|stale|unknown`。导演来源核对剧本；分镜还核对所绑定导演与当前导演。旧记录缺来源标为 unknown，不能推断为当前有效。

导演生成和分镜生成追加版本。手动镜头编辑在当前分镜的 Shot 行上执行，不创建新 Storyboard；其他历史分镜的镜头保持不变。`edit_fingerprint` 用于检测同版本并发编辑。真实内容变化才撤销镜头和分镜批准，同值保存保留原批准；时长按合法正数保存，不静默取整或夹到 0.5 秒。

旧客户端可以省略乐观字段，因此仍可能发生最后写入覆盖；新版编辑器始终携带两个基线字段。这不是任意并发或分布式场景的完整事务治理。

## 第二轮审核

`decision.storyboard_snapshot` 保存服务端的分镜身份、导演身份／指纹、剧本来源及镜头内容指纹。它用于核验送审内容，不等于保存所有镜头正文的完整副本。

独立提审使用 `target_type=storyboard / target_id=board.id`。正式工作流保留 `workflow_node` 目标语义，真实分镜身份由 `target_snapshot.storyboard_id` 绑定。页面支持两种形式，不凭当前工作区猜测历史目标。

批准前核对快照：若内容、版本或来源变化，返回 409，原 pending 与结论保持不变；用户可以明确退回、修改并重新提审。批准只更新快照所对应的导演、分镜和镜头。批准本身改变状态不会使内容指纹失效；批准后再修改则须重新审核。

没有单独导演审核关卡。页面及检查均停在第二关；完整工作流后续是否继续，由用户另行发起。

## 模型与失败边界

提示词使用完整保存正文。没有人物／场景档案时，不伪造档案 ID 或场景引用；可以在画面描述中表达内容。有引用时必须属于当前项目。

Schema 拒绝空风格、空镜头、空描述及非法／非有限时长，不补造占位镜头冒充成功。模型完成后发生基线冲突，不保存陈旧产物；已完成请求的审计与预算按用例边界保留。

LLM 的 HTTP 传输异常统一为安全的 ProviderError，交给既有 Agent 重试预算处理；Adapter 自身不额外重试。无响应的传输失败不能推算供应商用量或费用。成功模型日志是响应汇总，不能将其条数等同全部 HTTP 尝试数。

## 独立检查

```bash
uv run --frozen --extra dev python scripts/checks/module4_directing_storyboard.py --offline
uv run --frozen --extra dev python scripts/checks/module4_directing_storyboard.py \
  --max-tokens 4096 --timeout 150 --report-json /tmp/module4-live.json
```

默认真实模式自动读取根目录 `.env` 和现有 YAML；上游采用 mock 夹具，真实目标为导演与分镜各两次，不运行额外提示词精化或媒体生成。13 组包括来源、历史、乐观编辑、Schema、第二关拒绝／过期／重新提审及审计。完整通过不接受必要 SKIP，沙箱结束释放，`--keep` 仅保留本次隔离证据。
