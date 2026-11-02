视频生成代理（Video Agent）。

该 Agent 不调用语言模型，只负责把分镜中已确认的提示词、时长、参考图转发给配置的视频生成 Provider。
`prompt.system` 与 `prompt.user_template` 仅用于管理端展示与人工核对，不会发送给语言模型。
