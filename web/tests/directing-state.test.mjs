/** 导演状态与展示的契约回归：真实来源、提交边界、文本安全及演示隔离。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { directingFormState, planningTaskError } from '../directing-state.js';
import { directingPlanBody, directingWorkspace, workbench } from '../views.js';

test('创作页将传输失败转为可重试说明，保留具体业务冲突', () => {
  assert.ok(planningTaskError('RemoteProtocolError: disconnected').includes('内容已保留'));
  assert.ok(
    planningTaskError("Agent 'director' failed to produce schema 'directing_plan'").includes(
      '调整要求',
    ),
  );
  assert.equal(planningTaskError('剧本基线已变化'), '剧本基线已变化');
});

function workspace(values = {}) {
  return {
    project: { id: 'project-a', name: '雨夜书店', aspect_ratio: '16:9', status: 'script_ready' },
    script: { id: 'script-a', version: 3, content: { events: [{ summary: '最后一封信' }] } },
    tasks: [],
    ...values,
  };
}

function plan(values = {}) {
  return {
    id: 'plan-a',
    version: 2,
    approved: false,
    source_status: 'current',
    source_script: { id: 'script-a', version: 3, title: '雨夜书店', fingerprint: 'saved-source' },
    model_id: 'configured-model',
    prompt_version: '1.2.0',
    config_version: 'saved-config',
    content: {
      visual_style: '克制的雨夜电影',
      color_palette: ['#abc', '#203040', '暖灰'],
      lighting_style: '书店暖光与街道冷光',
      camera_language: '稳定机位，缓慢推近',
      pacing: '缓慢开始，信件出现后停顿',
      narrative_arc: '从等待到重逢',
      shot_strategy: {
        total_shots: 8,
        avg_duration_seconds: 4.5,
        coverage_notes: '保留人物反应镜头',
      },
      continuity_rules: ['灯光方向一致'],
      scenes_order: ['街道', '书店'],
      generation_request: { instruction: '对白克制，保留停顿', shots_target: 8 },
    },
    ...values,
  };
}

function state(values = {}) {
  return {
    api: { isDemo: false },
    workspace: workspace({ directing: plan(), directing_versions: [plan()] }),
    directingDraft: { instruction: '', shots_target: 6, error: '', submitting: false },
    scriptDraft: { dirty: false, saving: false },
    tab: 'directing',
    ...values,
  };
}

test('导演表单兼容已有结构化剧本，正常追加版本且错误可以重试', () => {
  let result = directingFormState({ workspace: workspace(), draft: { shots_target: 6 } });
  assert.equal(result.blocked, false);
  assert.equal(result.label, '生成导演方案');
  assert.match(result.message, /已保存剧本 V3/);
  result = directingFormState({
    workspace: workspace({ directing: plan() }),
    draft: { error: '超时' },
  });
  assert.equal(result.blocked, false);
  assert.equal(result.label, '重试生成方案');
  assert.match(result.message, /创作要求已保留/);
});

test('没有剧本、未保存修改和保存中均明确阻止导演提交', () => {
  const missing = directingFormState({ workspace: workspace({ script: null }) });
  assert.equal(missing.missingScript, true);
  assert.equal(missing.blocked, true);
  for (const scriptDraft of [{ dirty: true }, { saving: true }]) {
    const result = directingFormState({ workspace: workspace(), scriptDraft });
    assert.equal(result.hasUnsavedScript, true);
    assert.equal(result.blocked, true);
    assert.match(result.message, /保存/);
  }
});

test('导演正在提交或有活动任务时不重复派发，终态任务允许继续', () => {
  assert.equal(
    directingFormState({ workspace: workspace(), draft: { submitting: true } }).busy,
    true,
  );
  for (const status of ['queued', 'pending', 'running']) {
    const result = directingFormState({
      workspace: workspace({ tasks: [{ type: 'directing', status }] }),
    });
    assert.equal(result.busy, true);
    assert.equal(result.blocked, true);
    assert.equal(result.label, '正在生成…');
  }
  for (const status of ['succeeded', 'failed', 'cancelled']) {
    assert.equal(
      directingFormState({ workspace: workspace({ tasks: [{ type: 'directing', status }] }) })
        .blocked,
      false,
    );
  }
});

test('目标镜头数和创作要求有明确提交边界，不截断用户输入', () => {
  for (const shots_target of [1, 120, '6']) {
    assert.equal(
      directingFormState({ workspace: workspace(), draft: { shots_target } }).blocked,
      false,
    );
  }
  for (const shots_target of [0, 121, 2.5, '', 'six']) {
    const result = directingFormState({ workspace: workspace(), draft: { shots_target } });
    assert.equal(result.invalidShots, true);
    assert.equal(result.blocked, true);
  }
  const draft = { instruction: '字'.repeat(8001), shots_target: 6 };
  assert.equal(directingFormState({ workspace: workspace(), draft }).invalidInstruction, true);
  assert.equal(draft.instruction.length, 8001);
});

test('DEMO 表单明确模拟操作，不把静态方案说成真实生成', () => {
  const result = directingFormState({ workspace: workspace(), isDemo: true });
  assert.equal(result.label, '确认模拟操作');
  assert.match(result.message, /不调用模型或创建真实方案/);
});

test('方案正文转义模型文字，只有安全十六进制色值进入样式', () => {
  const unsafe = '</p><img src=x onerror=alert(1)>';
  const value = plan();
  value.content.visual_style = unsafe;
  value.content.color_palette = ['#abc', '#123456', '#fff;background:url(javascript:x)', unsafe];
  value.content.continuity_rules = [unsafe];
  value.content.scenes_order = [unsafe];
  const html = directingPlanBody(value);
  assert.ok(html.includes('&lt;/p&gt;&lt;img'));
  assert.ok(!html.includes('<img'));
  assert.equal((html.match(/style="background-color:/g) || []).length, 2);
  assert.ok(html.includes('background-color:#abc'));
  assert.ok(!html.includes('style="background-color:#fff;'));
});

test('方案来源按后端状态区分 current、stale 和 unknown，不猜测历史基线', () => {
  const current = directingPlanBody(plan());
  assert.ok(current.includes('基于剧本 V3'));
  assert.ok(current.includes('当前基线'));
  const stale = directingPlanBody(plan({ source_status: 'stale' }));
  assert.ok(stale.includes('基线已变化'));
  assert.ok(stale.includes('基于旧稿'));
  const unknown = directingPlanBody(plan({ source_status: 'unknown', source_script: null }));
  assert.ok(unknown.includes('剧本来源未记录'));
  assert.ok(unknown.includes('来源待核对'));
  assert.ok(!unknown.includes('基于剧本 V3'));
});

test('方案结构展示完整策略、顺序与真实生成记录，缺字段不编造默认参数', () => {
  const html = directingPlanBody(plan());
  for (const heading of [
    '视觉风格',
    '色彩与光线',
    '镜头语言',
    '叙事节奏',
    '叙事弧线',
    '镜头策略',
    '连续性约束',
    '场景顺序',
  ]) {
    assert.ok(html.includes(heading));
  }
  for (const value of [
    '8 个',
    '4.5 秒',
    'configured-model',
    'saved-config',
    '1.2.0',
    '对白克制，保留停顿',
  ]) {
    assert.ok(html.includes(value));
  }
  const legacy = directingPlanBody({ content: { visual_style: '旧方案' } });
  assert.ok(legacy.includes('未提供'));
  assert.ok(legacy.includes('生成时的创作要求未记录'));
  assert.ok(!legacy.includes('6 个'));
});

test('导演工作台使用专用表单和历史入口，导演不提供单独审批', () => {
  const html = workbench(state());
  for (const contract of [
    'id="directing-form"',
    'name="instruction"',
    'name="shots_target"',
    'min="1"',
    'max="120"',
    'id="directing-form-state"',
    'data-directing-submit',
    'data-action="directing-version"',
    'data-id="plan-a"',
  ]) {
    assert.ok(html.includes(contract));
  }
  assert.ok(html.includes('当前页不单独批准'));
  assert.ok(html.includes('data-tab="storyboard"'));
  assert.ok(!html.includes('data-action="approve-directing"'));
  assert.ok(!html.includes('data-stage="directing"'));
});

test('导演无剧本空态与未保存稿均保持返回剧本路径和禁用状态', () => {
  let s = state();
  s.workspace.script = null;
  s.workspace.directing = null;
  let html = directingWorkspace(s);
  assert.ok(html.includes('先保存或导入剧本'));
  assert.match(html, /data-directing-submit disabled/);
  assert.ok(html.includes('data-tab="story"'));
  s = state({ scriptDraft: { dirty: true } });
  html = directingWorkspace(s);
  assert.match(html, /data-directing-submit disabled/);
  assert.ok(html.includes('未保存修改'));
});

test('表单错误和历史版本保持可访问及文本安全，任务区分真实结果与模拟记录', () => {
  const s = state({
    directingDraft: {
      instruction: '</textarea><script>x</script>',
      shots_target: 6,
      error: '<失败>',
    },
  });
  s.workspace.tasks = [
    {
      id: 'task-real',
      type: 'directing',
      status: 'succeeded',
      result: { plan_id: 'plan-result', version: 3 },
    },
    {
      id: 'task-demo',
      type: 'directing',
      status: 'succeeded',
      result: { simulated: true, plan_id: 'not-a-real-plan' },
    },
  ];
  const html = directingWorkspace(s);
  assert.ok(html.includes('data-directing-error'));
  assert.ok(html.includes('tabindex="-1"'));
  assert.ok(html.includes('&lt;失败&gt;'));
  assert.ok(!html.includes('<script>x</script>'));
  assert.ok(html.includes('data-id="plan-result"'));
  assert.ok(!html.includes('data-id="not-a-real-plan"'));
  assert.ok(html.includes('未生成真实方案'));
  assert.ok(html.includes('data-action="task-detail"'));
  const demo = directingWorkspace({ ...s, api: { isDemo: true } });
  assert.ok(demo.includes('DEMO 静态示例'));
  assert.ok(demo.includes('不作为真实生成或审核依据'));
});
