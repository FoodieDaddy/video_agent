/** 剧本编辑器的纯状态规则：不访问 DOM、不请求接口、不保存供应商凭据。 */
export const SCRIPT_FIELDS = Object.freeze(['title', 'logline', 'synopsis', 'script_text']);
export const SCRIPT_IMPORT_LIMIT = 2 * 1024 * 1024;

export function scriptFields(value = {}, fallbackTitle = '') {
  return Object.fromEntries(
    SCRIPT_FIELDS.map((field) => [
      field,
      typeof value?.[field] === 'string' ? value[field] : field === 'title' ? fallbackTitle : '',
    ]),
  );
}

export function sameScriptFields(left, right) {
  return SCRIPT_FIELDS.every((field) => (left?.[field] ?? '') === (right?.[field] ?? ''));
}

/** 模式、后端、身份、项目隔离，避免切换环境后误用另一份草稿。 */
export function scriptDraftKey(connection, projectId) {
  return `studio.scriptDraft.v1.${encodeURIComponent(
    JSON.stringify([
      connection.mode,
      connection.baseUrl,
      connection.userId,
      connection.userRole,
      projectId,
    ]),
  )}`;
}

export function createScriptDraft(script, fallbackTitle = '') {
  const values = scriptFields(script, fallbackTitle);
  return {
    ...values,
    baseline: { ...values },
    base_script_id: script?.id ?? null,
    dirty: false,
    restored: false,
    conflict: false,
    saving: false,
    error: '',
    persisted: false,
  };
}

export function updateScriptDraft(draft, field, value) {
  if (!SCRIPT_FIELDS.includes(field)) return draft;
  draft[field] = String(value);
  draft.dirty = !sameScriptFields(draft, draft.baseline);
  draft.error = '';
  return draft;
}

/** 自动更新干净编辑器；发现服务端新版本时保留正在编辑的正文并标记冲突。 */
export function reconcileScriptDraft(draft, script, fallbackTitle = '') {
  if (!draft || (!draft.dirty && !draft.saving)) return createScriptDraft(script, fallbackTitle);
  draft.conflict = draft.base_script_id !== (script?.id ?? null);
  return draft;
}

/** 成功保存后，只清除本次已提交内容；请求期间新输入的文字仍保留为草稿。 */
export function acceptSavedScript(draft, submitted, saved) {
  if (sameScriptFields(draft, submitted)) return createScriptDraft(saved);
  draft.baseline = scriptFields(saved);
  draft.base_script_id = saved.id;
  draft.saving = false;
  draft.conflict = false;
  draft.error = '';
  draft.dirty = !sameScriptFields(draft, draft.baseline);
  return draft;
}

export function persistScriptDraft(storage, key, draft) {
  try {
    if (!draft.dirty) {
      storage?.removeItem(key);
      draft.persisted = false;
      return true;
    }
    if (!storage) {
      draft.persisted = false;
      return false;
    }
    storage.setItem(
      key,
      JSON.stringify({
        fields: scriptFields(draft),
        baseline: draft.baseline,
        base_script_id: draft.base_script_id,
        updated_at: new Date().toISOString(),
      }),
    );
    draft.persisted = true;
    return true;
  } catch {
    draft.persisted = false;
    return false;
  }
}

export function readScriptDraft(storage, key, script, fallbackTitle = '') {
  const initial = createScriptDraft(script, fallbackTitle);
  try {
    const raw = storage?.getItem(key);
    if (!raw) return initial;
    const stored = JSON.parse(raw);
    if (
      !stored.fields ||
      SCRIPT_FIELDS.some((field) => typeof stored.fields[field] !== 'string') ||
      !(stored.base_script_id === null || typeof stored.base_script_id === 'string')
    )
      return initial;
    Object.assign(initial, scriptFields(stored.fields), {
      baseline: scriptFields(stored.baseline ?? script, fallbackTitle),
      base_script_id: stored.base_script_id,
      restored: true,
      persisted: true,
    });
    initial.dirty = !sameScriptFields(initial, initial.baseline);
    initial.conflict = initial.base_script_id !== (script?.id ?? null);
    return initial.dirty ? initial : createScriptDraft(script, fallbackTitle);
  } catch {
    return initial;
  }
}

export function scriptSourceName(value) {
  return (
    {
      manual: '手动编辑',
      import: '文件导入',
      polish: 'AI 润色',
      continue: 'AI 续写',
      restore: '历史恢复',
      script: '小说解析',
    }[value] ||
    value ||
    '已有剧本'
  );
}

/** 正文和工作区元信息不混进结构化解析预览，防止把两份正文误认为不同稿件。 */
export function scriptStructure(script) {
  return Object.fromEntries(
    Object.entries(script?.content || {}).filter(
      ([key]) => !['script_text', 'workspace_meta'].includes(key),
    ),
  );
}

/** AI 按钮与文案共用同一状态判定，输入还原、保存和任务刷新不会彼此分叉。 */
export function scriptAssistState({
  script,
  draft,
  tasks = [],
  submitting = false,
  isDemo = false,
}) {
  const busy =
    submitting ||
    tasks.some(
      (task) =>
        task.type === 'script_assist' &&
        !['succeeded', 'failed', 'cancelled'].includes(task.status),
    );
  const missing = !script || !String(script.script_text || '').trim();
  const blocked = !!(missing || draft?.dirty || draft?.saving || busy);
  const message = draft?.saving
    ? '正文正在保存，完成后即可使用 AI 辅助。'
    : busy
      ? 'AI 任务正在处理中，可在下方查看状态。'
      : draft?.dirty
        ? '请先保存正文，再基于新版本发起 AI 辅助。'
        : missing
          ? '保存第一版完整正文后，即可使用 AI 辅助。'
          : isDemo
            ? '模拟操作不会调用模型或编造 AI 结果。'
            : `将基于 V${script.version} 发起，确认后可能产生模型费用。`;
  return { busy, blocked, message };
}

/** 保存按钮、表单和快捷键共享变更判断；相同内容的版本创建仍由 API 独立支持。 */
export function scriptSaveState({ script, draft }) {
  const saving = !!draft?.saving;
  const unchanged = !!script && !draft?.dirty;
  const valid = !!draft?.title.trim() && !!draft?.script_text.trim();
  return {
    saving,
    unchanged,
    disabled: saving || unchanged || !valid || !!draft?.conflict,
    label: saving
      ? '正在保存…'
      : draft?.conflict
        ? '版本冲突'
        : unchanged
          ? '已保存'
          : draft?.error
            ? '重试保存'
            : script
              ? '保存为新版本'
              : '保存第一版',
    message: saving
      ? '正在保存版本'
      : draft?.conflict
        ? '版本冲突，草稿已保留，请先核对最新版本'
        : draft?.error
          ? '保存未完成，正文已保留'
          : draft?.dirty
            ? draft.persisted
              ? script
                ? `V${script.version} 已保存 · 当前修改待保存`
                : '草稿已保留在当前浏览器标签页'
              : '尚未保存，请保留当前页面'
            : script
              ? `已保存为 V${script.version}`
              : '还没有已保存的版本',
  };
}

export function isScriptSaveShortcut(event, { view, tab, dialogOpen, hasEditor }) {
  return !!(
    (event.metaKey || event.ctrlKey) &&
    !event.altKey &&
    !event.isComposing &&
    event.key?.toLowerCase() === 's' &&
    view === 'workbench' &&
    tab === 'story' &&
    !dialogOpen &&
    hasEditor
  );
}
