/** 分镜与第二轮审核的纯状态规则；不推断未记录来源，不执行任务或审批。 */
const TERMINAL_TASKS = new Set(['succeeded', 'failed', 'cancelled']);

export function storyboardFormState({ workspace, draft = {}, scriptDraft, isDemo = false } = {}) {
  const missingScript = !workspace?.script;
  const latestTask = (workspace?.tasks || []).find((task) => task.type === 'storyboard');
  const latestFailed = latestTask?.status === 'failed';
  const completedCurrent =
    !isDemo &&
    latestTask?.status === 'succeeded' &&
    latestTask.result?.storyboard_id === workspace?.storyboard?.id &&
    workspace?.storyboard?.source_status === 'current';
  const missingDirector = !workspace?.directing;
  const unverifiedDirector =
    !missingDirector && !isDemo && workspace.directing.source_status !== 'current';
  const hasUnsavedScript = !!(scriptDraft?.dirty || scriptDraft?.saving);
  const reviewSubmitting = !!draft.reviewSubmitting;
  const busy = !!(
    draft.submitting ||
    (workspace?.tasks || []).some(
      (task) => task.type === 'storyboard' && !TERMINAL_TASKS.has(task.status),
    )
  );
  const blocked =
    missingScript ||
    missingDirector ||
    unverifiedDirector ||
    hasUnsavedScript ||
    busy ||
    reviewSubmitting;
  const message = missingScript
    ? '先保存一版剧本，再准备分镜。'
    : scriptDraft?.saving
      ? '剧本正在保存，请等待完成后再生成分镜。'
      : scriptDraft?.dirty
        ? '剧本有未保存修改，请先保存并核对导演方案。'
        : missingDirector
          ? '先生成导演方案，再将故事拆解为镜头。'
          : unverifiedDirector
            ? '导演方案的剧本来源已变化或未记录，请先核对并重新生成导演方案。'
            : busy
              ? '分镜正在生成，可在任务记录中查看状态。'
              : reviewSubmitting
                ? '第二轮审核正在提交，请稍候再生成分镜。'
                : draft.error || latestFailed
                  ? '生成未完成，精化选项已保留。核对后可以重试。'
                  : isDemo
                    ? '演示只记录模拟任务，不调用模型或创建真实分镜。'
                    : completedCurrent
                      ? workspace.storyboard.approved
                        ? `分镜 V${workspace.storyboard.version} 已确认；生成或编辑内容后需要重新审核。`
                        : `分镜 V${workspace.storyboard.version} 已生成，可编辑镜头并提交第二轮审核。`
                      : draft.refine_prompts === true
                        ? '将生成分镜并逐镜额外精化提示词，提交前会再次确认模型调用。'
                        : '基础提示词会随分镜生成；不会额外逐镜调用精化模型。';
  return {
    busy,
    blocked,
    message,
    label: busy
      ? '正在生成…'
      : reviewSubmitting
        ? '等待提审完成'
        : isDemo
          ? '确认模拟操作'
          : draft.error || latestFailed
            ? '重试生成分镜'
            : workspace?.storyboard
              ? '生成分镜新版本'
              : '生成分镜',
    missingScript,
    missingDirector,
    unverifiedDirector,
    hasUnsavedScript,
    reviewSubmitting,
  };
}

/**
 * 待审快照属于服务端已提交内容。旧版本、缺快照或过期记录必须先退回，
 * 不能将“当前页面看到了哪些镜头”当成原先已提审的内容。
 */
export function storyboardReviewState({ workspace, draft = {}, scriptDraft, isDemo = false } = {}) {
  const board = workspace?.storyboard;
  const form = storyboardFormState({ workspace, draft, scriptDraft, isDemo });
  const reviews = (workspace?.reviews || []).filter((review) => review.stage === 'storyboard');
  // 独立提审直接引用board；正式工作流的target_id保留节点名，以服务端快照确认产物身份。
  const matchesBoard = (review) =>
    !!board &&
    (review.target_id === board.id || review.target_snapshot?.storyboard_id === board.id);
  const matching = reviews.filter(matchesBoard);
  const pending =
    matching.find((review) => review.status === 'pending') ||
    reviews.find((review) => review.status === 'pending') ||
    null;
  const review = pending || matching[0] || null;
  const snapshot = pending?.target_snapshot;
  const snapshotMatches =
    !!snapshot && typeof snapshot === 'object' && snapshot.storyboard_id === board?.id;
  const sourceReady =
    !!board &&
    !form.missingScript &&
    (isDemo ||
      (board.source_status === 'current' &&
        workspace?.directing?.source_status === 'current' &&
        board.directing_plan_id === workspace.directing.id));
  const pendingCurrent =
    !!pending &&
    matchesBoard(pending) &&
    pending.target_status === 'current' &&
    snapshotMatches &&
    sourceReady;
  const confirmed = !!board?.approved && review?.status === 'approved';
  const shots = Array.isArray(workspace?.shots) ? workspace.shots : board?.shots || [];
  const hasShots = shots.length > 0;
  const canRequest =
    !!board &&
    hasShots &&
    sourceReady &&
    !form.hasUnsavedScript &&
    !form.busy &&
    !form.reviewSubmitting &&
    !pending;
  const requestLabel = form.reviewSubmitting
    ? '正在提交…'
    : draft.reviewError
      ? '重试提交审核'
      : review?.status === 'rejected' || (review?.status === 'approved' && !board?.approved)
        ? '重新提交审核'
        : '提交第二轮审核';
  let state = 'ready';
  let message = '提审会保存当前导演、分镜和镜头的快照；审核只保存结论，不会自动启动后续媒体生产。';
  if (!board) {
    state = 'missing';
    message = '生成分镜并核对镜头后，将导演与分镜一起提交第二轮审核。';
  } else if (pending && !pendingCurrent) {
    state = 'stale-pending';
    message = '存在旧版本、内容已变化或缺少快照的待审记录。请先查看并退回旧审核，再提交当前分镜。';
  } else if (pending) {
    state = 'pending';
    message = '当前导演与分镜已有待审快照，请核对后保存审核结论；不会自动继续媒体生产。';
  } else if (confirmed) {
    state = sourceReady ? 'approved' : 'approved-stale';
    message = sourceReady
      ? '本版导演与分镜已确认。审核已完成，没有自动启动后续媒体生产。'
      : '已有确认记录，但剧本或导演来源已变化，继续制作前请重新生成并核对。';
  } else if (form.reviewSubmitting) {
    state = 'submitting';
    message = '正在保存当前导演与分镜的审核快照，请稍候。';
  } else if (form.hasUnsavedScript) {
    state = 'blocked';
    message = '剧本有未保存修改，请先保存，并核对导演与分镜的来源后再提审。';
  } else if (form.busy) {
    state = 'blocked';
    message = '分镜正在生成，请等待新版本完成后再提审。';
  } else if (!sourceReady) {
    state = 'blocked';
    message = '分镜的剧本或导演来源已过期或未记录，请重新生成后提审。';
  } else if (!hasShots) {
    state = 'blocked';
    message = '当前分镜没有可审核镜头，请先生成有效分镜。';
  } else if (review?.status === 'rejected') {
    state = 'rejected';
    message = '最近一次审核已退回。核对修改后，可以重新提交当前分镜。';
  } else if (review?.status === 'approved' && !board.approved) {
    state = 'edited';
    message = '已确认的分镜内容发生了修改，请重新提审后再使用。';
  }
  return {
    state,
    message,
    review,
    pending,
    pendingCurrent,
    confirmed,
    canRequest: canRequest && !confirmed,
    requestLabel,
    reviewActionLabel: pending
      ? pendingCurrent
        ? '查看待审快照'
        : '查看并退回旧审核'
      : '查看审核记录',
  };
}
