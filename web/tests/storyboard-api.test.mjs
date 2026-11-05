import test from 'node:test';
import assert from 'node:assert/strict';
import { createStudioApi } from '../api.js';
const json = (value) => new Response(JSON.stringify(value), { status: 200 });

test('真实分镜生成须确认，完整传入来源与精化选择；详情与镜头更新走实际接口', async () => {
  const calls = [];
  const api = createStudioApi({
    mode: 'live',
    fetch: async (url, options) => {
      calls.push({ url, options });
      return json({ id: 'board-1', task_id: 'task-1', status: 'pending' });
    },
  });
  const payload = { base_script_id: 'script-1', base_plan_id: 'plan-1', refine_prompts: false };
  await assert.rejects(
    api.generateStoryboard('project-1', payload),
    (error) => error.code === 'confirmation_required',
  );
  assert.equal(calls.length, 0);
  await api.generateStoryboard('project-1', payload, { confirmed: true });
  assert.equal(calls[0].url, '/api/v1/projects/project-1/storyboards?wait=false');
  assert.deepEqual(JSON.parse(calls[0].options.body), payload);
  await api.getStoryboardVersion('board-1');
  assert.equal(calls[1].url, '/api/v1/storyboards/board-1');
  const edit = {
    base_storyboard_id: 'board-1',
    base_shot_fingerprint: 'fingerprint-1',
    description: '书店门口',
    duration_seconds: 4.5,
    camera: { shot_type: 'wide_shot' },
  };
  await api.updateShot('shot-1', edit);
  assert.equal(calls[2].url, '/api/v1/shots/shot-1');
  assert.equal(calls[2].options.method, 'PATCH');
  assert.deepEqual(JSON.parse(calls[2].options.body), edit);
  await api.requestStoryboardReview('project-1', 'board-1');
  assert.equal(calls[3].url, '/api/v1/projects/project-1/storyboards/board-1/review');
});

test('DEMO镜头修改使旧审核过期，退回重提可通过且不自动产生模型或续跑任务', async () => {
  const api = createStudioApi({
    mode: 'demo',
    fetch: async () => {
      throw Error('unexpected network');
    },
  });
  const project = (await api.getProjects())[0];
  const before = await api.getWorkspace(project.id),
    shot = before.shots[0];
  const review = before.reviews.find((item) => item.stage === 'storyboard');
  await api.updateShot(shot.id, {
    base_storyboard_id: before.storyboard.id,
    base_shot_fingerprint: shot.edit_fingerprint,
    description: '手动核对后的新描述',
  });
  await assert.rejects(
    api.decideReview(review.id, { status: 'approved' }),
    (error) => error.status === 409,
  );
  assert.equal((await api.getReview(review.id)).status, 'pending');
  await api.decideReview(review.id, { status: 'rejected', comment: '内容更新，请重新核对' });
  const next = await api.requestStoryboardReview(project.id, before.storyboard.id);
  assert.equal(next.target_id, before.storyboard.id);
  assert.equal(next.target_status, 'current');
  const approved = await api.decideReview(next.id, { status: 'approved' });
  const after = await api.getWorkspace(project.id);
  assert.equal(approved.review.status, 'approved');
  assert.ok(approved.review.decision.storyboard_snapshot);
  assert.equal(after.storyboard.approved, true);
  assert.equal(after.tasks.length, before.tasks.length);
  const simulated = await api.generateStoryboard(project.id, {
    base_script_id: after.script.id,
    base_plan_id: after.directing.id,
  });
  assert.equal(simulated.task.result.simulated, true);
  assert.equal((await api.getWorkspace(project.id)).storyboard.id, after.storyboard.id);
});

test('工作区保留真实分镜版本列表，不把历史摘要丢弃', async () => {
  const api = createStudioApi({
    mode: 'live',
    fetch: async (url) => {
      if (url.endsWith('/dashboard'))
        return json({
          project: { id: 'project-1', name: '项目' },
          tasks: [],
          pending_reviews: [],
          summary: {},
        });
      if (url.endsWith('/script')) return json({ id: 'script-1', version: 1, script_text: '书店' });
      if (url.endsWith('/directing'))
        return json({ plan: { id: 'plan-1', source_status: 'current' }, versions: [] });
      if (url.endsWith('/storyboards'))
        return json({
          board: { id: 'board-2' },
          versions: [
            { id: 'board-2', version: 2 },
            { id: 'board-1', version: 1 },
          ],
        });
      return json({ items: [] });
    },
  });
  const workspace = await api.getWorkspace('project-1');
  assert.equal(workspace.storyboard.id, 'board-2');
  assert.equal(workspace.storyboard_versions.length, 2);
});

test('同值保存保留已批准快照，实际修改才要求重审', async () => {
  const api = createStudioApi({ mode: 'demo' }),
    id = (await api.getProjects())[0].id;
  const before = await api.getWorkspace(id),
    review = before.reviews.find((item) => item.stage === 'storyboard');
  await api.decideReview(review.id, { status: 'approved' });
  const shot = (await api.getWorkspace(id)).shots[0];
  await api.updateShot(shot.id, {
    base_storyboard_id: before.storyboard.id,
    base_shot_fingerprint: shot.edit_fingerprint,
    description: shot.description,
    camera: { ...shot.camera },
  });
  const after = await api.getWorkspace(id);
  assert.equal(after.storyboard.approved, true);
  assert.equal(after.shots[0].edit_fingerprint, shot.edit_fingerprint);
  assert.equal(after.reviews.find((item) => item.id === review.id).target_status, 'current');
});
