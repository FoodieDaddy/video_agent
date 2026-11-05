/** 导演表单的纯状态规则，展示与提交入口共用，不发请求、不修改草稿。 */
const TERMINAL_TASKS = new Set(['succeeded', 'failed', 'cancelled']);

/** 任务日志保留诊断细节，创作页优先给出可采取行动的失败说明。 */
export function planningTaskError(error) {
  const text = typeof error === 'string' ? error : error?.message || '任务未完成，请查看任务日志。';
  if (/RemoteProtocolError|ReadTimeout|ConnectTimeout|ConnectError|ReadError|WriteError/.test(text))
    return '模型连接暂时中断，创作内容已保留，可以稍后重试。';
  if (/failed to produce schema/.test(text))
    return '模型未返回可用的方案，创作要求已保留，请重试或调整要求。';
  return text;
}

export function directingFormState({ workspace, draft = {}, scriptDraft, isDemo = false } = {}) {
  const script = workspace?.script;
  const latestTask = (workspace?.tasks || []).find((task) => task.type === 'directing');
  const completedCurrent =
    !isDemo &&
    latestTask?.status === 'succeeded' &&
    latestTask.result?.plan_id === workspace?.directing?.id &&
    workspace?.directing?.source_status === 'current';
  const latestFailed = latestTask?.status === 'failed';
  const missingScript = !script;
  const hasUnsavedScript = !!(scriptDraft?.dirty || scriptDraft?.saving);
  const busy = !!(
    draft.submitting ||
    (workspace?.tasks || []).some(
      (task) => task.type === 'directing' && !TERMINAL_TASKS.has(task.status),
    )
  );
  const shots = Number(draft.shots_target ?? 6);
  const invalidShots = !Number.isInteger(shots) || shots < 1 || shots > 120;
  const invalidInstruction = String(draft.instruction || '').length > 8000;
  const blocked = missingScript || hasUnsavedScript || busy || invalidShots || invalidInstruction;
  const message = missingScript
    ? '先保存一版剧本，再制定导演方案。'
    : scriptDraft?.saving
      ? '剧本正在保存，请等待完成后再生成导演方案。'
      : scriptDraft?.dirty
        ? '剧本有未保存修改，请先保存，再基于新版本生成。'
        : busy
          ? '导演方案正在生成，可在任务记录中查看进度。'
          : invalidShots
            ? '目标镜头数需要是 1 至 120 的整数。'
            : invalidInstruction
              ? '创作要求最多 8000 个字符，请精简后再提交。'
              : draft.error || latestFailed
                ? '生成未完成，创作要求已保留。核对后可以重试。'
                : isDemo
                  ? '演示操作只记录模拟任务，不调用模型或创建真实方案。'
                  : completedCurrent
                    ? workspace.directing.approved
                      ? `导演方案 V${workspace.directing.version} 已随分镜确认；新版本需要重新核对。`
                      : `导演方案 V${workspace.directing.version} 已生成，核对后可前往分镜。`
                    : `将基于已保存剧本 V${script.version} 生成，提交前会再次确认。`;
  return {
    busy,
    blocked,
    message,
    label: busy
      ? '正在生成…'
      : isDemo
        ? '确认模拟操作'
        : draft.error || latestFailed
          ? '重试生成方案'
          : workspace?.directing
            ? '生成新版本'
            : '生成导演方案',
    missingScript,
    hasUnsavedScript,
    invalidShots,
    invalidInstruction,
    scriptVersion: script?.version ?? null,
  };
}
