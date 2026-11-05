import test from 'node:test';
import assert from 'node:assert/strict';
import { createStudioApi } from '../api.js';

test('真实导演生成须确认，参数与来源基线完整传至专用接口', async () => {
  const calls = [];
  const api = createStudioApi({
    mode: 'live',
    fetch: async (url, options) => {
      calls.push({ url, options });
      return new Response(JSON.stringify({ task_id: 'task-direct', status: 'pending' }), {
        status: 200,
      });
    },
  });
  const payload = { base_script_id: 'script-1', instruction: '保留书店的暖光', shots_target: 8 };
  await assert.rejects(
    api.generateDirecting('project-1', payload),
    (e) => e.code === 'confirmation_required',
  );
  assert.equal(calls.length, 0);
  await api.generateDirecting('project-1', payload, { confirmed: true, wait: true });
  assert.equal(calls[0].url, '/api/v1/projects/project-1/direct?wait=true');
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), payload);
});

test('导演历史读取使用单版本详情，DEMO模拟不会伪造新方案版本', async () => {
  const urls = [];
  const live = createStudioApi({
    mode: 'live',
    fetch: async (url) => {
      urls.push(url);
      return new Response(JSON.stringify({ id: 'plan-1', source_status: 'stale' }));
    },
  });
  assert.equal((await live.getDirectingPlan('plan-1')).source_status, 'stale');
  assert.equal(urls[0], '/api/v1/directing-plans/plan-1');
  const demo = createStudioApi({
    mode: 'demo',
    fetch: async () => {
      throw Error('unexpected network');
    },
  });
  const id = (await demo.getProjects())[0].id;
  const before = await demo.getWorkspace(id);
  const result = await demo.generateDirecting(id, {
    base_script_id: before.script.id,
    instruction: '测试',
    shots_target: 6,
  });
  const after = await demo.getWorkspace(id);
  assert.equal(result.task.result.simulated, true);
  assert.equal(after.directing.id, before.directing.id);
  assert.equal(after.directing_versions.length, before.directing_versions.length);
});
