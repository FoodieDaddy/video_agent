/** 原生 Node 契约测试；所有 fetch 都是测试替身，不访问后端、模型或外网。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createStudioApi, ApiError, studioApi, resolveMode } from '../api.js';
const json = (value, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const failure = (message, status = 404, details = { project_id: 'project-1' }) =>
  json({ error: { code: 'not_found', message, details } }, status);
const fake = (handler = () => json({ items: [], count: 0 })) => {
  const calls = [];
  return {
    calls,
    fetch: async (url, options) => {
      calls.push({ url, options });
      return handler(url, options);
    },
  };
};
const expectConfirmation = (error) =>
  error instanceof ApiError && error.code === 'confirmation_required';

function workspaceFetch({
  scriptResponse = () => failure('该项目还没有剧本'),
  otherResponse,
} = {}) {
  return fake((url, options) => {
    const path = new URL(url, 'http://test.local').pathname;
    if (path.endsWith('/dashboard'))
      return json({
        project: { id: 'project-1', name: '真实项目' },
        summary: { shot_count: 0 },
        workflow: null,
        pending_reviews: [],
        tasks: [],
      });
    if (path.endsWith('/script')) return scriptResponse();
    if (otherResponse) {
      const response = otherResponse(path, options);
      if (response) return response;
    }
    if (path.endsWith('/directing')) return json({ plan: null, versions: [] });
    if (path.endsWith('/storyboards')) return json({ board: null, versions: [] });
    return json({ items: [], count: 0 });
  });
}

test('默认实例与新实例使用live，导入和构造不fetch，显式读取才请求真实接口', async () => {
  assert.equal(studioApi.mode, 'live');
  assert.equal(studioApi.isDemo, false);
  const transport = fake(() => json({ items: [{ id: 'real-project', name: '后端项目' }] }));
  const api = createStudioApi({ fetch: transport.fetch });
  assert.equal(api.mode, 'live');
  assert.equal(transport.calls.length, 0);
  // 再次独立载入模块，验证导出默认实例的构造也不会读取后端。
  const originalFetch = globalThis.fetch;
  globalThis.fetch = transport.fetch;
  try {
    const isolated = await import('../api.js?default-live-import-check');
    assert.equal(isolated.studioApi.mode, 'live');
    assert.equal(transport.calls.length, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(await api.getProjects(), [{ id: 'real-project', name: '后端项目' }]);
  assert.equal(transport.calls.length, 1);
  assert.equal(transport.calls[0].url, '/api/v1/projects?limit=50');
});

test('URL模式只有显式demo进入演示，缺省、live和未知值都使用真实项目', () => {
  const cases = [
    ['', 'live'],
    ['?tab=projects', 'live'],
    ['?mode=live', 'live'],
    ['?mode=demo', 'demo'],
    ['?mode=', 'live'],
    ['?mode=unknown', 'live'],
    ['?mode=DEMO', 'live'],
  ];
  const originalLocation = Object.getOwnPropertyDescriptor(globalThis, 'location');
  try {
    delete globalThis.location;
    assert.equal(resolveMode(), 'live', '没有浏览器location也应默认live');
    assert.equal(createStudioApi().mode, 'live');
    for (const [search, mode] of cases) {
      assert.equal(resolveMode(search), mode);
      Object.defineProperty(globalThis, 'location', { configurable: true, value: { search } });
      assert.equal(resolveMode(), mode);
      assert.equal(createStudioApi().mode, mode);
      assert.equal(createStudioApi({ mode: 'live' }).mode, 'live', '显式配置优先于URL');
      assert.equal(createStudioApi({ mode: 'demo' }).mode, 'demo', '显式配置优先于URL');
    }
  } finally {
    if (originalLocation) Object.defineProperty(globalThis, 'location', originalLocation);
    else delete globalThis.location;
  }
});

test('显式模式只接受demo/live，无效配置报错且不改变已有连接', () => {
  for (const mode of ['typo', '', 'DEMO', false, 1]) {
    assert.throws(
      () => createStudioApi({ mode }),
      (error) => error.code === 'invalid_mode',
    );
  }
  const api = createStudioApi({ mode: 'demo' });
  assert.equal(api.configure({ userId: 'editor-1' }).mode, 'demo', '未指定mode时保留当前模式');
  assert.throws(
    () => api.configure({ mode: 'typo' }),
    (error) => error.code === 'invalid_mode',
  );
  assert.equal(api.mode, 'demo');
  assert.equal(api.configure({ mode: 'live' }).mode, 'live');
  assert.equal(api.configure({ baseUrl: '/api/v1' }).mode, 'live');
});

test('显式DEMO的读取和演示操作均不fetch', async () => {
  const transport = fake(() => {
    throw new Error('演示不应调用 fetch');
  });
  const api = createStudioApi({ mode: 'demo', fetch: transport.fetch });
  const projects = await api.getProjects();
  assert.equal(projects.length, 3);
  const rain = await api.getWorkspace(projects[0].id);
  assert.equal(rain.project.name, '雨夜书店');
  assert.equal(rain.dashboard.progress, 0.62);
  assert.equal(rain.characters.length, 3);
  assert.equal(rain.scenes.length, 3);
  assert.equal(rain.shots.length, 6);
  assert.equal(rain.pending_reviews[0].stage, 'storyboard');
  assert.equal(rain.pending_reviews[0].status, 'pending');
  assert.equal((await api.getAgentCatalog()).length, 13);
  assert.equal((await api.getAgents()).length, 13);
  assert.ok(rain.characters.every((person) => person.image_url.startsWith('data:image/svg+xml')));
  await api.startWorkflow(projects[1].id);
  await api.runStage(projects[0].id, 'video');
  assert.equal(transport.calls.length, 0);
});

test('演示项目可切换、新建、导入与修改，读取副本互不污染', async () => {
  const api = createStudioApi({ mode: 'demo' });
  const projects = await api.getProjects();
  projects[0].name = '外部篡改';
  assert.equal((await api.getProjects())[0].name, '雨夜书店');
  const project = await api.createProject({ name: '  我的短片  ', description: '新故事' });
  assert.equal(project.name, '我的短片');
  assert.equal((await api.getWorkspace(project.id)).script, null);
  assert.deepEqual((await api.getWorkspace(project.id)).characters, []);
  const imported = await api.importSample(project.id);
  assert.equal(imported.chapters.length, 1);
  assert.equal((await api.getDocuments(project.id)).length, 1);
  assert.equal((await api.getWorkspace(project.id)).script, null, '导入原文不应伪造剧本输出');
  await api.updateProject(project.id, { name: '新的片名' });
  assert.equal((await api.getDashboard(project.id)).project.name, '新的片名');
  await api.updateScript('demo-script-1', { title: '雨夜之后' });
  assert.equal((await api.getScript('demo-rainy-bookstore')).title, '雨夜之后');
  const independent = createStudioApi({ mode: 'demo' });
  assert.equal((await independent.getScript('demo-rainy-bookstore')).title, '雨夜书店');
});

test('演示审核只保存决定，配置编辑与重置都在内存中', async () => {
  const api = createStudioApi({ mode: 'demo' });
  const before = await api.getWorkspace('demo-rainy-bookstore');
  await api.decideReview(before.pending_reviews[0].id, { status: 'approved', comment: '节奏通过' });
  const after = await api.getWorkspace(before.project.id);
  assert.equal(after.pending_reviews.length, 0);
  assert.equal(after.reviews[0].comment, '节奏通过');
  assert.equal(after.tasks.length, before.tasks.length);
  const config = await api.getAgentConfig('script');
  config.payload.model.model_id = 'demo-edited';
  const saved = await api.updateAgentConfig('script', config.payload, { note: '示例变更' });
  assert.equal(saved.applied.model.model_id, 'demo-edited');
  assert.equal((await api.getAgentConfigVersions('script')).length, 1);
  assert.equal(
    (await api.getAgentCatalog()).find((agent) => agent.id === 'script').model_id,
    'demo-edited',
  );
  await api.resetAgentConfig('script');
  assert.equal((await api.getAgentConfig('script')).payload.model.model_id, 'demo-preview');
});

test('live统一baseURL、身份头、列表与AbortSignal，不存连接秘密', async () => {
  const transport = fake();
  const api = createStudioApi({
    mode: 'live',
    baseUrl: 'https://studio.test',
    userId: 'editor-1',
    userRole: 'editor',
    fetch: transport.fetch,
  });
  const controller = new AbortController();
  assert.deepEqual(await api.getProjects({ signal: controller.signal, limit: 20 }), []);
  const { url, options } = transport.calls[0];
  assert.equal(url, 'https://studio.test/api/v1/projects?limit=20');
  assert.equal(options.headers.get('X-User-Id'), 'editor-1');
  assert.equal(options.headers.get('X-User-Role'), 'editor');
  assert.equal(options.signal, controller.signal);
  assert.equal(options.credentials, 'same-origin');
  const defaultIdentity = fake();
  await createStudioApi({ mode: 'live', fetch: defaultIdentity.fetch }).getMeta();
  assert.equal(defaultIdentity.calls[0].options.headers.has('X-User-Id'), false);
  assert.throws(
    () => api.configure({ baseUrl: 'https://secret:password@studio.test/api/v1' }),
    (error) => error.code === 'invalid_base_url',
  );
  assert.throws(
    () => api.configure({ baseUrl: 'https://studio.test/api/v1?api_key=secret' }),
    (error) => error.code === 'invalid_base_url',
  );
  assert.throws(
    () => api.configure({ mode: 'anything' }),
    (error) => error.code === 'invalid_mode',
  );
  assert.equal(api.getConnection().baseUrl, 'https://studio.test/api/v1', '失败配置应保持原连接');
});

test('未经确认的所有live生成入口均在fetch前被阻止', async () => {
  const transport = fake();
  const api = createStudioApi({ mode: 'live', fetch: transport.fetch });
  for (const action of [
    () => api.startWorkflow('p'),
    () => api.resumeWorkflow('p', 'r'),
    ...[
      'script',
      'directing',
      'storyboard',
      'video',
      'audio',
      'editing',
      'render',
      'export',
      'evaluation',
    ].map((stage) => () => api.runStage('p', stage)),
    () => api.generateCharacterImages('c'),
    () => api.generateCharacterViews('c'),
    () => api.generateShot('s'),
    () => api.decideReview('r', { status: 'approved', resume_workflow: true }),
  ])
    await assert.rejects(action, expectConfirmation);
  assert.equal(transport.calls.length, 0);
  await assert.rejects(
    () => api.runStage('p', 'characters', { confirmed: true }),
    (error) => error.code === 'invalid_stage',
  );
});

test('确认后启动真实任务仍保留后端失败或部分成功的结果', async () => {
  const failed = {
    task_id: 'task-1',
    status: 'failed',
    task: {
      id: 'task-1',
      status: 'failed',
      error: '供应商不可用',
      result: { failures: ['镜头2'] },
    },
  };
  const transport = fake(() => json(failed));
  const api = createStudioApi({ mode: 'live', fetch: transport.fetch });
  assert.deepEqual(
    await api.startWorkflow('p', { workflow_id: 'novel_to_video' }, { confirmed: true }),
    failed,
  );
  assert.equal(transport.calls[0].url, '/api/v1/projects/p/workflows/start?wait=false');
  assert.deepEqual(JSON.parse(transport.calls[0].options.body), { workflow_id: 'novel_to_video' });
  const partial = {
    task_id: 'task-2',
    status: 'succeeded',
    task: {
      status: 'succeeded',
      result: { videos_created: 1, failures: [{ shot_id: 'shot-2', error: '失败' }] },
    },
  };
  api.configure({ fetch: async () => json(partial) });
  assert.deepEqual(await api.runStage('p', 'video', { confirmed: true }), partial);
});

test('审核默认显式resume_workflow=false，二次确认后才能续跑', async () => {
  const transport = fake(() => json({ review: { id: 'r', status: 'approved' } }));
  const api = createStudioApi({ mode: 'live', fetch: transport.fetch });
  await api.decideReview('r', { status: 'approved', comment: '通过' });
  assert.deepEqual(JSON.parse(transport.calls[0].options.body), {
    status: 'approved',
    comment: '通过',
    decision: {},
    resume_workflow: false,
  });
  await api.decideReview('r', { status: 'approved', resume_workflow: true }, { confirmed: true });
  assert.equal(JSON.parse(transport.calls[1].options.body).resume_workflow, true);
});

test('workspace只将已知的尚无剧本空态转null，不伪造进度', async () => {
  const transport = workspaceFetch();
  const api = createStudioApi({ mode: 'live', fetch: transport.fetch });
  const value = await api.getWorkspace('project-1');
  assert.equal(value.script, null);
  assert.equal(value.dashboard.project.name, '真实项目');
  assert.equal(value.demo, false);
  assert.equal(value.project.progress, undefined);
  assert.equal(value.dashboard.progress, undefined);
  assert.deepEqual(value.characters, []);
  assert.equal(value.directing, null);
  assert.equal(value.storyboard, null);
  assert.ok(transport.calls[0].url.endsWith('/dashboard'));
});

test('项目404、未知路由404与权限失败不能伪装成空workspace', async () => {
  for (const response of [
    () => failure('项目不存在'),
    () => failure('Not Found'),
    () => failure('该项目还没有剧本', 404, { project_id: 'different' }),
    () => failure('权限不足', 403),
  ]) {
    const transport = workspaceFetch({ scriptResponse: response });
    const api = createStudioApi({ mode: 'live', fetch: transport.fetch });
    await assert.rejects(
      () => api.getWorkspace('project-1'),
      (error) => error instanceof ApiError && [403, 404].includes(error.status),
    );
  }
  const transport = workspaceFetch({
    otherResponse: (path) => (path.endsWith('/scenes') ? failure('Not Found') : null),
  });
  await assert.rejects(
    () => createStudioApi({ mode: 'live', fetch: transport.fetch }).getWorkspace('project-1'),
    (error) => error.status === 404,
  );
  const denied = fake(() =>
    json(
      { error: { code: 'permission_denied', message: '没有权限', details: { role: 'editor' } } },
      403,
    ),
  );
  await assert.rejects(
    () => createStudioApi({ mode: 'live', fetch: denied.fetch }).getWorkspace('project-1'),
    (error) =>
      error.status === 403 && error.code === 'permission_denied' && error.details.role === 'editor',
  );
  assert.equal(denied.calls.length, 1, 'dashboard失败后不应继续请求其他资源');
});

test('取消和网络错误保留语义，失败不自动退回DEMO', async () => {
  const controller = new AbortController();
  controller.abort();
  const transport = fake();
  const api = createStudioApi({ mode: 'live', fetch: transport.fetch });
  await assert.rejects(
    () => api.getProjects({ signal: controller.signal }),
    (error) => error.name === 'AbortError',
  );
  assert.equal(transport.calls.length, 0);
  const aborted = new DOMException('取消', 'AbortError');
  api.configure({
    fetch: async () => {
      throw aborted;
    },
  });
  await assert.rejects(
    () => api.getProjects(),
    (error) => error === aborted,
  );
  api.configure({
    fetch: async () => {
      throw new TypeError('offline');
    },
  });
  await assert.rejects(
    () => api.getProjects(),
    (error) => error instanceof ApiError && error.code === 'network_error',
  );
  assert.equal(api.mode, 'live');
  api.configure({ fetch: async () => new Response('<html>proxy failed</html>', { status: 502 }) });
  await assert.rejects(
    () => api.getMeta(),
    (error) => error.status === 502 && error.code === 'invalid_response',
  );
});

test('实际资源更新路径、任务路径和上传体符合后端约定', async () => {
  const transport = fake(() => json({}));
  const api = createStudioApi({ mode: 'live', fetch: transport.fetch });
  await api.updateScript('script/a', { title: '片名' });
  await api.updateCharacter('char-1', { summary: '人物' });
  await api.updateScene('scene-1', { profile: { mood: '宁静' } });
  await api.updateShot('shot-1', { duration_seconds: 4 });
  await api.getTask('project-1', 'task-1');
  await api.getTaskEvents('project-1', 'task-1', { after: 'event-1' });
  await api.runStage('project-1', 'directing', { confirmed: true });
  assert.equal(transport.calls[0].url, '/api/v1/scripts/script%2Fa');
  assert.equal(transport.calls[0].options.method, 'PATCH');
  assert.equal(transport.calls[1].url, '/api/v1/characters/char-1');
  assert.equal(transport.calls[2].url, '/api/v1/scenes/scene-1');
  assert.equal(transport.calls[3].url, '/api/v1/shots/shot-1');
  assert.equal(transport.calls[4].url, '/api/v1/projects/project-1/tasks/task-1');
  assert.equal(
    transport.calls[5].url,
    '/api/v1/projects/project-1/tasks/task-1/events?after=event-1&limit=200',
  );
  assert.equal(transport.calls[6].url, '/api/v1/projects/project-1/direct?wait=false');
  const count = transport.calls.length;
  await assert.rejects(
    () => api.uploadDocument('p', null),
    (error) => error.code === 'file_required',
  );
  assert.equal(transport.calls.length, count);
  await api.uploadDocument('p', new File(['原文'], 'source.txt', { type: 'text/plain' }));
  const upload = transport.calls.at(-1);
  assert.ok(upload.options.body instanceof FormData);
  assert.equal(upload.options.body.get('file').name, 'source.txt');
  assert.equal(upload.options.headers.has('Content-Type'), false, 'multipart边界由浏览器生成');
});

test('SSE携带身份、解析跨块CRLF并在终态取消reader', async () => {
  const encoder = new TextEncoder();
  let cancelled = false;
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(
        encoder.encode(': connected\r\nevent: task\r\ndata: {"id":"e1","message":"完成"}\r'),
      );
      controller.enqueue(encoder.encode('\n\r\nevent: end\r\ndata: {}\r\n\r\n'));
    },
    cancel() {
      cancelled = true;
    },
  });
  const transport = fake(
    () => new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }),
  );
  const api = createStudioApi({ mode: 'live', userId: 'editor-1', fetch: transport.fetch });
  const controller = new AbortController();
  const events = [];
  for await (const event of api.streamTaskEvents('p', 't', {
    after: 'e0',
    signal: controller.signal,
  }))
    events.push(event);
  assert.deepEqual(events, [
    { event: 'task', data: { id: 'e1', message: '完成' } },
    { event: 'end', data: {} },
  ]);
  assert.equal(cancelled, true);
  assert.equal(transport.calls[0].options.headers.get('X-User-Id'), 'editor-1');
  assert.equal(transport.calls[0].options.headers.get('Accept'), 'text/event-stream');
  assert.equal(transport.calls[0].options.signal, controller.signal);
  assert.equal(
    transport.calls[0].url,
    '/api/v1/projects/p/tasks/t/events/stream?after=e0&timeout=900',
  );
});

test('读取方法忽略非契约method/body参数，不能意外触发生成', async () => {
  const transport = fake(() => json({ board: null, versions: [] }));
  const api = createStudioApi({ mode: 'live', fetch: transport.fetch });
  await api.getStoryboard('p', { method: 'POST', body: {} });
  assert.equal(transport.calls[0].options.method, 'GET');
  assert.equal(transport.calls[0].options.body, undefined);
  await api.runStage('p', 'evaluate', {}, { confirmed: true });
  assert.equal(transport.calls[1].url, '/api/v1/projects/p/evaluate?wait=false');
  assert.equal(transport.calls[1].options.method, 'POST');
});

test('SSE中途失败保持原始AbortError，不被reader清理错误覆盖', async () => {
  const cancelled = new DOMException('已取消', 'AbortError');
  const body = new ReadableStream({
    start(controller) {
      controller.error(cancelled);
    },
  });
  const api = createStudioApi({
    mode: 'live',
    fetch: async () => new Response(body, { headers: { 'Content-Type': 'text/event-stream' } }),
  });
  await assert.rejects(
    async () => {
      for await (const item of api.streamTaskEvents('p', 't')) assert.fail(`不应收到事件 ${item}`);
    },
    (error) => error === cancelled,
  );
});

test('普通成员仅在配置403时读取注册目录，项目数据仍可浏览', async () => {
  const transport = workspaceFetch({
    otherResponse: (path) => {
      if (path === '/api/v1/admin/model-configs')
        return json({ error: { code: 'permission_denied', message: '需要管理员' } }, 403);
      if (path === '/api/v1/meta')
        return json({
          agents: ['script', 'character_extraction', 'character_description', 'scene_extraction'],
          env: 'development',
        });
      return null;
    },
  });
  const api = createStudioApi({
    mode: 'live',
    userId: 'member-1',
    userRole: 'viewer',
    fetch: transport.fetch,
  });
  const [catalog, value] = await Promise.all([
    api.getAgentCatalog(),
    api.getWorkspace('project-1'),
  ]);
  assert.equal(value.project.name, '真实项目');
  assert.equal(catalog.length, 13);
  const script = catalog.find((item) => item.id === 'script');
  assert.equal(script.status, 'registered');
  assert.equal(script.config_access, false);
  assert.equal(script.model_id, null);
  assert.equal(script.enabled, null);
  const character = catalog.find((item) => item.id === 'character');
  assert.deepEqual(character.agent_ids, [
    'character_extraction',
    'character_description',
    'character_consistency',
  ]);
  assert.deepEqual(character.registered_agent_ids, [
    'character_extraction',
    'character_description',
  ]);
  assert.equal(catalog.find((item) => item.id === 'video').status, 'unregistered');
  assert.equal(transport.calls.filter((call) => call.url === '/api/v1/meta').length, 1);
  assert.ok(transport.calls.every((call) => call.options.method === 'GET'));
});

test('角色目录不吞管理员接口的网络或服务端错误', async () => {
  for (const status of [404, 500]) {
    const transport = fake(() =>
      json({ error: { code: 'server_error', message: '服务异常' } }, status),
    );
    const api = createStudioApi({ mode: 'live', fetch: transport.fetch });
    await assert.rejects(
      () => api.getAgentCatalog(),
      (error) => error.status === status,
    );
    assert.equal(transport.calls.length, 1);
    assert.ok(transport.calls[0].url.includes('/admin/model-configs'));
  }
});
