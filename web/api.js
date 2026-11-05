/**
 * 无构建依赖的浏览器接口适配层。
 * 默认连接真实项目；仅显式 mode=demo 或 mode:'demo' 使用内存示例。
 * 导入与构造实例不发请求；真实读取与写入必须显式调用方法。
 * confirmed 是界面二次确认的约定，不能代替服务端权限与计费控制。
 */
import { AGENT_CATALOG, createDemoState, demoArtwork } from './demo-data.js';
import { scriptFields, SCRIPT_IMPORT_LIMIT } from './script-editor.js';

const clone = (value) => structuredClone(value);
// 仅用于内存演示的同值比较；真实镜头基线始终由后端指纹校验。
const demoComparable = (value) =>
  Array.isArray(value)
    ? value.map(demoComparable)
    : value && typeof value === 'object'
      ? Object.fromEntries(
          Object.keys(value)
            .sort()
            .map((key) => [key, demoComparable(value[key])]),
        )
      : value;
const segment = (value) => encodeURIComponent(String(value));
const items = (payload) => (Array.isArray(payload) ? payload : (payload?.items ?? []));
const STAGE_PATHS = Object.freeze({
  script: 'analyze',
  analyze: 'analyze',
  directing: 'direct',
  director: 'direct',
  storyboard: 'storyboards',
  storyboards: 'storyboards',
  video: 'shots/generate',
  audio: 'audio',
  editing: 'editing',
  render: 'render',
  export: 'export',
  evaluation: 'evaluate',
  evaluate: 'evaluate',
});

export class ApiError extends Error {
  constructor(
    message,
    { status = 0, code = 'request_failed', details = {}, url = '', cause } = {},
  ) {
    super(message, cause ? { cause } : undefined);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.url = url;
  }
}

function abortIfNeeded(signal) {
  if (signal?.aborted) throw signal.reason ?? new DOMException('请求已取消', 'AbortError');
}

/** 页面与接口共用的 URL 模式规则：只有明确指定 demo 才展示示例资料。 */
export function resolveMode(search = typeof location === 'undefined' ? '' : location.search) {
  return new URLSearchParams(search).get('mode') === 'demo' ? 'demo' : 'live';
}

/** URL 仅接受 API 根地址；禁止在地址中夹带账号、密钥、查询参数或片段。 */
function normalizeBaseUrl(value = '/api/v1') {
  const raw = String(value).trim();
  if (/^\/(?!\/)/.test(raw) && !/[?#\\]/.test(raw)) return raw.replace(/\/+$/, '') || '/api/v1';
  let parsed;
  try {
    parsed = new URL(raw);
  } catch {
    throw new ApiError('接口地址必须是 /api/v1 或完整的 HTTP(S) 地址', {
      code: 'invalid_base_url',
    });
  }
  if (
    !['http:', 'https:'].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash
  ) {
    throw new ApiError('接口地址不能包含账号、密钥、查询参数或片段', { code: 'invalid_base_url' });
  }
  parsed.pathname = parsed.pathname === '/' ? '/api/v1' : parsed.pathname.replace(/\/+$/, '');
  return parsed.href.replace(/\/+$/, '');
}

function queryString(values = {}) {
  const result = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value !== undefined && value !== null && value !== '') result.set(key, String(value));
  return result.size ? `?${result}` : '';
}

/** 一个适配器对应一份独立演示资料和一组仅保存在内存中的连接设置。 */
export function createStudioApi(initial = {}) {
  let connection;
  let demo = createDemoState();
  let fetchImpl = initial.fetch ?? ((...args) => globalThis.fetch(...args));

  function configure(next = {}) {
    const mode = next.mode ?? connection?.mode ?? resolveMode();
    if (!['demo', 'live'].includes(mode))
      throw new ApiError('模式只能是 demo 或 live', { code: 'invalid_mode' });
    const updated = {
      mode,
      isDemo: mode === 'demo',
      baseUrl: normalizeBaseUrl(next.baseUrl ?? connection?.baseUrl ?? '/api/v1'),
      userId: String(next.userId ?? connection?.userId ?? 'user_demo').trim(),
      userRole: String(next.userRole ?? connection?.userRole ?? 'admin').trim(),
    };
    if (next.fetch !== undefined && typeof next.fetch !== 'function')
      throw new ApiError('fetch 必须是函数', { code: 'invalid_fetch' });
    if (next.fetch) fetchImpl = next.fetch;
    connection = updated;
    return { ...connection };
  }
  configure(initial);

  function identityHeaders(extra = {}) {
    const headers = new Headers(extra);
    // 当前开发鉴权在省略 user_demo 时返回演示管理员；显式发送反而成为普通用户。
    if (connection.userId && connection.userId !== 'user_demo')
      headers.set('X-User-Id', connection.userId);
    if (connection.userRole) headers.set('X-User-Role', connection.userRole);
    return headers;
  }

  async function request(path, { method = 'GET', body, signal, query, stream = false } = {}) {
    abortIfNeeded(signal);
    const url = `${connection.baseUrl}${path}${queryString(query)}`;
    const headers = identityHeaders({ Accept: stream ? 'text/event-stream' : 'application/json' });
    const form = typeof FormData !== 'undefined' && body instanceof FormData;
    if (body !== undefined && !form) headers.set('Content-Type', 'application/json');
    let response;
    try {
      response = await fetchImpl(url, {
        method,
        headers,
        body: body === undefined ? undefined : form ? body : JSON.stringify(body),
        signal,
        credentials: 'same-origin',
      });
    } catch (error) {
      if (signal?.aborted || error?.name === 'AbortError') throw error;
      throw new ApiError('连接失败，请检查接口地址及服务状态', {
        code: 'network_error',
        url,
        cause: error,
      });
    }
    if (stream && response.ok) return response;
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        throw new ApiError(
          response.ok ? '接口未返回有效的 JSON 数据' : `请求失败（HTTP ${response.status}）`,
          { status: response.status, code: 'invalid_response', url },
        );
      }
    }
    if (!response.ok) {
      const error = payload?.error ?? {};
      const detail = typeof payload?.detail === 'string' ? payload.detail : null;
      throw new ApiError(error.message || detail || `请求失败（HTTP ${response.status}）`, {
        status: response.status,
        code: error.code || 'http_error',
        details: error.details ?? payload?.detail ?? {},
        url,
      });
    }
    return payload;
  }

  async function act(options, demoAction, liveAction) {
    abortIfNeeded(options?.signal);
    if (connection.isDemo) return clone(await demoAction());
    return liveAction();
  }

  function needConfirmation(options = {}) {
    if (!connection.isDemo && options.confirmed !== true)
      throw new ApiError('请先在界面中确认启动真实生成，再继续此操作', {
        code: 'confirmation_required',
      });
  }

  function workspace(id) {
    const value = demo.workspaces[id];
    if (!value)
      throw new ApiError('项目不存在', {
        status: 404,
        code: 'not_found',
        details: { project_id: id },
      });
    return value;
  }

  function findEntity(kind, id) {
    for (const value of Object.values(demo.workspaces)) {
      const found =
        kind === 'script'
          ? value.script?.id === id
            ? value.script
            : null
          : value[kind]?.find((entry) => entry.id === id);
      if (found) return { value: found, workspace: value };
    }
    throw new ApiError('所选内容不存在', { status: 404, code: 'not_found', details: { id } });
  }

  function syncWorkspace(value) {
    if (value.directing?.source_script) {
      value.directing.source_status =
        value.directing.source_script.id === value.script?.id ? 'current' : 'stale';
    }
    if (value.storyboard?.source_script) {
      value.storyboard.source_status =
        value.storyboard.source_script.id === value.script?.id &&
        value.storyboard.directing_plan_id === value.directing?.id &&
        value.directing.source_status === 'current'
          ? 'current'
          : 'stale';
    }
    for (const review of value.reviews) {
      if (review.stage !== 'storyboard' || !review.target_snapshot) continue;
      const snapshot = review.target_snapshot;
      review.target_status =
        snapshot.storyboard_id === value.storyboard?.id &&
        value.storyboard.source_status === 'current' &&
        Object.keys(snapshot.shot_fingerprints || {}).length === value.shots.length &&
        value.shots.every(
          (shot) => snapshot.shot_fingerprints[shot.id] === (shot.edit_fingerprint || 'demo'),
        )
          ? 'current'
          : 'stale';
    }
    value.pending_reviews = value.reviews.filter((review) => review.status === 'pending');
    Object.assign(value.summary, {
      name: value.project.name,
      status: value.project.status,
      script_title: value.script?.title ?? null,
      logline: value.script?.logline ?? null,
      synopsis: value.script?.synopsis ?? null,
      shot_count: value.shots.length,
      characters: value.characters.map((item) => item.name),
      scenes: value.scenes.map((item) => item.name),
      total_duration_seconds: value.shots.reduce(
        (total, shot) => total + (shot.duration_seconds || 0),
        0,
      ),
    });
    Object.assign(value.dashboard, {
      project: value.project,
      summary: value.summary,
      workflow: value.workflow,
      pending_reviews: value.pending_reviews,
      tasks: value.tasks,
    });
    return value;
  }

  function demoTask(projectId, type) {
    const value = workspace(projectId);
    const now = new Date().toISOString();
    const task = {
      id: `demo-task-new-${++demo.sequence}`,
      project_id: projectId,
      type,
      status: 'succeeded',
      progress: 1,
      message: '演示操作已记录，未调用模型',
      result: { demo: true, simulated: true },
      error: null,
      created_at: now,
      started_at: now,
      finished_at: now,
    };
    value.tasks.unshift(task);
    demo.taskEvents[task.id] = [
      {
        id: `demo-event-${demo.sequence}`,
        task_id: task.id,
        event_type: 'completed',
        level: 'info',
        message: task.message,
        progress: 1,
        data: { demo: true },
        created_at: now,
      },
    ];
    value.activities.unshift({
      id: `demo-activity-${demo.sequence}`,
      title: '已记录演示操作',
      description: `${type} · 不会调用真实模型`,
      created_at: now,
      type: 'completed',
    });
    syncWorkspace(value);
    return { task_id: task.id, status: task.status, task };
  }

  function scriptVersions(value) {
    value.scripts ??= value.script ? [value.script] : [];
    return value.scripts;
  }

  function checkScriptBase(value, baseId) {
    if ((value.script?.id ?? null) !== (baseId || null))
      throw new ApiError('剧本已有新版本，草稿已保留，请核对最新版本后再保存', {
        status: 409,
        code: 'conflict',
        details: { current_script_id: value.script?.id ?? null },
      });
  }

  function saveDemoScript(projectId, payload, source = 'manual') {
    const value = workspace(projectId);
    checkScriptBase(value, payload.base_script_id);
    const fields = scriptFields(payload);
    if (!fields.title.trim() || !fields.script_text.trim())
      throw new ApiError('剧本标题和正文不能为空', { status: 422, code: 'validation_error' });
    const versions = scriptVersions(value);
    const saved = {
      ...fields,
      id: `demo-script-new-${++demo.sequence}`,
      project_id: projectId,
      version: Math.max(0, ...versions.map((item) => item.version || 0)) + 1,
      content: {},
      events: [],
      status: 'edited',
      approved: false,
      demo: true,
      created_at: new Date().toISOString(),
      workspace_meta: {
        source,
        base_script_id: value.script?.id ?? null,
        requires_reconfirmation: true,
      },
    };
    versions.unshift(saved);
    value.script = saved;
    syncWorkspace(value);
    return saved;
  }

  function validateScriptFile(file) {
    if (!file) throw new ApiError('请先选择剧本文件', { code: 'file_required' });
    const extension = String(file.name || '')
      .split('.')
      .pop()
      .toLowerCase();
    if (!['txt', 'md', 'json', 'docx'].includes(extension))
      throw new ApiError('剧本文件支持 TXT、MD、JSON 或 DOCX', {
        status: 422,
        code: 'invalid_file_type',
      });
    if (file.size > SCRIPT_IMPORT_LIMIT)
      throw new ApiError('剧本文件不能超过 2 MiB', { status: 422, code: 'file_too_large' });
    return extension;
  }

  function listMethod(suffix, key) {
    return (projectId, options = {}) =>
      act(
        options,
        () => workspace(projectId)[key] ?? [],
        async () =>
          items(
            await request(`/projects/${segment(projectId)}/${suffix}`, {
              signal: options.signal,
              query: options.query,
            }),
          ),
      );
  }

  function resourceMethods(resource, demoKey) {
    return {
      get: (id, options = {}) =>
        act(
          options,
          () => findEntity(demoKey, id).value,
          () => request(`/${resource}/${segment(id)}`, { signal: options.signal }),
        ),
      update: (id, payload, options = {}) =>
        act(
          options,
          () => {
            const found = findEntity(demoKey, id);
            Object.assign(found.value, clone(payload));
            syncWorkspace(found.workspace);
            return found.value;
          },
          () =>
            request(`/${resource}/${segment(id)}`, {
              method: 'PATCH',
              body: payload,
              signal: options.signal,
            }),
        ),
      approve: (id, options = {}) =>
        act(
          options,
          () => {
            const found = findEntity(demoKey, id);
            Object.assign(found.value, {
              approved: true,
              status: 'approved',
              approved_version: found.value.approved_version || 1,
            });
            return found.value;
          },
          () =>
            request(`/${resource}/${segment(id)}/approve`, {
              method: 'POST',
              signal: options.signal,
            }),
        ),
    };
  }

  const characterApi = resourceMethods('characters', 'characters');
  const sceneApi = resourceMethods('scenes', 'scenes');
  const shotApi = resourceMethods('shots', 'shots');
  const scriptApi = resourceMethods('scripts', 'script');

  const api = {
    get mode() {
      return connection.mode;
    },
    get isDemo() {
      return connection.isDemo;
    },
    configure,
    getConnection: () => ({ ...connection }),
    resetDemo() {
      demo = createDemoState();
    },

    getProjects: (options = {}) =>
      act(
        options,
        () => demo.projects,
        async () =>
          items(
            await request('/projects', {
              signal: options.signal,
              query: { limit: options.limit ?? 50 },
            }),
          ),
      ),
    getProject: (id, options = {}) =>
      act(
        options,
        () => workspace(id).project,
        () => request(`/projects/${segment(id)}`, { signal: options.signal }),
      ),
    createProject: (payload, options = {}) =>
      act(
        options,
        () => {
          if (!String(payload?.name ?? '').trim())
            throw new ApiError('请输入项目名称', { status: 422, code: 'validation_error' });
          const now = new Date().toISOString();
          const project = {
            id: `demo-project-new-${++demo.sequence}`,
            name: payload.name.trim(),
            description: payload.description ?? '',
            genre: payload.genre ?? '',
            language: payload.language ?? 'zh',
            aspect_ratio: payload.aspect_ratio ?? '16:9',
            budget_limit_usd: payload.budget_limit_usd ?? 0,
            spent_usd: 0,
            settings: clone(payload.settings ?? {}),
            status: 'draft',
            owner_id: connection.userId,
            created_at: now,
            updated_at: now,
            demo: true,
            progress: 0,
            cover_url: demoArtwork(payload.name),
          };
          const summary = {
            project_id: project.id,
            name: project.name,
            status: 'draft',
            shot_count: 0,
            characters: [],
            scenes: [],
            total_duration_seconds: 0,
            demo: true,
            progress: 0,
          };
          const value = {
            project,
            summary,
            workflow: null,
            pending_reviews: [],
            reviews: [],
            tasks: [],
            script: null,
            characters: [],
            scenes: [],
            shots: [],
            assets: [],
            documents: [],
            chapters: [],
            activities: [],
            agentCatalog: clone(AGENT_CATALOG),
            demo: true,
          };
          value.dashboard = {
            project,
            summary,
            workflow: null,
            pending_reviews: [],
            tasks: [],
            editing: null,
            film: null,
            evaluation: null,
            demo: true,
            progress: 0,
          };
          demo.projects.unshift(project);
          demo.workspaces[project.id] = value;
          return project;
        },
        () => request('/projects', { method: 'POST', body: payload, signal: options.signal }),
      ),
    updateProject: (id, payload, options = {}) =>
      act(
        options,
        () => {
          const value = workspace(id);
          Object.assign(value.project, clone(payload), { updated_at: new Date().toISOString() });
          return syncWorkspace(value).project;
        },
        () =>
          request(`/projects/${segment(id)}`, {
            method: 'PATCH',
            body: payload,
            signal: options.signal,
          }),
      ),
    getDashboard: (id, options = {}) =>
      act(
        options,
        () => syncWorkspace(workspace(id)).dashboard,
        () => request(`/projects/${segment(id)}/dashboard`, { signal: options.signal }),
      ),
    getSummary: (id, options = {}) =>
      act(
        options,
        () => syncWorkspace(workspace(id)).summary,
        () => request(`/projects/${segment(id)}/summary`, { signal: options.signal }),
      ),

    async getWorkspace(id, options = {}) {
      if (connection.isDemo)
        return act(
          options,
          () => syncWorkspace(workspace(id)),
          () => null,
        );
      // dashboard 先验证项目存在与访问权；只吞掉已知的“尚无剧本”业务空态。
      const dashboard = await api.getDashboard(id, options);
      const [
        script,
        characters,
        scenes,
        shots,
        assets,
        reviews,
        directing,
        storyboard,
        documents,
        chapters,
      ] = await Promise.all([
        api.getScript(id, options),
        api.getCharacters(id, options),
        api.getScenes(id, options),
        api.getShots(id, options),
        api.getAssets(id, options),
        api.getReviews(id, options),
        api.getDirecting(id, options),
        api.getStoryboard(id, options),
        api.getDocuments(id, options),
        api.getChapters(id, options),
      ]);
      return {
        project: dashboard.project,
        dashboard,
        summary: dashboard.summary,
        workflow: dashboard.workflow,
        pending_reviews: dashboard.pending_reviews ?? [],
        tasks: dashboard.tasks ?? [],
        script,
        characters,
        scenes,
        shots,
        assets,
        reviews,
        directing: directing.plan,
        directing_versions: directing.versions,
        storyboard: storyboard.board,
        storyboard_versions: storyboard.versions,
        editing: dashboard.editing,
        evaluation: dashboard.evaluation,
        documents,
        chapters,
        activities: [],
        agentCatalog: [],
        demo: false,
      };
    },

    importSample: (id, options = {}) =>
      act(
        options,
        () => {
          const value = workspace(id),
            template = createDemoState().workspaces['demo-rainy-bookstore'];
          const document = {
            ...template.documents[0],
            id: `demo-document-new-${++demo.sequence}`,
            project_id: id,
          };
          const chapters = template.chapters.map((chapter, index) => ({
            ...chapter,
            id: `${document.id}-chapter-${index + 1}`,
            project_id: id,
          }));
          value.documents.push(document);
          value.chapters.push(...chapters);
          return { document, chapters };
        },
        () =>
          request(`/projects/${segment(id)}/upload`, {
            method: 'POST',
            query: { sample: true },
            signal: options.signal,
          }),
      ),
    uploadDocument: (id, file, options = {}) =>
      act(
        options,
        () => {
          if (!file) throw new ApiError('请先选择文件', { code: 'file_required' });
          const value = workspace(id);
          const document = {
            id: `demo-document-new-${++demo.sequence}`,
            project_id: id,
            filename: file.name,
            title: file.name,
            status: 'uploaded',
            created_at: new Date().toISOString(),
            demo: true,
          };
          value.documents.push(document);
          return { document, chapters: [] };
        },
        () => {
          if (!file) throw new ApiError('请先选择文件', { code: 'file_required' });
          const form = new FormData();
          form.append('file', file);
          return request(`/projects/${segment(id)}/upload`, {
            method: 'POST',
            body: form,
            signal: options.signal,
          });
        },
      ),
    parseDocument: (projectId, documentId, options = {}) =>
      act(
        options,
        () => demoTask(projectId, 'parse_document'),
        () =>
          request(`/projects/${segment(projectId)}/documents/${segment(documentId)}/parse`, {
            method: 'POST',
            query: { wait: options.wait ?? false },
            signal: options.signal,
          }),
      ),
    getDocuments: listMethod('documents', 'documents'),
    getChapters: listMethod('chapters', 'chapters'),
    getScripts: (id, options = {}) =>
      act(
        options,
        () => scriptVersions(workspace(id)),
        async () =>
          items(await request(`/projects/${segment(id)}/scripts`, { signal: options.signal })),
      ),
    getScript: (projectId, options = {}) =>
      act(
        options,
        () => workspace(projectId).script,
        async () => {
          try {
            return await request(`/projects/${segment(projectId)}/script`, {
              signal: options.signal,
            });
          } catch (error) {
            if (
              error instanceof ApiError &&
              error.status === 404 &&
              error.code === 'not_found' &&
              error.message === '该项目还没有剧本' &&
              error.details?.project_id === projectId
            )
              return null;
            throw error;
          }
        },
      ),
    getScriptVersion: (scriptId, options = {}) =>
      act(
        options,
        () => {
          for (const value of Object.values(demo.workspaces)) {
            const found = scriptVersions(value).find((item) => item.id === scriptId);
            if (found) return found;
          }
          throw new ApiError('剧本版本不存在', { status: 404, code: 'not_found' });
        },
        () => request(`/scripts/${segment(scriptId)}`, { signal: options.signal }),
      ),
    createScript: (id, payload, options = {}) =>
      act(
        options,
        () => saveDemoScript(id, payload),
        () =>
          request(`/projects/${segment(id)}/scripts`, {
            method: 'POST',
            body: payload,
            signal: options.signal,
          }),
      ),
    importScript: (id, file, options = {}) =>
      act(
        options,
        async () => {
          const extension = validateScriptFile(file);
          if (extension === 'docx')
            throw new ApiError('演示模式不解析 DOCX，请使用 TXT、MD、JSON，或连接真实后端导入', {
              status: 422,
              code: 'unsupported_demo_format',
            });
          const text = await file.text();
          abortIfNeeded(options.signal);
          let fields = { title: file.name.replace(/\.[^.]+$/, ''), script_text: text };
          if (extension === 'json') {
            let parsed;
            try {
              parsed = JSON.parse(text);
            } catch {
              throw new ApiError('JSON 剧本格式无效', { status: 422, code: 'validation_error' });
            }
            if (!parsed || Array.isArray(parsed) || typeof parsed.script_text !== 'string')
              throw new ApiError('JSON 剧本必须包含字符串字段 script_text', {
                status: 422,
                code: 'validation_error',
              });
            fields = { ...scriptFields(parsed), title: parsed.title || fields.title };
          }
          return saveDemoScript(
            id,
            { ...fields, base_script_id: options.base_script_id },
            'import',
          );
        },
        () => {
          validateScriptFile(file);
          const form = new FormData();
          form.append('file', file);
          if (options.base_script_id) form.append('base_script_id', options.base_script_id);
          return request(`/projects/${segment(id)}/scripts/import`, {
            method: 'POST',
            body: form,
            signal: options.signal,
          });
        },
      ),
    restoreScriptVersion: (id, scriptId, options = {}) =>
      act(
        options,
        () => {
          const value = workspace(id);
          const found = scriptVersions(value).find((item) => item.id === scriptId);
          if (!found) throw new ApiError('剧本版本不存在', { status: 404, code: 'not_found' });
          return saveDemoScript(
            id,
            { ...scriptFields(found), base_script_id: options.base_script_id },
            'restore',
          );
        },
        () =>
          request(`/projects/${segment(id)}/scripts/${segment(scriptId)}/restore`, {
            method: 'POST',
            body: { base_script_id: options.base_script_id ?? null },
            signal: options.signal,
          }),
      ),
    assistScript: (id, payload, options = {}) =>
      act(
        options,
        () => {
          const value = workspace(id);
          checkScriptBase(value, payload.base_script_id);
          if (!value.script || !['polish', 'continue'].includes(payload.operation))
            throw new ApiError('请先保存剧本，再选择润色或续写', {
              status: 422,
              code: 'validation_error',
            });
          const result = demoTask(id, 'script_assist');
          result.task.message = 'AI 辅助模拟已记录；未调用模型，也未创建 AI 剧本版本';
          result.task.result = { demo: true, simulated: true, operation: payload.operation };
          return result;
        },
        () => {
          needConfirmation(options);
          return request(`/projects/${segment(id)}/scripts/assist`, {
            method: 'POST',
            body: payload,
            signal: options.signal,
            query: { wait: options.wait ?? false },
          });
        },
      ),
    updateScript: scriptApi.update,
    getCharacters: listMethod('characters', 'characters'),
    getCharacter: characterApi.get,
    updateCharacter: characterApi.update,
    approveCharacter: characterApi.approve,
    getCharacterAssets: (id, options = {}) =>
      act(
        options,
        () => {
          const found = findEntity('characters', id);
          return found.workspace.assets.filter((asset) => asset.meta?.character_id === id);
        },
        async () =>
          items(await request(`/characters/${segment(id)}/assets`, { signal: options.signal })),
      ),
    getScenes: listMethod('scenes', 'scenes'),
    getScene: sceneApi.get,
    updateScene: sceneApi.update,
    approveScene: sceneApi.approve,
    getShots: listMethod('shots', 'shots'),
    getShot: shotApi.get,
    async updateShot(id, payload, options = {}) {
      if (!connection.isDemo) return shotApi.update(id, payload, options);
      abortIfNeeded(options.signal);
      const found = findEntity('shots', id),
        board = found.workspace.storyboard;
      if (payload.base_storyboard_id && payload.base_storyboard_id !== board?.id)
        throw new ApiError('分镜版本已变化', { status: 409, code: 'conflict' });
      if (
        payload.base_shot_fingerprint &&
        payload.base_shot_fingerprint !== found.value.edit_fingerprint
      )
        throw new ApiError('镜头已被修改，请核对最新内容', { status: 409, code: 'conflict' });
      const { base_storyboard_id, base_shot_fingerprint, ...fields } = payload;
      const projectFields = () =>
        Object.fromEntries(Object.keys(fields).map((key) => [key, found.value[key]]));
      const before = JSON.stringify(demoComparable(projectFields()));
      await shotApi.update(id, fields, options);
      if (before !== JSON.stringify(demoComparable(projectFields()))) {
        found.value.approved = false;
        found.value.edit_fingerprint = `demo-edit-${++demo.sequence}`;
        if (board) Object.assign(board, { approved: false, status: 'draft' });
      }
      syncWorkspace(found.workspace);
      return clone(found.value);
    },
    approveShot: shotApi.approve,
    getAssets: (id, options = {}) =>
      act(
        options,
        () => workspace(id).assets.filter((asset) => !options.kind || asset.kind === options.kind),
        async () =>
          items(
            await request(`/projects/${segment(id)}/assets`, {
              signal: options.signal,
              query: { kind: options.kind, limit: options.limit ?? 100 },
            }),
          ),
      ),
    getDirecting: (id, options = {}) =>
      act(
        options,
        () => ({
          plan: workspace(id).directing ?? null,
          versions: workspace(id).directing_versions ?? [],
        }),
        () => request(`/projects/${segment(id)}/directing`, { signal: options.signal }),
      ),
    generateDirecting: (id, payload = {}, options = {}) =>
      act(
        options,
        () => {
          const value = workspace(id);
          if (!value.script)
            throw new ApiError('请先保存剧本，再生成导演方案', {
              status: 422,
              code: 'validation_error',
            });
          if (payload.base_script_id !== undefined) checkScriptBase(value, payload.base_script_id);
          const result = demoTask(id, 'directing');
          result.task.message = '导演模拟操作已记录；未调用模型，当前方案仍为静态示例';
          return result;
        },
        () => {
          needConfirmation(options);
          return request(`/projects/${segment(id)}/direct`, {
            method: 'POST',
            body: payload,
            signal: options.signal,
            query: { wait: options.wait ?? false },
          });
        },
      ),
    getDirectingPlan: (id, options = {}) =>
      act(
        options,
        () => {
          for (const value of Object.values(demo.workspaces)) {
            const found = (value.directing_versions ?? []).find((plan) => plan.id === id);
            if (found) return found;
          }
          throw new ApiError('导演规划版本不存在', { status: 404, code: 'not_found' });
        },
        () => request(`/directing-plans/${segment(id)}`, { signal: options.signal }),
      ),
    getStoryboard: (id, options = {}) =>
      act(
        options,
        () => ({
          board: workspace(id).storyboard ?? null,
          versions:
            workspace(id).storyboard_versions ??
            (workspace(id).storyboard ? [workspace(id).storyboard] : []),
        }),
        () => request(`/projects/${segment(id)}/storyboards`, { signal: options.signal }),
      ),
    getStoryboardVersion: (id, options = {}) =>
      act(
        options,
        () => {
          for (const value of Object.values(demo.workspaces)) {
            const found = (
              value.storyboard_versions ?? (value.storyboard ? [value.storyboard] : [])
            ).find((board) => board.id === id);
            if (found)
              return {
                ...found,
                shots: found.id === value.storyboard?.id ? value.shots : found.shots || [],
              };
          }
          throw new ApiError('分镜版本不存在', { status: 404, code: 'not_found' });
        },
        () => request(`/storyboards/${segment(id)}`, { signal: options.signal }),
      ),
    generateStoryboard: (id, payload = {}, options = {}) =>
      act(
        options,
        () => {
          const value = workspace(id);
          if (!value.script || !value.directing)
            throw new ApiError('请先完成剧本与导演方案', { status: 422, code: 'validation_error' });
          if (payload.base_script_id !== undefined) checkScriptBase(value, payload.base_script_id);
          if (payload.base_plan_id && payload.base_plan_id !== value.directing.id)
            throw new ApiError('导演方案已变化', { status: 409, code: 'conflict' });
          const result = demoTask(id, 'storyboard');
          result.task.message = '分镜模拟操作已记录；没有调用模型或创建真实分镜';
          return result;
        },
        () => {
          needConfirmation(options);
          return request(`/projects/${segment(id)}/storyboards`, {
            method: 'POST',
            body: payload,
            signal: options.signal,
            query: { wait: options.wait ?? false },
          });
        },
      ),
    requestStoryboardReview: (id, boardId, options = {}) =>
      act(
        options,
        () => {
          const value = workspace(id),
            board = value.storyboard;
          if (!board || board.id !== boardId)
            throw new ApiError('分镜版本不存在', { status: 404, code: 'not_found' });
          const pending = value.reviews.find(
            (review) => review.stage === 'storyboard' && review.status === 'pending',
          );
          if (pending) {
            if (pending.target_id === boardId && pending.target_status === 'current')
              return pending;
            throw new ApiError('请先退回旧的待审内容，再重新提交', {
              status: 409,
              code: 'conflict',
            });
          }
          const snapshot = {
            storyboard_id: boardId,
            storyboard_version: board.version,
            directing_plan_id: board.directing_plan_id,
            source_script: board.source_script,
            storyboard_fingerprint: 'demo',
            shot_fingerprints: Object.fromEntries(
              value.shots.map((shot) => [shot.id, shot.edit_fingerprint || 'demo']),
            ),
          };
          const review = {
            id: `demo-review-${++demo.sequence}`,
            project_id: id,
            stage: 'storyboard',
            target_type: 'storyboard',
            target_id: boardId,
            target_snapshot: snapshot,
            target_status: 'current',
            status: 'pending',
            title: '分镜与导演方案审核',
            description: 'DEMO 内存审核，不产生真实审批结果',
            decision: { storyboard_snapshot: snapshot },
            created_at: new Date().toISOString(),
          };
          value.reviews.unshift(review);
          syncWorkspace(value);
          return review;
        },
        () =>
          request(`/projects/${segment(id)}/storyboards/${segment(boardId)}/review`, {
            method: 'POST',
            signal: options.signal,
          }),
      ),
    getShotVersions: (id, options = {}) =>
      act(
        options,
        () => {
          findEntity('shots', id);
          return { shot_id: id, selected_video_id: null, items: [], count: 0 };
        },
        () => request(`/shots/${segment(id)}/versions`, { signal: options.signal }),
      ),
    selectShotVersion: (id, versionId, options = {}) =>
      act(
        options,
        () => ({ shot: findEntity('shots', id).value, video: { id: versionId, demo: true } }),
        () =>
          request(`/shots/${segment(id)}/versions/${segment(versionId)}/select`, {
            method: 'POST',
            signal: options.signal,
          }),
      ),
    getAudio: listMethod('audio', 'audio'),
    getEditing: (id, options = {}) =>
      act(
        options,
        () => ({
          editing: workspace(id).editing ?? null,
          versions: [],
          film: workspace(id).dashboard.film ?? null,
        }),
        () => request(`/projects/${segment(id)}/editing`, { signal: options.signal }),
      ),
    getExport: (id, options = {}) =>
      act(
        options,
        () => ({
          film: workspace(id).dashboard.film ?? null,
          ready: Boolean(workspace(id).dashboard.film),
        }),
        () => request(`/projects/${segment(id)}/export`, { signal: options.signal }),
      ),
    getEvaluation: (id, options = {}) =>
      act(
        options,
        () => ({ evaluation: workspace(id).evaluation ?? null, metrics: {} }),
        () => request(`/projects/${segment(id)}/evaluation`, { signal: options.signal }),
      ),

    getWorkflows: (id, options = {}) =>
      act(
        options,
        () => (workspace(id).workflow ? [workspace(id).workflow] : []),
        async () =>
          items(await request(`/projects/${segment(id)}/workflows`, { signal: options.signal })),
      ),
    getWorkflow: (id, runId, options = {}) =>
      act(
        options,
        () => {
          const value = workspace(id);
          if (value.workflow?.id !== runId)
            throw new ApiError('工作流不存在', { status: 404, code: 'not_found' });
          return { run: value.workflow, checkpoints: [] };
        },
        () =>
          request(`/projects/${segment(id)}/workflows/${segment(runId)}`, {
            signal: options.signal,
          }),
      ),
    startWorkflow: (id, payload = {}, options = {}) =>
      act(
        options,
        () => {
          const value = workspace(id);
          const result = demoTask(id, 'workflow');
          value.workflow ??= {
            id: `demo-run-new-${++demo.sequence}`,
            project_id: id,
            workflow_id: payload.workflow_id ?? 'novel_to_video',
            status: 'awaiting_review',
            created_at: new Date().toISOString(),
            demo: true,
          };
          result.task.result = {
            demo: true,
            simulated: true,
            message: '只演示操作流程；未生成新内容',
          };
          syncWorkspace(value);
          return result;
        },
        () => {
          needConfirmation(options);
          return request(`/projects/${segment(id)}/workflows/start`, {
            method: 'POST',
            body: payload,
            signal: options.signal,
            query: { wait: options.wait ?? false },
          });
        },
      ),
    resumeWorkflow: (id, runId, options = {}) =>
      act(
        options,
        () => {
          workspace(id);
          return demoTask(id, 'workflow_resume');
        },
        () => {
          needConfirmation(options);
          return request(`/projects/${segment(id)}/workflows/${segment(runId)}/resume`, {
            method: 'POST',
            signal: options.signal,
            query: { wait: options.wait ?? false },
          });
        },
      ),
    cancelWorkflow: (id, runId, options = {}) =>
      act(
        options,
        () => {
          const value = workspace(id);
          if (value.workflow?.id !== runId)
            throw new ApiError('工作流不存在', { status: 404, code: 'not_found' });
          value.workflow.status = 'cancelled';
          return value.workflow;
        },
        () =>
          request(`/projects/${segment(id)}/workflows/${segment(runId)}/cancel`, {
            method: 'POST',
            signal: options.signal,
          }),
      ),
    getTasks: (id, options = {}) =>
      act(
        options,
        () => workspace(id).tasks,
        async () =>
          items(
            await request(`/projects/${segment(id)}/tasks`, {
              signal: options.signal,
              query: { limit: options.limit ?? 50 },
            }),
          ),
      ),
    getTask: (id, taskId, options = {}) =>
      act(
        options,
        () => {
          const task = workspace(id).tasks.find((entry) => entry.id === taskId);
          if (!task) throw new ApiError('任务不存在', { status: 404, code: 'not_found' });
          return { task, events: demo.taskEvents[taskId] ?? [] };
        },
        () =>
          request(`/projects/${segment(id)}/tasks/${segment(taskId)}`, { signal: options.signal }),
      ),
    getTaskEvents: (id, taskId, options = {}) =>
      act(
        options,
        () => {
          const value = workspace(id);
          if (!value.tasks.some((task) => task.id === taskId))
            throw new ApiError('任务不存在', { status: 404, code: 'not_found' });
          const events = demo.taskEvents[taskId] ?? [];
          const after = options.after
            ? events.findIndex((entry) => entry.id === options.after) + 1
            : 0;
          return events.slice(after, after + (options.limit ?? 200));
        },
        async () =>
          items(
            await request(`/projects/${segment(id)}/tasks/${segment(taskId)}/events`, {
              signal: options.signal,
              query: { after: options.after, limit: options.limit ?? 200 },
            }),
          ),
      ),
    cancelTask: (id, taskId, options = {}) =>
      act(
        options,
        () => {
          const task = workspace(id).tasks.find((entry) => entry.id === taskId);
          if (!task) throw new ApiError('任务不存在', { status: 404, code: 'not_found' });
          if (!['succeeded', 'failed', 'cancelled'].includes(task.status))
            task.status = 'cancelled';
          return { task };
        },
        () =>
          request(`/projects/${segment(id)}/tasks/${segment(taskId)}/cancel`, {
            method: 'POST',
            signal: options.signal,
          }),
      ),
    getReviews: (id, options = {}) =>
      act(
        options,
        () =>
          workspace(id).reviews.filter(
            (review) => !options.status || review.status === options.status,
          ),
        async () =>
          items(
            await request(`/projects/${segment(id)}/reviews`, {
              signal: options.signal,
              query: { status: options.status },
            }),
          ),
      ),
    getReview: (id, options = {}) =>
      act(
        options,
        () => findEntity('reviews', id).value,
        () => request(`/reviews/${segment(id)}`, { signal: options.signal }),
      ),
    decideReview: (id, payload, options = {}) =>
      act(
        options,
        () => {
          if (!['approved', 'rejected'].includes(payload.status))
            throw new ApiError('审核结果只能是 approved 或 rejected', {
              status: 422,
              code: 'validation_error',
            });
          const found = findEntity('reviews', id);
          if (found.value.status !== 'pending')
            throw new ApiError('该审核已经处理', { status: 409, code: 'conflict' });
          if (
            found.value.stage === 'storyboard' &&
            payload.status === 'approved' &&
            found.value.target_status !== 'current'
          )
            throw new ApiError('分镜待审快照已变化，请退回后重新提交', {
              status: 409,
              code: 'conflict',
            });
          const snapshot = found.value.decision?.storyboard_snapshot;
          Object.assign(found.value, {
            status: payload.status,
            comment: payload.comment ?? '',
            decision: {
              ...clone(payload.decision ?? {}),
              ...(snapshot ? { storyboard_snapshot: snapshot } : {}),
            },
            reviewer_id: connection.userId,
            reviewed_at: new Date().toISOString(),
          });
          if (payload.status === 'approved' && found.value.stage === 'storyboard') {
            if (found.workspace.storyboard)
              Object.assign(found.workspace.storyboard, { approved: true, status: 'approved' });
            if (found.workspace.directing)
              Object.assign(found.workspace.directing, { approved: true, status: 'approved' });
            found.workspace.shots.forEach((shot) => {
              shot.approved = true;
            });
            found.workspace.project.status = 'storyboard_ready';
          }
          syncWorkspace(found.workspace);
          return {
            review: found.value,
            ...(payload.resume_workflow
              ? demoTask(found.workspace.project.id, 'workflow_resume')
              : {}),
          };
        },
        () => {
          const body = {
            status: payload.status,
            comment: payload.comment ?? '',
            decision: payload.decision ?? {},
            resume_workflow: payload.resume_workflow ?? false,
          };
          if (body.resume_workflow) needConfirmation(options);
          return request(`/reviews/${segment(id)}`, {
            method: 'POST',
            body,
            signal: options.signal,
            query: { wait: options.wait ?? false },
          });
        },
      ),
    getReviewComments: (id, options = {}) =>
      act(
        options,
        () => findEntity('reviews', id).value.comments ?? [],
        async () =>
          items(await request(`/reviews/${segment(id)}/comments`, { signal: options.signal })),
      ),
    addReviewComment: (id, body, options = {}) =>
      act(
        options,
        () => {
          const found = findEntity('reviews', id).value;
          const comment = {
            id: `demo-comment-${++demo.sequence}`,
            body,
            user_id: connection.userId,
            created_at: new Date().toISOString(),
          };
          (found.comments ??= []).push(comment);
          return comment;
        },
        () =>
          request(`/reviews/${segment(id)}/comments`, {
            method: 'POST',
            body: { body },
            signal: options.signal,
          }),
      ),

    getMeta: (options = {}) =>
      act(
        options,
        () => demo.meta,
        () => request('/meta', { signal: options.signal }),
      ),
    getProjectMeta: (id, options = {}) =>
      act(
        options,
        () => ({ project_id: workspace(id).project.id, ...demo.meta }),
        () => request(`/projects/${segment(id)}/meta`, { signal: options.signal }),
      ),
    getProviders: (options = {}) =>
      act(
        options,
        () => demo.providers,
        async () => items(await request('/admin/providers', { signal: options.signal })),
      ),
    getSystemStatus: (options = {}) =>
      act(
        options,
        () => ({
          app: 'AI Film Studio',
          env: 'demo',
          database: 'memory',
          storage_backend: 'memory',
          agents: { count: demo.agentConfigs.length, enabled: demo.agentConfigs.length },
          ffmpeg: { available: false },
          tasks: { inline: true, max_workers: 0 },
          demo: true,
        }),
        () => request('/admin/status', { signal: options.signal }),
      ),
    getWorkflowConfigs: (options = {}) =>
      act(
        options,
        () => demo.meta.workflows,
        async () => items(await request('/admin/workflows', { signal: options.signal })),
      ),
    getAgentConfigs: (options = {}) =>
      act(
        options,
        () => demo.agentConfigs,
        async () => items(await request('/admin/model-configs', { signal: options.signal })),
      ),
    getAgentConfig: (id, options = {}) =>
      act(
        options,
        () => {
          const config = demo.agentConfigs.find((item) => item.id === id);
          if (!config) throw new ApiError('智能体配置不存在', { status: 404, code: 'not_found' });
          return { id, payload: config.payload, versions: config.versions };
        },
        () => request(`/admin/model-configs/${segment(id)}`, { signal: options.signal }),
      ),
    updateAgentConfig: (id, payload, options = {}) =>
      act(
        options,
        () => {
          const config = demo.agentConfigs.find((item) => item.id === id);
          if (!config) throw new ApiError('智能体配置不存在', { status: 404, code: 'not_found' });
          const version = {
            id: `demo-config-${++demo.sequence}`,
            version: config.versions.length + 1,
            scope: 'agent',
            key: id,
            payload: clone(payload),
            note: options.note ?? '',
            is_active: true,
            created_at: new Date().toISOString(),
          };
          config.versions.forEach((entry) => {
            entry.is_active = false;
          });
          config.versions.unshift(version);
          config.active_version = version.version;
          config.payload = clone(payload);
          config.model_id = payload.model?.model_id ?? config.model_id;
          config.provider = payload.model?.provider ?? config.provider;
          config.enabled = payload.agent?.enabled ?? config.enabled;
          return { id, version, applied: config.payload };
        },
        () =>
          request(`/admin/model-configs/${segment(id)}/versions`, {
            method: 'POST',
            body: { payload, note: options.note ?? '' },
            signal: options.signal,
          }),
      ),
    getAgentConfigVersions: (id, options = {}) =>
      act(
        options,
        () => demo.agentConfigs.find((item) => item.id === id)?.versions ?? [],
        async () =>
          items(
            await request(`/admin/model-configs/${segment(id)}/versions`, {
              signal: options.signal,
            }),
          ),
      ),
    rollbackAgentConfig: (id, options = {}) =>
      act(
        options,
        () => {
          const config = demo.agentConfigs.find((item) => item.id === id);
          const previous = config?.versions[1];
          if (!previous)
            throw new ApiError('没有可回滚的历史版本', { status: 409, code: 'conflict' });
          config.versions.forEach((entry) => {
            entry.is_active = entry.id === previous.id;
          });
          config.payload = clone(previous.payload);
          config.model_id = config.payload.model?.model_id ?? config.model_id;
          return { id, version: previous, applied: config.payload };
        },
        () =>
          request(`/admin/model-configs/${segment(id)}/rollback`, {
            method: 'POST',
            signal: options.signal,
          }),
      ),
    activateAgentConfigVersion: (versionId, options = {}) =>
      act(
        options,
        () => {
          const config = demo.agentConfigs.find((item) =>
            item.versions.some((version) => version.id === versionId),
          );
          const version = config?.versions.find((item) => item.id === versionId);
          if (!version) throw new ApiError('配置版本不存在', { status: 404, code: 'not_found' });
          config.versions.forEach((item) => {
            item.is_active = item.id === versionId;
          });
          config.active_version = version.version;
          config.payload = clone(version.payload);
          config.model_id = config.payload.model?.model_id ?? config.model_id;
          config.provider = config.payload.model?.provider ?? config.provider;
          config.enabled = config.payload.agent?.enabled ?? config.enabled;
          return { version, applied: config.payload };
        },
        () =>
          request(`/admin/model-config-versions/${segment(versionId)}/activate`, {
            method: 'POST',
            signal: options.signal,
          }),
      ),
    resetAgentConfig: (id, options = {}) =>
      act(
        options,
        () => {
          const index = demo.agentConfigs.findIndex((item) => item.id === id);
          const initialConfig = createDemoState().agentConfigs.find((item) => item.id === id);
          if (index < 0 || !initialConfig)
            throw new ApiError('智能体配置不存在', { status: 404, code: 'not_found' });
          demo.agentConfigs[index] = initialConfig;
          return { id, applied: initialConfig.payload };
        },
        () =>
          request(`/admin/model-configs/${segment(id)}/override`, {
            method: 'DELETE',
            signal: options.signal,
          }),
      ),

    async getAgentCatalog(options = {}) {
      return act(
        options,
        () =>
          AGENT_CATALOG.map((family) => {
            const configs = demo.agentConfigs.filter((item) => family.agent_ids.includes(item.id));
            return {
              ...family,
              enabled: configs.some((item) => item.enabled),
              model_id: [...new Set(configs.map((item) => item.model_id))].join(' / '),
              status: 'demo',
            };
          }),
        async () => {
          let configs;
          try {
            configs = await api.getAgentConfigs(options);
          } catch (error) {
            if (!(error instanceof ApiError) || error.status !== 403) throw error;
            // 普通成员可看注册目录，不可读取管理员配置；注册不代表启用或健康。
            const meta = await api.getMeta(options);
            const registered = new Set(meta.agents ?? []);
            return AGENT_CATALOG.map((family) => {
              const registeredIds = family.agent_ids.filter((id) => registered.has(id));
              return {
                ...family,
                agent_ids: [...family.agent_ids],
                registered_agent_ids: registeredIds,
                status: registeredIds.length ? 'registered' : 'unregistered',
                config_access: false,
                enabled: null,
                model_id: null,
                provider: null,
              };
            });
          }
          return AGENT_CATALOG.map((family) => {
            const members = configs.filter((item) => family.agent_ids.includes(item.id));
            return {
              ...family,
              status: members.length
                ? members.some((item) => item.enabled)
                  ? 'configured'
                  : 'disabled'
                : 'unconfigured',
              enabled: members.some((item) => item.enabled),
              model_id:
                [...new Set(members.map((item) => item.model_id).filter(Boolean))].join(' / ') ||
                null,
              provider:
                [...new Set(members.map((item) => item.provider).filter(Boolean))].join(' / ') ||
                null,
              agent_ids: members.map((item) => item.id),
              config_access: true,
            };
          });
        },
      );
    },
    getAgents: (options = {}) => api.getAgentCatalog(options),

    runStage(id, stage, payloadOrOptions = {}, explicitOptions) {
      // 通用阶段入口保留无请求体兼容；导演创作参数通过 generateDirecting 独立传递。
      const options = explicitOptions ?? payloadOrOptions;
      return act(
        options,
        () => {
          if (!STAGE_PATHS[stage])
            throw new ApiError('不支持的制作阶段', { code: 'invalid_stage', details: { stage } });
          return demoTask(id, stage);
        },
        () => {
          const path = STAGE_PATHS[stage];
          if (!path)
            throw new ApiError('不支持的制作阶段', { code: 'invalid_stage', details: { stage } });
          needConfirmation(options);
          return request(`/projects/${segment(id)}/${path}`, {
            method: 'POST',
            signal: options.signal,
            query: { wait: options.wait ?? false },
          });
        },
      );
    },
    generateCharacterImages: (id, payload = {}, options = {}) =>
      act(
        options,
        () => demoTask(findEntity('characters', id).workspace.project.id, 'character_images'),
        () => {
          needConfirmation(options);
          return request(`/characters/${segment(id)}/generate-images`, {
            method: 'POST',
            body: payload,
            signal: options.signal,
            query: { wait: options.wait ?? false },
          });
        },
      ),
    generateCharacterViews: (id, payload = {}, options = {}) =>
      act(
        options,
        () => demoTask(findEntity('characters', id).workspace.project.id, 'character_views'),
        () => {
          needConfirmation(options);
          return request(`/characters/${segment(id)}/generate-views`, {
            method: 'POST',
            signal: options.signal,
            query: { wait: options.wait ?? false },
          });
        },
      ),
    generateShot: (id, options = {}) =>
      act(
        options,
        () => demoTask(findEntity('shots', id).workspace.project.id, 'shot_video'),
        () => {
          needConfirmation(options);
          return request(`/shots/${segment(id)}/generate`, {
            method: 'POST',
            signal: options.signal,
            query: { wait: options.wait ?? false },
          });
        },
      ),

    /** 使用 fetch 读取 SSE，才能携带身份头；调用方用 AbortController 停止监听。 */
    async *streamTaskEvents(projectId, taskId, options = {}) {
      abortIfNeeded(options.signal);
      if (connection.isDemo) {
        for (const event of await api.getTaskEvents(projectId, taskId, options)) {
          abortIfNeeded(options.signal);
          yield { event: 'task', data: event };
        }
        yield { event: 'end', data: {} };
        return;
      }
      const response = await request(
        `/projects/${segment(projectId)}/tasks/${segment(taskId)}/events/stream`,
        {
          signal: options.signal,
          query: { after: options.after, timeout: options.timeout ?? 900 },
          stream: true,
        },
      );
      if (!response.body)
        throw new ApiError('浏览器不支持流式响应', { code: 'stream_unavailable' });
      const reader = response.body.getReader(),
        decoder = new TextDecoder();
      let buffer = '';
      function parse(block) {
        let event = 'message';
        const lines = [];
        for (const line of block.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim();
          else if (line.startsWith('data:')) lines.push(line.slice(5).trimStart());
        }
        if (!lines.length) return null;
        const raw = lines.join('\n');
        try {
          return { event, data: JSON.parse(raw) };
        } catch {
          throw new ApiError('任务事件格式无效', { code: 'invalid_event' });
        }
      }
      try {
        while (true) {
          abortIfNeeded(options.signal);
          const { done, value } = await reader.read();
          buffer += decoder.decode(value, { stream: !done });
          // 只在完整读到 CRLF 后归一化，兼容分块恰好切在 CR 与 LF 之间。
          buffer = buffer.replace(/\r\n/g, '\n');
          let end;
          while ((end = buffer.indexOf('\n\n')) >= 0) {
            const result = parse(buffer.slice(0, end));
            buffer = buffer.slice(end + 2);
            if (result) {
              yield result;
              if (['end', 'timeout'].includes(result.event)) return;
            }
          }
          if (done) break;
        }
      } finally {
        // 清理失败不覆盖原始的取消或解析错误。
        try {
          await reader.cancel();
        } catch {
          /* 已被取消或出错的流无需再次取消。 */
        }
        reader.releaseLock();
      }
    },
  };
  return api;
}

export const studioApi = createStudioApi();
export default studioApi;
