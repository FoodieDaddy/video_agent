/** 分镜生成、只读历史与第二关快照的展示契约，不执行模型、编辑或审核。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { storyboardFormState, storyboardReviewState } from '../storyboard-state.js';
import {
  storyboardVersionBody,
  storyboardShotDetails,
  storyboardWorkspace,
  workbench,
} from '../views.js';

function shot(values = {}) {
  return {
    id: 'shot-a',
    order: 7,
    storyboard_id: 'board-a',
    scene_id: 'scene-a',
    description: '灯光落在最后一封信上。',
    action: '林简转身。',
    duration_seconds: 4.5,
    camera: { shot_type: 'close_up', movement: 'static', angle: 'eye_level' },
    characters: [
      { character_id: 'character-a', character_name: '林简', action: '转身', emotion: '迟疑' },
    ],
    dialogue: [{ character_name: '林简', text: '灯还亮着。', emotion: '平静' }],
    visual_prompt: '低饱和书店暖光',
    negative_prompt: '水印、文字',
    edit_fingerprint: 'saved-shot',
    ...values,
  };
}
function board(values = {}) {
  return {
    id: 'board-a',
    version: 2,
    title: '雨夜分镜',
    notes: '保留沉默',
    approved: false,
    directing_plan_id: 'plan-a',
    source_status: 'current',
    source_script: { id: 'script-a', version: 3, title: '雨夜书店', fingerprint: 'saved-script' },
    model_id: 'configured-storyboard-model',
    prompt_version: '2.0',
    config_version: 'board-config',
    shots: [shot()],
    ...values,
  };
}
function workspace(values = {}) {
  return {
    project: {
      id: 'project-a',
      name: '雨夜书店',
      status: 'characters_ready',
      aspect_ratio: '16:9',
    },
    script: { id: 'script-a', version: 3 },
    directing: { id: 'plan-a', version: 1, source_status: 'current' },
    storyboard: board(),
    shots: [shot()],
    scenes: [{ id: 'scene-a', name: '旧书店' }],
    tasks: [],
    reviews: [],
    ...values,
  };
}
function review(values = {}) {
  return {
    id: 'review-a',
    stage: 'storyboard',
    target_id: 'board-a',
    status: 'pending',
    target_status: 'current',
    target_snapshot: {
      storyboard_id: 'board-a',
      storyboard_version: 2,
      directing_plan_id: 'plan-a',
      source_script: { id: 'script-a', version: 3 },
      shot_fingerprints: { 'shot-a': 'saved-shot' },
    },
    ...values,
  };
}
function state(values = {}) {
  return {
    api: { isDemo: false },
    workspace: workspace(),
    tab: 'storyboard',
    storyboardDraft: {
      refine_prompts: false,
      error: '',
      submitting: false,
      reviewError: '',
      reviewSubmitting: false,
    },
    scriptDraft: { dirty: false, saving: false },
    ...values,
  };
}

test('生成分镜需要剧本和可验证的当前导演来源，DEMO静态演示明确例外', () => {
  assert.equal(storyboardFormState({ workspace: workspace() }).blocked, false);
  for (const w of [
    workspace({ script: null }),
    workspace({ directing: null }),
    workspace({ directing: { source_status: 'stale' } }),
    workspace({ directing: { source_status: 'unknown' } }),
  ]) {
    assert.equal(storyboardFormState({ workspace: w }).blocked, true);
  }
  const demo = storyboardFormState({
    workspace: workspace({ directing: { id: 'static-plan' } }),
    isDemo: true,
  });
  assert.equal(demo.blocked, false);
  assert.match(demo.message, /不调用模型或创建真实分镜/);
});

test('未保存剧本、生成活动任务和提审过程中不能并发生成新分镜', () => {
  for (const scriptDraft of [{ dirty: true }, { saving: true }]) {
    assert.equal(storyboardFormState({ workspace: workspace(), scriptDraft }).blocked, true);
  }
  for (const status of ['pending', 'queued', 'running']) {
    assert.equal(
      storyboardFormState({ workspace: workspace({ tasks: [{ type: 'storyboard', status }] }) })
        .busy,
      true,
    );
  }
  const result = storyboardFormState({ workspace: workspace(), draft: { reviewSubmitting: true } });
  assert.equal(result.blocked, true);
  assert.equal(result.label, '等待提审完成');
});

test('额外逐镜提示词精化默认关闭，开启后明确追加调用，失败可保留重试', () => {
  assert.match(storyboardFormState({ workspace: workspace() }).message, /不会额外逐镜调用/);
  assert.match(
    storyboardFormState({ workspace: workspace(), draft: { refine_prompts: true } }).message,
    /逐镜额外精化/,
  );
  const retry = storyboardFormState({ workspace: workspace(), draft: { error: '超时' } });
  assert.equal(retry.blocked, false);
  assert.equal(retry.label, '重试生成分镜');
});

test('第二关只将当前分镜的服务端完整快照显示为当前待审', () => {
  const current = storyboardReviewState({ workspace: workspace({ reviews: [review()] }) });
  assert.equal(current.state, 'pending');
  assert.equal(current.pendingCurrent, true);
  assert.equal(current.canRequest, false);
  assert.equal(current.reviewActionLabel, '查看待审快照');
  for (const r of [
    review({ target_status: 'stale' }),
    review({ target_status: 'unknown' }),
    review({ target_snapshot: null }),
    review({ target_id: 'old-board', target_snapshot: { storyboard_id: 'old-board' } }),
    review({ target_snapshot: { storyboard_id: 'old-board' } }),
  ]) {
    const value = storyboardReviewState({ workspace: workspace({ reviews: [r] }) });
    assert.equal(value.state, 'stale-pending');
    assert.equal(value.pendingCurrent, false);
    assert.equal(value.canRequest, false);
    assert.equal(value.reviewActionLabel, '查看并退回旧审核');
  }
});

test('正式工作流节点以服务端分镜快照匹配当前产物，旧无快照记录仍需退回', () => {
  const workflowReview = review({ target_type: 'workflow_node', target_id: 'review_storyboard' });
  let result = storyboardReviewState({ workspace: workspace({ reviews: [workflowReview] }) });
  assert.equal(result.state, 'pending');
  assert.equal(result.pendingCurrent, true);
  assert.equal(result.reviewActionLabel, '查看待审快照');
  result = storyboardReviewState({
    workspace: workspace({
      storyboard: board({ approved: true }),
      reviews: [{ ...workflowReview, status: 'approved' }],
    }),
  });
  assert.equal(result.confirmed, true);
  assert.equal(result.review.id, workflowReview.id);
  result = storyboardReviewState({
    workspace: workspace({ reviews: [{ ...workflowReview, target_snapshot: null }] }),
  });
  assert.equal(result.state, 'stale-pending');
  assert.equal(result.pendingCurrent, false);
  assert.equal(result.reviewActionLabel, '查看并退回旧审核');
});

test('新提审需要当前来源和有效镜头，未保存/无镜头/过期来源均禁用', () => {
  assert.equal(storyboardReviewState({ workspace: workspace() }).canRequest, true);
  for (const w of [
    workspace({ storyboard: null }),
    workspace({ script: null }),
    workspace({ shots: [] }),
    workspace({ storyboard: board({ source_status: 'stale' }) }),
    workspace({ directing: { id: 'other-plan', source_status: 'current' } }),
  ]) {
    assert.equal(storyboardReviewState({ workspace: w }).canRequest, false);
  }
  assert.equal(
    storyboardReviewState({ workspace: workspace(), scriptDraft: { dirty: true } }).canRequest,
    false,
  );
});

test('退回或编辑后的分镜可以重提审，批准记录与当前批准标记共同决定确认状态', () => {
  let value = storyboardReviewState({
    workspace: workspace({ reviews: [review({ status: 'rejected' })] }),
  });
  assert.equal(value.state, 'rejected');
  assert.equal(value.requestLabel, '重新提交审核');
  assert.equal(value.canRequest, true);
  value = storyboardReviewState({
    workspace: workspace({ reviews: [review({ status: 'approved' })] }),
  });
  assert.equal(value.state, 'edited');
  assert.equal(value.confirmed, false);
  assert.equal(value.canRequest, true);
  value = storyboardReviewState({
    workspace: workspace({
      storyboard: board({ approved: true }),
      reviews: [review({ status: 'approved' })],
    }),
  });
  assert.equal(value.state, 'approved');
  assert.equal(value.confirmed, true);
  assert.equal(value.canRequest, false);
});

test('镜头结构读取canonical相机字段并兼容旧字段，保留实际镜头序号和人物台词', () => {
  const html = storyboardVersionBody(board(), {
    scenes: [{ id: 'scene-a', name: '旧书店' }],
    readOnly: false,
  });
  for (const value of [
    'SHOT 07',
    '特写',
    '固定机位',
    '平视',
    '4.5 秒',
    '旧书店',
    '林简',
    '灯还亮着。',
    '低饱和书店暖光',
  ])
    assert.ok(html.includes(value));
  const canonical = storyboardVersionBody(
    board({ shots: [shot({ camera: { shot_type: 'close_up', shot_size: 'wide_shot' } })] }),
  );
  assert.ok(canonical.includes('特写'));
  const legacy = storyboardVersionBody(
    board({ shots: [shot({ camera: { shot_size: 'medium_shot' } })] }),
  );
  assert.ok(legacy.includes('中景'));
});

test('真实无图镜头没有示例图片，历史只读没有当前编辑或提审入口', () => {
  const html = storyboardVersionBody(board());
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('/assets/rainy-bookstore.png'));
  assert.ok(html.includes('storyboard-shot-symbol'));
  assert.ok(html.includes('历史版本 · 只读'));
  assert.ok(!html.includes('data-action="edit-shot"'));
  assert.ok(!html.includes('data-action="request-storyboard-review"'));
  assert.ok(html.includes('id="history-shot-prompt-shot-a"'));
  const editable = storyboardVersionBody(board(), { readOnly: false });
  assert.ok(editable.includes('data-action="edit-shot"'));
  assert.ok(editable.includes('data-action="shot-detail"'));
  assert.ok(editable.includes('id="shot-prompt-shot-a"'));
  const details = storyboardShotDetails(shot());
  assert.ok(!details.includes('历史版本'));
  assert.ok(!details.includes('data-action="edit-shot"'));
  assert.ok(details.includes('id="history-shot-prompt-shot-a"'));
});

test('所有镜头与来源文字转义，危险图片地址不进入预览', () => {
  const unsafe = '</p><script>alert(1)</script>';
  const html = storyboardVersionBody(
    board({
      title: unsafe,
      notes: unsafe,
      shots: [
        shot({
          description: unsafe,
          action: unsafe,
          image_url: 'javascript:alert(1)',
          dialogue: [{ character_name: unsafe, text: unsafe }],
        }),
      ],
    }),
  );
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('src="javascript:'));
});

test('分镜工作台表单、错误和二审请求具备明确契约，精化默认未勾选', () => {
  const s = state();
  s.storyboardDraft.reviewError = '<提审失败>';
  let html = storyboardWorkspace(s);
  for (const contract of [
    'id="storyboard-form"',
    'id="storyboard-form-state"',
    'data-storyboard-submit',
    'data-storyboard-review-error',
    'data-action="request-storyboard-review"',
    'data-id="board-a"',
  ])
    assert.ok(html.includes(contract));
  const input = html.match(/<input[^>]*name="refine_prompts"[^>]*>/)[0];
  assert.ok(!input.includes('checked'));
  assert.ok(html.includes('&lt;提审失败&gt;'));
  s.storyboardDraft.reviewSubmitting = true;
  html = storyboardWorkspace(s);
  assert.match(html, /data-action="request-storyboard-review"[^>]*disabled/);
  assert.ok(html.includes('正在提交…'));
});

test('二审面板显示冻结版本与镜头数，旧待审只提示查看退回', () => {
  let s = state({ workspace: workspace({ reviews: [review()] }) });
  let html = storyboardWorkspace(s);
  assert.ok(html.includes('data-review-state="pending"'));
  assert.ok(html.includes('查看待审快照'));
  assert.ok(html.includes('快照镜头'));
  assert.ok(!html.includes('data-action="request-storyboard-review"'));
  s.workspace.reviews = [review({ target_status: 'stale' })];
  html = storyboardWorkspace(s);
  assert.ok(html.includes('data-review-state="stale-pending"'));
  assert.ok(html.includes('查看并退回旧审核'));
  assert.ok(!html.includes('查看待审快照'));
});

test('模块四两页互相导航，不误启动完整媒体流程；手机面板有明确往返目标', () => {
  const s = state();
  for (const tab of ['directing', 'storyboard']) {
    s.tab = tab;
    const html = workbench(s);
    assert.ok(!html.includes('data-action="start-workflow"'));
    assert.ok(html.includes('has-plan'));
    assert.ok(html.includes('production-context-links'));
    assert.ok(html.includes('data-action="production-return"'));
  }
  s.tab = 'storyboard';
  const html = workbench(s);
  for (const id of [
    'storyboard-overview',
    'storyboard-brief',
    'storyboard-review',
    'storyboard-history',
  ])
    assert.ok(html.includes(`id="${id}"`));
  s.workspace.storyboard = null;
  assert.ok(workbench(s).includes('storyboard-workspace is-empty'));
});

test('任务区分真实结果与模拟记录，不从模拟任务制造分镜版本链接', () => {
  const s = state({ api: { isDemo: true } });
  s.workspace.tasks = [
    {
      id: 'task-real',
      type: 'storyboard',
      status: 'succeeded',
      result: { storyboard_id: 'board-result' },
    },
    {
      id: 'task-demo',
      type: 'storyboard',
      status: 'succeeded',
      result: { storyboard_id: 'fake-board', simulated: true },
    },
  ];
  const html = storyboardWorkspace(s);
  assert.ok(html.includes('data-id="board-result"'));
  assert.ok(!html.includes('data-id="fake-board"'));
  assert.ok(html.includes('未生成真实分镜'));
  assert.ok(html.includes('DEMO 静态示例'));
});
