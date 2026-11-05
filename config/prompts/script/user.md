本次操作：$operation
用户要求（为空时遵守该操作的默认规则）：$instruction

作品标题（可选）：$title_hint
类型：$genre
语言：$language
章节数量：$chapter_count

章节内容：
$chapters

原文节选（供核对语气与细节）：
$source_excerpt

完整现稿正文（polish/continue 的权威依据，开始）：
$script_text
完整现稿正文（结束）。

现有剧本结构上下文（仅供对照，不代替正文）：
$current_script

请按本次操作返回 JSON：title / script_text / logline / synopsis / genre / tone / chapters / events / dialogues。
analyze 与 polish 的 script_text 是完整最终正文；continue 的 script_text 仅包含非空新增片段，应用会保留原稿再追加，禁止重复原稿。其余结构字段始终描述操作后的完整故事。
