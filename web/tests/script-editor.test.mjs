/** 草稿、版本与导入回归：纯内存与替身请求，不调用服务或模型。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createStudioApi, ApiError } from '../api.js';
import {
  createScriptDraft,
  updateScriptDraft,
  reconcileScriptDraft,
  acceptSavedScript,
  scriptDraftKey,
  persistScriptDraft,
  readScriptDraft,
  scriptFields,
  SCRIPT_IMPORT_LIMIT,
  scriptAssistState,
  scriptSaveState,
  isScriptSaveShortcut,
} from '../script-editor.js';

const connection = { mode: 'live', baseUrl: '/api/v1', userId: 'u1', userRole: 'editor' };
const script = {
  id: 's1',
  title: '初稿',
  logline: '',
  synopsis: '',
  script_text: '原始正文',
  version: 1,
};
const storage = () => {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
};
const json = (value, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

function live(handler) {
  const calls = [];
  const api = createStudioApi({
    mode: 'live',
    fetch: async (url, options) => {
      calls.push({ url, options });
      return handler(url, options);
    },
  });
  return { api, calls };
}

test('未保存正文按连接、模式、身份和项目隔离，刷新后恢复原base与文字', () => {
  const saved = storage(),
    key = scriptDraftKey(connection, 'p1');
  const draft = createScriptDraft(script);
  updateScriptDraft(draft, 'script_text', '用户修改\n第二行');
  persistScriptDraft(saved, key, draft);
  assert.equal(draft.persisted, true);
  const restored = readScriptDraft(saved, key, script);
  assert.equal(restored.script_text, '用户修改\n第二行');
  assert.equal(restored.base_script_id, 's1');
  assert.equal(restored.dirty, true);
  assert.equal(restored.restored, true);
  for (const other of [
    scriptDraftKey({ ...connection, mode: 'demo' }, 'p1'),
    scriptDraftKey({ ...connection, baseUrl: 'https://other.test/api/v1' }, 'p1'),
    scriptDraftKey({ ...connection, userId: 'u2' }, 'p1'),
    scriptDraftKey(connection, 'p2'),
  ])
    assert.equal(readScriptDraft(saved, other, script).dirty, false);
});

test('后台出现新版本保留脏草稿并提示冲突，干净编辑器跟随最新正文', () => {
  const next = { ...script, id: 's2', version: 2, script_text: '后台 AI 的新版本' };
  const clean = reconcileScriptDraft(createScriptDraft(script), next);
  assert.equal(clean.script_text, next.script_text);
  assert.equal(clean.base_script_id, 's2');
  const draft = createScriptDraft(script);
  updateScriptDraft(draft, 'script_text', '用户尚未保存的内容');
  const reconciled = reconcileScriptDraft(draft, next);
  assert.equal(reconciled.script_text, '用户尚未保存的内容');
  assert.equal(reconciled.base_script_id, 's1');
  assert.equal(reconciled.conflict, true);
});

test('保存期间继续输入不会丢失，提交内容仅作为新baseline', () => {
  const draft = createScriptDraft(script);
  updateScriptDraft(draft, 'script_text', '第一次修改');
  const submitted = scriptFields(draft);
  draft.saving = true;
  updateScriptDraft(draft, 'script_text', '请求期间继续输入');
  const saved = { ...script, id: 's2', version: 2, script_text: submitted.script_text };
  const next = acceptSavedScript(draft, submitted, saved);
  assert.equal(next.script_text, '请求期间继续输入');
  assert.equal(next.base_script_id, 's2');
  assert.equal(next.baseline.script_text, '第一次修改');
  assert.equal(next.dirty, true);
  assert.equal(next.saving, false);
  const unchanged = acceptSavedScript(createScriptDraft(saved), scriptFields(saved), saved);
  assert.equal(unchanged.dirty, false);
});

test('草稿损坏或存储不可用时不破坏正文，恢复到baseline会移除会话副本', () => {
  const saved = storage(),
    key = scriptDraftKey(connection, 'p');
  saved.setItem(key, '{bad json');
  assert.equal(readScriptDraft(saved, key, script).script_text, '原始正文');
  const draft = createScriptDraft(script);
  updateScriptDraft(draft, 'script_text', '未保存');
  assert.equal(
    persistScriptDraft(
      {
        setItem() {
          throw new Error('blocked');
        },
      },
      key,
      draft,
    ),
    false,
  );
  assert.equal(draft.script_text, '未保存');
  persistScriptDraft(saved, key, draft);
  updateScriptDraft(draft, 'script_text', script.script_text);
  persistScriptDraft(saved, key, draft);
  assert.equal(saved.getItem(key), null);
  assert.equal(draft.dirty, false);
});

test('演示手动新建、版本保存、预览与恢复保留旧版本，过时base抛409', async () => {
  const api = createStudioApi({ mode: 'demo', fetch: () => assert.fail('DEMO不应请求') });
  const p = await api.createProject({ name: '手写剧本' });
  const first = await api.createScript(p.id, { title: '片名', script_text: '第一场\n原文' });
  assert.equal(first.version, 1);
  const second = await api.createScript(p.id, {
    title: '片名',
    script_text: '第二版正文',
    base_script_id: first.id,
  });
  assert.equal(second.version, 2);
  assert.equal((await api.getScriptVersion(first.id)).script_text, '第一场\n原文');
  await assert.rejects(
    () =>
      api.createScript(p.id, { title: '片名', script_text: '过时写入', base_script_id: first.id }),
    (error) => error.status === 409,
  );
  await assert.rejects(
    () => api.createScript(p.id, { title: '片名', script_text: '缺少base' }),
    (error) => error.status === 409,
  );
  const restored = await api.restoreScriptVersion(p.id, first.id, { base_script_id: second.id });
  assert.equal(restored.version, 3);
  assert.equal(restored.script_text, first.script_text);
  assert.equal(restored.workspace_meta.source, 'restore');
  assert.equal(restored.workspace_meta.requires_reconfirmation, true);
  assert.equal((await api.getScripts(p.id)).length, 3);
  assert.equal((await api.getScript(p.id)).id, restored.id);
});

test('演示TXT/MD/JSON导入仅创建内存版本，DOCX明确不编造正文', async () => {
  const api = createStudioApi({ mode: 'demo', fetch: () => assert.fail('DEMO不应请求') });
  const p = await api.createProject({ name: '导入测试' });
  const txt = await api.importScript(p.id, new File(['第一场\n对白'], '初稿.txt'));
  assert.equal(txt.script_text, '第一场\n对白');
  assert.equal(txt.title, '初稿');
  const md = await api.importScript(p.id, new File(['# 场景二\n正文'], '二稿.md'), {
    base_script_id: txt.id,
  });
  assert.equal(md.version, 2);
  assert.equal(md.script_text, '# 场景二\n正文');
  const payload = {
    title: 'JSON片名',
    logline: '一句话',
    synopsis: '梗概',
    script_text: 'JSON正文',
  };
  const imported = await api.importScript(p.id, new File([JSON.stringify(payload)], '三稿.json'), {
    base_script_id: md.id,
  });
  assert.equal(imported.script_text, payload.script_text);
  assert.equal(imported.workspace_meta.source, 'import');
  await assert.rejects(
    () =>
      api.importScript(p.id, new File(['not docx'], '文件.docx'), { base_script_id: imported.id }),
    (error) => error.code === 'unsupported_demo_format',
  );
  await assert.rejects(
    () => api.importScript(p.id, new File(['{"content":{}}'], '无正文.json')),
    (error) => error.code === 'validation_error',
  );
  assert.equal((await api.getScripts(p.id)).length, 3);
});

test('真实创建、导入和恢复使用剧本专用接口，multipart保留base版本', async () => {
  const { api, calls } = live(() => json({ ...script, id: 's2', version: 2 }));
  await api.createScript('p', { ...scriptFields(script), base_script_id: 's1' });
  await api.importScript('p', new File(['docx bytes'], '剧本.docx'), { base_script_id: 's1' });
  await api.restoreScriptVersion('p', 's0', { base_script_id: 's1' });
  assert.equal(calls[0].url, '/api/v1/projects/p/scripts');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(JSON.parse(calls[0].options.body).script_text, script.script_text);
  assert.equal(calls[1].url, '/api/v1/projects/p/scripts/import');
  assert.ok(calls[1].options.body instanceof FormData);
  assert.equal(calls[1].options.body.get('file').name, '剧本.docx');
  assert.equal(calls[1].options.body.get('base_script_id'), 's1');
  assert.equal(calls[1].options.headers.has('Content-Type'), false);
  assert.equal(calls[2].url, '/api/v1/projects/p/scripts/s0/restore');
  assert.deepEqual(JSON.parse(calls[2].options.body), { base_script_id: 's1' });
  assert.ok(!calls.some((call) => call.url.endsWith('/upload')));
});

test('剧本文件空值、类型与2MiB上限在请求前检查', async () => {
  const { api, calls } = live(() => assert.fail('不应请求'));
  await assert.rejects(
    () => api.importScript('p', null),
    (error) => error.code === 'file_required',
  );
  await assert.rejects(
    () => api.importScript('p', new File(['x'], 'a.pdf')),
    (error) => error.code === 'invalid_file_type',
  );
  await assert.rejects(
    () => api.importScript('p', { name: 'a.txt', size: SCRIPT_IMPORT_LIMIT + 1 }),
    (error) => error.code === 'file_too_large',
  );
  assert.equal(calls.length, 0);
});

test('真实AI润色/续写必须确认并锁定已保存版本，错误任务和409原样保留', async () => {
  const task = {
    task_id: 't',
    status: 'queued',
    task: { id: 't', type: 'script_assist', status: 'queued' },
  };
  const { api, calls } = live(() => json(task));
  const payload = {
    operation: 'continue',
    base_script_id: 's1',
    instruction: '续写下一场，保留原文',
  };
  await assert.rejects(
    () => api.assistScript('p', payload),
    (error) => error.code === 'confirmation_required',
  );
  assert.equal(calls.length, 0);
  assert.deepEqual(await api.assistScript('p', payload, { confirmed: true }), task);
  assert.equal(calls[0].url, '/api/v1/projects/p/scripts/assist?wait=false');
  assert.deepEqual(JSON.parse(calls[0].options.body), payload);
  api.configure({
    fetch: async () =>
      json(
        { error: { code: 'conflict', message: '版本变化', details: { current_script_id: 's2' } } },
        409,
      ),
  });
  await assert.rejects(
    () => api.assistScript('p', payload, { confirmed: true }),
    (error) =>
      error instanceof ApiError && error.status === 409 && error.details.current_script_id === 's2',
  );
});

test('演示AI只记录模拟任务，不编造润色/续写内容或新版本', async () => {
  const api = createStudioApi({ mode: 'demo', fetch: () => assert.fail('DEMO不应请求') });
  const before = await api.getScript('demo-rainy-bookstore');
  for (const operation of ['polish', 'continue']) {
    const response = await api.assistScript('demo-rainy-bookstore', {
      operation,
      base_script_id: before.id,
      instruction: '测试',
    });
    assert.equal(response.task.type, 'script_assist');
    assert.equal(response.task.result.simulated, true);
    assert.equal(response.task.result.script_id, undefined);
  }
  assert.equal((await api.getScript('demo-rainy-bookstore')).script_text, before.script_text);
  assert.equal((await api.getScripts('demo-rainy-bookstore')).length, 1);
});

test('AI状态在编辑、还原、保存和任务运行时同步按钮与提示', () => {
  const draft = createScriptDraft(script);
  const context = { script, draft, tasks: [], isDemo: true };
  assert.equal(scriptAssistState(context).blocked, false);
  assert.ok(scriptAssistState(context).message.includes('模拟操作'));
  updateScriptDraft(draft, 'script_text', '修改');
  assert.equal(scriptAssistState(context).blocked, true);
  assert.ok(scriptAssistState(context).message.includes('请先保存'));
  updateScriptDraft(draft, 'script_text', script.script_text);
  assert.equal(scriptAssistState(context).blocked, false);
  assert.ok(scriptAssistState(context).message.includes('模拟操作'), '还原后恢复正常说明');
  draft.saving = true;
  assert.equal(scriptAssistState(context).blocked, true);
  assert.ok(scriptAssistState(context).message.includes('正在保存'));
  draft.saving = false;
  const running = scriptAssistState({
    ...context,
    tasks: [{ type: 'script_assist', status: 'running' }],
  });
  assert.equal(running.busy, true);
  assert.equal(running.blocked, true);
  assert.ok(running.message.includes('正在处理'));
  assert.equal(scriptAssistState({ ...context, submitting: true }).blocked, true);
  assert.equal(
    scriptAssistState({ ...context, tasks: [{ type: 'script_assist', status: 'failed' }] }).blocked,
    false,
  );
  assert.equal(
    scriptAssistState({ ...context, tasks: [{ type: 'video', status: 'running' }] }).blocked,
    false,
  );
  assert.ok(scriptAssistState({ ...context, isDemo: false }).message.includes('V1'));
  assert.ok(scriptAssistState({ ...context, isDemo: false }).message.includes('费用'));
  assert.equal(scriptAssistState({ ...context, script: null }).blocked, true);
  assert.equal(
    scriptAssistState({ ...context, script: { ...script, script_text: '  ' } }).blocked,
    true,
  );
});

test('所有保存入口共享未修改、保存中和首次保存状态，API仍允许相同正文新版本', async () => {
  const draft = createScriptDraft(script);
  assert.deepEqual(scriptSaveState({ script, draft }), {
    saving: false,
    unchanged: true,
    disabled: true,
    label: '已保存',
    message: '已保存为 V1',
  });
  updateScriptDraft(draft, 'title', '片名调整');
  assert.equal(scriptSaveState({ script, draft }).disabled, false);
  draft.saving = true;
  assert.equal(scriptSaveState({ script, draft }).disabled, true);
  assert.equal(scriptSaveState({ script, draft }).label, '正在保存…');
  const first = createScriptDraft(null, '新剧本');
  assert.equal(scriptSaveState({ script: null, draft: first }).disabled, true);
  updateScriptDraft(first, 'script_text', '正文');
  assert.equal(scriptSaveState({ script: null, draft: first }).disabled, false);
  assert.equal(scriptSaveState({ script: null, draft: first }).label, '保存第一版');
  const api = createStudioApi({ mode: 'demo' });
  const base = await api.getScript('demo-rainy-bookstore');
  const saved = await api.createScript('demo-rainy-bookstore', {
    ...scriptFields(base),
    base_script_id: base.id,
  });
  assert.equal(saved.version, base.version + 1);
  assert.equal(saved.script_text, base.script_text);
});

test('保存快捷键只在当前剧本编辑页且没有模态弹窗时处理', () => {
  const context = { view: 'workbench', tab: 'story', dialogOpen: false, hasEditor: true };
  assert.equal(isScriptSaveShortcut({ key: 's', metaKey: true }, context), true);
  assert.equal(isScriptSaveShortcut({ key: 'S', ctrlKey: true }, context), true);
  for (const changed of [
    { dialogOpen: true },
    { view: 'overview' },
    { tab: 'characters' },
    { hasEditor: false },
  ])
    assert.equal(
      isScriptSaveShortcut({ key: 's', metaKey: true }, { ...context, ...changed }),
      false,
    );
  for (const event of [
    { key: 's' },
    { key: 'k', metaKey: true },
    { key: 's', ctrlKey: true, altKey: true },
    { key: 's', metaKey: true, isComposing: true },
  ])
    assert.equal(isScriptSaveShortcut(event, context), false);
});

test('保存失败与版本冲突有持久且不同的操作反馈', () => {
  const draft = createScriptDraft(script);
  updateScriptDraft(draft, 'script_text', '需要保存的新输入');
  draft.error = '网络中断';
  let result = scriptSaveState({ script, draft });
  assert.equal(result.label, '重试保存');
  assert.equal(result.disabled, false);
  assert.equal(result.message, '保存未完成，正文已保留');
  draft.conflict = true;
  result = scriptSaveState({ script, draft });
  assert.equal(result.label, '版本冲突');
  assert.equal(result.disabled, true);
  assert.ok(result.message.includes('核对最新版本'));
});

test('保存请求后继续输入，内联状态区分已存版本和待存草稿', () => {
  const draft = createScriptDraft(script);
  updateScriptDraft(draft, 'script_text', '提交后又输入的文字');
  draft.persisted = true;
  const result = scriptSaveState({ script: { ...script, version: 2 }, draft });
  assert.equal(result.message, 'V2 已保存 · 当前修改待保存');
  assert.equal(result.disabled, false);
});
