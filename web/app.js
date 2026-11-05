/**
 * 片场 Studio 页面控制器。数据通过 api.js 接入 /api/v1，展示函数在 views.js。
 * 默认读取真实项目；只有显式选择 demo 才使用示例。生成由用户明确提交，不在启动时执行。
 */
import { createStudioApi } from './api.js';
import { icon } from './icons.js';
import { captureFocusTarget, resolveFocusTarget, mayRestoreDialogFocus } from './focus-return.js';
import { searchMatches, searchKeyboardAction, searchPopupOffset } from './search-controller.js';
import { PROJECT_SORTS } from './project-library.js';
import { assetPresentation, assetPreviewPosition } from './asset-library.js';
import { directingFormState } from './directing-state.js';
import { storyboardFormState, storyboardReviewState } from './storyboard-state.js';
import {
  SCRIPT_FIELDS,
  scriptFields,
  scriptDraftKey,
  createScriptDraft,
  updateScriptDraft,
  reconcileScriptDraft,
  acceptSavedScript,
  persistScriptDraft,
  readScriptDraft,
  scriptSourceName,
  scriptStructure,
  scriptAssistState,
  scriptSaveState,
  isScriptSaveShortcut,
} from './script-editor.js';
import {
  NAV,
  TABS,
  h,
  img,
  mediaUrl,
  action,
  heading,
  empty,
  status,
  statusName,
  stageTitle,
  overview,
  directingPlanBody,
  storyboardVersionBody,
  storyboardShotDetails,
  storyPreviewContent,
  projectsView,
  agentsView,
  assetsView,
  reviewsView,
  workbench,
  settingsView,
} from './views.js';

const $ = (id) => document.getElementById(id);
// 默认模式由适配层统一解析，页面与独立 API 调用不会采用两套默认值。
const api = createStudioApi();
const state = {
  api,
  connection: api.getConnection(),
  projects: [],
  agents: [],
  workspace: null,
  projectId: '',
  view: 'overview',
  tab: 'story',
  filter: 'all',
  query: '',
  projectSort: 'updated',
  agentFilter: 'all',
  assetFilter: 'all',
  assetQuery: '',
  assetSort: 'default',
  reviewFilter: 'all',
  controller: null,
  generation: 0,
  error: null,
  poll: null,
  scriptDrafts: {},
  scriptAssistDrafts: {},
  scriptDraft: null,
  scriptAssist: null,
  scriptTaskSubmitting: false,
  directingDrafts: {},
  directingDraft: null,
  storyboardDrafts: {},
  storyboardDraft: null,
  scriptFocus: false,
  scriptFocusKey: '',
};
let scriptReturnScroll = 0;
const terminal = new Set(['succeeded', 'failed', 'cancelled']);
let dialogHandler = null;
let dialogReturnFocus = null;
let dialogActionOrigin = null;
let dialogInteraction = 0;
let dialogSession = 0;
const dialogClosures = [];
// 已在当前上下文持久显示的错误，不再重复生成遮挡正文的全局通知。
const contextualErrors = new WeakSet();
let globalSearchItems = [];
let globalSearchIndex = -1;
let projectSearchComposing = false;
let assetSearchComposing = false;
let libraryReturn = null;
let assetReturn = null;

function positionSearchResults() {
  const box = $('search-results');
  if (box.hidden) return;
  // 先还原上次偏移再测量，避免重复打开或 resize 时累计平移。
  box.style.transform = '';
  const offset = searchPopupOffset(box.getBoundingClientRect(), window.innerWidth);
  if (offset) box.style.transform = `translateX(${offset}px)`;
}

function closeSearch() {
  $('search-results').hidden = true;
  $('global-search').setAttribute('aria-expanded', 'false');
  $('global-search').removeAttribute('aria-activedescendant');
  globalSearchIndex = -1;
  for (const option of $('search-results').querySelectorAll('[role="option"]')) {
    option.classList.remove('is-active');
    option.setAttribute('aria-selected', 'false');
  }
}

function selectSearchResult(index) {
  const options = [...$('search-results').querySelectorAll('button[role="option"]')];
  globalSearchIndex = index;
  for (const [position, option] of options.entries()) {
    const active = position === index;
    option.classList.toggle('is-active', active);
    option.setAttribute('aria-selected', String(active));
  }
  const active = options[index];
  if (active) {
    $('global-search').setAttribute('aria-activedescendant', active.id);
    active.scrollIntoView({ block: 'nearest' });
  } else $('global-search').removeAttribute('aria-activedescendant');
}

function renderSearchResults() {
  const input = $('global-search');
  if (!input.value.trim()) {
    globalSearchItems = [];
    closeSearch();
    return;
  }
  globalSearchItems = searchMatches(input.value, state.projects, NAV);
  $('search-results').innerHTML =
    globalSearchItems
      .map(
        (item, index) =>
          `<button type="button" class="search-result" id="search-option-${index}" role="option" aria-selected="false" tabindex="-1" data-search-kind="${item.kind}" data-action="${item.kind === 'project' ? 'open-project' : 'navigate'}" ${item.kind === 'project' ? 'data-id' : 'data-view'}="${h(item.id)}">${icon(item.icon)}<span>${h(item.label)}</span><small>${item.kind === 'project' ? '项目' : '功能'}</small></button>`,
      )
      .join('') ||
    '<div class="search-result search-empty" role="option" aria-disabled="true" aria-selected="false">没有找到相关项目或功能。</div>';
  $('search-results').hidden = false;
  input.setAttribute('aria-expanded', 'true');
  positionSearchResults();
  selectSearchResult(-1);
}

function toast(message, error = false) {
  const node = document.createElement('div');
  node.className = `toast${error ? ' error' : ''}`;
  node.innerHTML = icon(error ? 'info' : 'check') + `<span>${h(message)}</span>`;
  $('toast-stack').append(node);
  setTimeout(
    () => {
      node.classList.add('removing');
      setTimeout(() => node.remove(), 250);
    },
    error ? 6500 : 3600,
  );
}
function showError(error) {
  if (error?.name !== 'AbortError' && !contextualErrors.has(error))
    toast(error.message || '操作未完成，请重试。', true);
}
function closeMenu(restoreFocus = false) {
  const wasOpen = $('sidebar').classList.contains('open');
  $('sidebar').classList.remove('open');
  $('sidebar-scrim').hidden = true;
  $('menu-toggle').setAttribute('aria-expanded', 'false');
  if (restoreFocus && wasOpen) $('menu-toggle').focus();
}
function navigate(view) {
  closeMenu();
  if (location.hash === `#${view}`) route();
  else location.hash = view;
}
function projectRoute(id, tab = 'story') {
  const target = `project/${encodeURIComponent(id)}/${tab}`;
  if (location.hash === `#${target}`) route();
  else location.hash = target;
  closeMenu();
}
function renderNav() {
  const current = state.view === 'workbench' ? 'projects' : state.view;
  $('primary-nav').innerHTML = NAV.map(
    ([id, label, symbol], i) =>
      `${i === 5 ? '<div class="nav-divider"></div>' : ''}<button class="nav-button ${current === id ? 'active' : ''}" data-action="navigate" data-view="${id}" ${current === id ? 'aria-current="page"' : ''}>${icon(symbol)}<span>${label}</span>${id === 'projects' ? `<span class="nav-number">${state.projects.length}</span>` : id === 'reviews' && state.workspace?.pending_reviews?.length ? `<span class="nav-number">${state.workspace.pending_reviews.length}</span>` : ''}</button>`,
  ).join('');
  $('breadcrumb-current').textContent =
    state.view === 'workbench'
      ? state.workspace?.project.name || '项目制作'
      : NAV.find((n) => n[0] === state.view)?.[1] || '创作概览';
  $('mode-pill').classList.toggle('live', !state.api.isDemo);
  $('mode-pill').innerHTML =
    `<span class="status-dot"></span><span>${state.api.isDemo ? '示例空间' : state.error ? '连接待检查' : '真实项目'}</span>`;
  $('footer-mode').textContent = state.api.isDemo
    ? 'DEMO · 示例内容，仅用于界面预览'
    : 'LIVE · 当前内容来自已连接后端';
}
function scriptStorage() {
  try {
    return sessionStorage;
  } catch {
    return null;
  }
}
function currentScriptKey(projectId = state.workspace?.project.id) {
  return scriptDraftKey(state.api.getConnection(), projectId);
}
function prepareScriptEditor() {
  if (!state.workspace) {
    state.scriptDraft = null;
    state.scriptAssist = null;
    return;
  }
  const key = currentScriptKey(),
    w = state.workspace;
  const existing =
    state.scriptDrafts[key] || readScriptDraft(scriptStorage(), key, w.script, w.project.name);
  state.scriptDrafts[key] = reconcileScriptDraft(existing, w.script, w.project.name);
  state.scriptDraft = state.scriptDrafts[key];
  state.scriptAssist = state.scriptAssistDrafts[key] ??= {
    operation: 'polish',
    instruction: '',
    error: '',
  };
}
function rememberScriptDraft(key = currentScriptKey(), draft = state.scriptDrafts[key]) {
  if (draft) persistScriptDraft(scriptStorage(), key, draft);
}

/** 导演创作参数按连接、身份与项目隔离，任务轮询不能清空正在填写的要求。 */
function prepareDirectingDraft() {
  const w = state.workspace;
  if (!w) {
    state.directingDraft = null;
    return;
  }
  const key = currentScriptKey();
  const saved = w.directing?.content?.generation_request || {};
  const requested = Number(saved.shots_target ?? w.project.settings?.shots_target ?? 6);
  state.directingDraft = state.directingDrafts[key] ??= {
    instruction: saved.instruction || '',
    shots_target: Number.isInteger(requested) && requested >= 1 && requested <= 120 ? requested : 6,
    error: '',
    submitting: false,
  };
}

function updateDirectingControls() {
  const form = $('directing-form');
  if (!form) return;
  const view = directingFormState({
    workspace: state.workspace,
    draft: state.directingDraft,
    scriptDraft: state.scriptDraft,
    isDemo: state.api.isDemo,
  });
  const button = form.querySelector('[data-directing-submit]');
  if (button) {
    button.disabled = view.blocked;
    button.innerHTML = icon('spark') + h(view.label);
  }
  if ($('directing-form-state')) $('directing-form-state').textContent = view.message;
}

function prepareStoryboardDraft() {
  state.storyboardDraft = state.workspace
    ? (state.storyboardDrafts[currentScriptKey()] ??= {
        refine_prompts: false,
        error: '',
        submitting: false,
        reviewError: '',
        reviewSubmitting: false,
      })
    : null;
}

function updateStoryboardControls() {
  const form = $('storyboard-form');
  if (!form) return;
  const view = storyboardFormState({
    workspace: state.workspace,
    draft: state.storyboardDraft,
    scriptDraft: state.scriptDraft,
    isDemo: state.api.isDemo,
  });
  const button = form.querySelector('[data-storyboard-submit]');
  if (button) {
    button.disabled = view.blocked;
    button.innerHTML = icon('spark') + h(view.label);
  }
  if ($('storyboard-form-state')) $('storyboard-form-state').textContent = view.message;
}

/** 接受任务后先显示已排队状态，读取刷新失败不能被误报为模型生成失败。 */
function acknowledgePlanningTask(projectId, key, type, result) {
  if (state.workspace?.project.id !== projectId || currentScriptKey() !== key) return;
  const task = result.task || {
    id: result.task_id,
    type,
    status: result.status || 'pending',
    message: '任务已提交',
  };
  if (task.id)
    state.workspace.tasks = [
      task,
      ...(state.workspace.tasks || []).filter((item) => item.id !== task.id),
    ];
  schedulePoll();
}
function updateScriptControls() {
  if (!state.workspace || !state.scriptDraft) return;
  const draft = state.scriptDraft;
  const ai = scriptAssistState({
    script: state.workspace.script,
    draft,
    tasks: state.workspace.tasks,
    submitting: state.scriptTaskSubmitting,
    isDemo: state.api.isDemo,
  });
  const save = scriptSaveState({ script: state.workspace.script, draft });
  if ($('script-char-count'))
    $('script-char-count').textContent = `${draft.script_text.length.toLocaleString()} 字符`;
  if ($('script-save-state')) $('script-save-state').textContent = save.message;
  for (const button of document.querySelectorAll('[data-script-save]')) {
    button.disabled = save.disabled;
    button.innerHTML = icon('check') + h(save.label);
  }
  const discard = document.querySelector('[data-action="discard-script-draft"]');
  if (discard) discard.disabled = !draft.dirty || draft.saving;
  const aiButton = document.querySelector('#script-assist-form [type="submit"]');
  if (aiButton) aiButton.disabled = ai.blocked;
  const aiMessage = document.querySelector('.script-ai-state');
  if (aiMessage) aiMessage.textContent = ai.message;
}

/** 同一份草稿切换为安静的写作布局，光标、正文滚动及返回位置不丢失。 */
function setScriptFocus(enabled) {
  const editor = $('script-text');
  if (!editor || $('studio-dialog').open) return;
  const selection = {
    start: editor.selectionStart,
    end: editor.selectionEnd,
    direction: editor.selectionDirection,
    scroll: editor.scrollTop,
  };
  if (enabled) scriptReturnScroll = window.scrollY;
  state.scriptFocus = enabled;
  state.scriptFocusKey = enabled ? currentScriptKey() : '';
  closeMenu();
  render();
  const next = $('script-text');
  next.focus({ preventScroll: true });
  next.setSelectionRange(selection.start, selection.end, selection.direction);
  next.scrollTop = selection.scroll;
  window.scrollTo({ top: enabled ? 0 : scriptReturnScroll, behavior: 'instant' });
}

function focusScriptPanel(panelId) {
  if (!['script-assistant', 'script-history'].includes(panelId)) return;
  const panel = $(panelId);
  const heading = panel?.querySelector('h2');
  heading?.focus({ preventScroll: true });
  panel?.scrollIntoView({ behavior: 'auto', block: 'start' });
}

function focusProductionPanel(panelId) {
  if (
    ![
      'directing-brief',
      'directing-history',
      'directing-plan',
      'storyboard-brief',
      'storyboard-review',
      'storyboard-history',
      'storyboard-overview',
    ].includes(panelId)
  )
    return;
  const panel = $(panelId),
    heading = panel?.querySelector('h2,h3');
  if (heading) {
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
  }
  panel?.scrollIntoView({ behavior: 'auto', block: 'start' });
}

/** 项目与素材列表共用焦点保留规则，筛选、排序和搜索光标留在原操作处。 */
function renderLibraryControl(source) {
  const target = captureFocusTarget(source);
  const scope = JSON.stringify(state.api.getConnection());
  const selection = Number.isInteger(source?.selectionStart)
    ? {
        start: source.selectionStart,
        end: source.selectionEnd,
        direction: source.selectionDirection,
        scrollLeft: source.scrollLeft,
      }
    : null;
  render();
  const next =
    resolveFocusTarget(target, {
      originalScope: scope,
      scope: JSON.stringify(state.api.getConnection()),
      candidates: document.querySelectorAll(
        '.library-toolbar button, .library-toolbar input, .library-toolbar select, [data-action="clear-project-filters"], [data-action="clear-asset-filters"]',
      ),
    }) ||
    $('project-filter') ||
    $('asset-query');
  next?.focus({ preventScroll: true });
  if (next && selection) {
    try {
      next.setSelectionRange(selection.start, selection.end, selection.direction || 'none');
      next.scrollLeft = selection.scrollLeft;
    } catch {
      /* 只有搜索文本字段需要选区，其他控件保留焦点即可。 */
    }
  }
}

function restoreLibraryPosition() {
  const snapshot = libraryReturn;
  if (!snapshot || snapshot.connection !== JSON.stringify(state.api.getConnection())) return;
  requestAnimationFrame(() => {
    if (state.view !== 'projects' || libraryReturn !== snapshot) return;
    const card = [...document.querySelectorAll('.library-grid .project-card')].find(
      (item) => item.dataset.id === snapshot.projectId,
    );
    window.scrollTo({ top: snapshot.scrollY, behavior: 'instant' });
    (card || $('library-results-status'))?.focus({ preventScroll: true });
    libraryReturn = null;
  });
}

/** 从素材上下文进入项目后，返回时回到同一项目、同一入口和列表位置。 */
function restoreAssetPosition() {
  const snapshot = assetReturn;
  if (!snapshot) return;
  const scope = JSON.stringify([state.api.getConnection(), state.workspace?.project.id]);
  if (snapshot.scope !== scope) {
    assetReturn = null;
    return;
  }
  requestAnimationFrame(() => {
    if (state.view !== 'assets' || assetReturn !== snapshot) return;
    const target = resolveFocusTarget(snapshot.target, {
      originalScope: snapshot.scope,
      scope: JSON.stringify([state.api.getConnection(), state.workspace?.project.id]),
      candidates: document.querySelectorAll('#main-content button'),
    });
    window.scrollTo({ top: snapshot.scrollY, behavior: 'instant' });
    target?.focus({ preventScroll: true });
    assetReturn = null;
  });
}

function render() {
  // 输入法候选期间不能替换原生输入节点，结束后再统一过滤和重绘。
  if (state.view === 'projects' && projectSearchComposing && $('project-filter')) return;
  if (state.view === 'assets' && assetSearchComposing && $('asset-query')) return;
  prepareScriptEditor();
  prepareDirectingDraft();
  prepareStoryboardDraft();
  // 专注布局仅属于当前连接和项目的剧本页，切换路由不能遗留隐藏的全局导航。
  if (
    state.view !== 'workbench' ||
    state.tab !== 'story' ||
    state.scriptFocusKey !== currentScriptKey()
  ) {
    state.scriptFocus = false;
    state.scriptFocusKey = '';
  }
  document.body.classList.toggle('script-focus', state.scriptFocus);
  const focused = document.activeElement;
  const metadataOpen = document.querySelector('#script-editor-form .script-metadata')?.open;
  const editorFocus =
    (focused?.closest(
      '#script-editor-form, #script-assist-form, #directing-form, #storyboard-form',
    ) &&
      [...SCRIPT_FIELDS, 'instruction', 'operation', 'shots_target', 'refine_prompts'].includes(
        focused.name,
      )) ||
    ['directing-form-state', 'storyboard-form-state'].includes(focused?.id)
      ? {
          id: focused.id,
          start: focused.selectionStart,
          end: focused.selectionEnd,
          scroll: focused.scrollTop,
        }
      : null;
  renderNav();
  if (state.error) {
    $('main-content').innerHTML =
      heading(
        '片场暂时没有连接。',
        '请检查接口地址与服务状态，再重新加载。',
        'CONNECTION REQUIRED',
      ) +
      `<div class="empty-state error-state">${icon('link')}<h3>数据加载未完成</h3><p>${h(state.error.message)}</p>${action('refresh', '重新加载', 'refresh', 'primary')}${action('navigate', '检查连接', 'settings', '', 'data-view="settings"')}${action('switch-demo', '进入示例空间', 'arrow')}</div>`;
    if (state.view === 'settings') $('main-content').innerHTML = settingsView(state);
    return;
  }
  const views = {
    overview,
    projects: projectsView,
    assets: assetsView,
    agents: agentsView,
    reviews: reviewsView,
    settings: settingsView,
    workbench,
  };
  $('main-content').innerHTML = (views[state.view] || overview)(state);
  const metadata = document.querySelector('#script-editor-form .script-metadata');
  if (metadata && metadataOpen) metadata.open = true;
  if (editorFocus) {
    const next = $(editorFocus.id);
    if (next) {
      next.focus({ preventScroll: true });
      try {
        next.setSelectionRange(editorFocus.start, editorFocus.end);
      } catch {
        /* 文本字段类型可能不支持选区。 */
      }
      next.scrollTop = editorFocus.scroll;
    }
  }
}
function schedulePoll() {
  clearTimeout(state.poll);
  if (
    !state.api.isDemo &&
    !document.hidden &&
    state.workspace?.tasks?.some((t) => !terminal.has(t.status))
  ) {
    state.poll = setTimeout(async () => {
      try {
        await loadWorkspace(state.projectId);
        render();
      } catch (e) {
        showError(e);
      }
    }, 3500);
  }
}
async function loadWorkspace(id) {
  clearTimeout(state.poll);
  if (!id) {
    state.controller?.abort();
    state.generation++;
    state.workspace = null;
    return;
  }
  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  const generation = ++state.generation;
  const [w, versions] = await Promise.all([
    state.api.getWorkspace(id, { signal: controller.signal }),
    state.api.getScripts(id, { signal: controller.signal }),
  ]);
  w.scriptVersions = versions;
  if (generation !== state.generation) return;
  state.workspace = w;
  state.projectId = id;
  state.error = null;
  try {
    localStorage.setItem(`studio.project.${state.api.mode}`, id);
  } catch {
    /* 私密窗口不保证允许持久化。 */
  }
  schedulePoll();
}
async function refresh() {
  const [projects, agents] = await Promise.all([
    state.api.getProjects(),
    state.api.getAgentCatalog(),
  ]);
  state.projects = projects;
  state.agents = agents;
  if (!projects.some((p) => p.id === state.projectId)) state.projectId = projects[0]?.id || '';
  await loadWorkspace(state.projectId);
  state.error = null;
  render();
}
async function route() {
  // 选择搜索结果及浏览器前进/后退都走同一关闭规则，浮层不能留在新页面上。
  closeSearch();
  projectSearchComposing = false;
  assetSearchComposing = false;
  const hash = location.hash.slice(1) || 'overview';
  const [view, id, tab] = hash.split('/');
  const enteringFromLibrary = state.view === 'projects' && view === 'project' && !!libraryReturn;
  const enteringFromAssets = state.view === 'assets' && view === 'project' && !!assetReturn;
  if (view === 'project' && id) {
    state.view = 'workbench';
    state.tab = TABS.some((t) => t[0] === tab) ? tab : 'story';
    const projectId = decodeURIComponent(id);
    if (projectId !== state.workspace?.project.id) {
      $('main-content').innerHTML =
        '<div class="initial-loader"><span class="loader-ring"></span><p>正在准备项目工作台…</p></div>';
      try {
        await loadWorkspace(projectId);
      } catch (e) {
        if (e.name === 'AbortError') return;
        state.error = e;
      }
    }
  } else state.view = NAV.some((n) => n[0] === view) ? view : 'overview';
  render();
  if (state.view === 'projects') restoreLibraryPosition();
  else if (state.view === 'assets') restoreAssetPosition();
  else if (enteringFromLibrary || enteringFromAssets) {
    // 列表可能滚动很深；进入项目先呈现项目页首，返回时再恢复列表位置。
    window.scrollTo({ top: 0, behavior: 'instant' });
    $('main-content').focus({ preventScroll: true });
  }
}

function dialogFocusScope() {
  // 同名按钮可能出现在另一个项目；返回焦点不能跨连接、项目或路由寻找。
  return JSON.stringify([
    state.api.getConnection(),
    state.projectId,
    state.view,
    state.tab,
    location.hash,
  ]);
}
function captureDialogOrigin(trigger = document.activeElement) {
  const dialog = $('studio-dialog');
  return {
    interaction: dialogInteraction,
    scope: dialogFocusScope(),
    target:
      dialog.open && dialog.contains(trigger)
        ? dialogReturnFocus?.target || null
        : captureFocusTarget(trigger),
  };
}

/** 所有关闭入口共用一次生命周期；排队记录对应各自的原生 close 事件。 */
function closeStudioDialog({ restoreFocus = true } = {}) {
  const dialog = $('studio-dialog');
  if (!dialog.open) return;
  dialogClosures.push({
    session: dialogSession,
    interaction: ++dialogInteraction,
    origin: dialogReturnFocus,
    restoreFocus,
  });
  dialogHandler = null;
  dialogReturnFocus = null;
  dialog.close();
}

/** 原生 dialog 自带焦点约束；返回目标在触发按钮被禁用之前捕获。 */
function openDialog(
  title,
  content,
  {
    label = 'STUDIO / CREATIVE SPACE',
    onSubmit = null,
    wide = false,
    origin = dialogActionOrigin || captureDialogOrigin(),
  } = {},
) {
  // 历史稿等需要先异步读取，旧请求不能覆盖后来打开的弹窗或切换后的项目。
  if (origin.interaction !== dialogInteraction || origin.scope !== dialogFocusScope()) return;
  dialogInteraction++;
  const dialog = $('studio-dialog');
  if (dialog.open) closeStudioDialog({ restoreFocus: false });
  dialogSession++;
  dialogReturnFocus = origin;
  dialogHandler = onSubmit;
  dialog.style.maxWidth = wide ? 'min(800px, calc(100vw - 32px))' : '';
  $('dialog-content').innerHTML =
    `<div class="dialog-header"><div><div class="eyebrow">${h(label)}</div><h2 id="dialog-title">${h(title)}</h2></div><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭弹窗">${icon('close')}</button></div><div class="dialog-body">${content}</div>`;
  dialog.showModal();
}
function closeOwnDialog(form) {
  if (form?.isConnected && $('studio-dialog').contains(form)) closeStudioDialog();
}
function showDialogFormError(form, error) {
  const dialog = $('studio-dialog');
  if (error?.name !== 'AbortError' && form?.isConnected && dialog.open && dialog.contains(form)) {
    let message = form.querySelector('.dialog-form-error');
    if (!message) {
      message = document.createElement('div');
      message.className = 'dialog-form-error';
      message.setAttribute('role', 'alert');
      message.tabIndex = -1;
      form.prepend(message);
    }
    message.textContent = error?.message || '操作未完成，请修改后重试。';
    message.focus({ preventScroll: true });
    message.scrollIntoView({ block: 'nearest' });
    if (error && typeof error === 'object') contextualErrors.add(error);
  }
  showError(error);
}

const dialogFooter = (text = '保存修改', classes = 'primary') =>
  `<div class="dialog-footer">${action('close-dialog', '取消')}<button type="submit" class="button ${classes}">${h(text)}${icon('arrow')}</button></div>`;
/** 保存后的读回失败不冒充写入失败；编辑期间新输入的内容仍保留。 */
async function refreshScriptProject(projectId, key, saved) {
  if (state.workspace?.project.id !== projectId || currentScriptKey() !== key) return;
  if (saved) {
    state.workspace.script = saved;
    state.workspace.scriptVersions = [
      saved,
      ...(state.workspace.scriptVersions || []).filter((item) => item.id !== saved.id),
    ];
  }
  render();
  try {
    await loadWorkspace(projectId);
    render();
  } catch (error) {
    if (error.name !== 'AbortError') toast(`操作已完成，但内容刷新失败：${error.message}`, true);
  }
}

async function saveScriptDraft({ baseScriptId } = {}) {
  const projectId = state.workspace?.project.id;
  if (!projectId) return;
  const key = currentScriptKey(),
    draft = state.scriptDrafts[key];
  if (!draft || draft.saving) return;
  if (draft.conflict && baseScriptId === undefined) {
    const conflict = document.querySelector('[data-script-conflict]');
    conflict?.focus();
    conflict?.scrollIntoView({ block: 'nearest' });
    return;
  }
  if (
    scriptSaveState({ script: state.workspace.script, draft }).unchanged &&
    baseScriptId === undefined
  ) {
    const savedState = $('script-save-state');
    if (savedState)
      savedState.textContent = `已保存为 V${state.workspace.script.version} · 当前无修改`;
    return;
  }
  const submitted = scriptFields(draft);
  if (!submitted.title.trim() || !submitted.script_text.trim())
    throw new Error('请填写剧本标题和正文。');
  draft.saving = true;
  draft.error = '';
  render();
  let saved;
  try {
    saved = await state.api.createScript(projectId, {
      ...submitted,
      base_script_id: baseScriptId ?? draft.base_script_id,
    });
    state.scriptDrafts[key] = acceptSavedScript(draft, submitted, saved);
    rememberScriptDraft(key, state.scriptDrafts[key]);
  } catch (error) {
    draft.saving = false;
    draft.error =
      error.status === 409
        ? '服务端已有新版本，当前草稿已保留。请查看最新版本，再核对另存。'
        : error.message;
    if (error.status === 409) {
      draft.conflict = true;
      if (currentScriptKey() === key) {
        try {
          await loadWorkspace(projectId);
        } catch {
          /* 保留最初的冲突提示和草稿。 */
        }
      }
    }
    rememberScriptDraft(key, draft);
    if (currentScriptKey() === key) {
      render();
      const notice = document.querySelector('[data-script-conflict], [data-script-error]');
      notice?.focus();
      notice?.scrollIntoView({ block: 'nearest' });
      if (notice && error && typeof error === 'object') contextualErrors.add(error);
    }
    throw error;
  }
  await refreshScriptProject(projectId, key, saved);
  // 普通保存由吸底区持久反馈；不重复弹toast遮挡正在编辑的正文。
  return saved;
}

function requireCleanScriptDraft() {
  if (state.scriptDraft?.saving) throw new Error('剧本正在保存，请等待完成后再操作。');
  if (state.scriptDraft?.dirty)
    throw new Error('请先保存或放弃当前草稿，再执行这个操作。正文会继续保留在编辑器中。');
}

function importScriptDialog() {
  requireCleanScriptDraft();
  const w = state.workspace,
    key = currentScriptKey();
  if (!w) return;
  openDialog(
    '导入已有剧本',
    `<p>导入正文并创建新版本，不走小说解析，也不会调用模型。</p><form id="dialog-form"><div class="form-field"><label for="script-import-file">选择剧本文件</label><input id="script-import-file" name="file" type="file" accept=".txt,.md,.json,.docx" required><p class="script-import-help">TXT、Markdown、JSON 或 DOCX，最大 2 MiB。JSON 使用 title、logline、synopsis、script_text 字段。${state.api.isDemo ? '演示模式可读 TXT、MD、JSON；DOCX 仅由真实后端解析。' : ''}</p></div><div class="inline-note">${icon('info')}已有版本保留；导入后请重新核对人物、场景和分镜。</div>${dialogFooter(state.api.isDemo ? '导入示例版本' : '导入为新版本')}</form>`,
    {
      label: '剧本导入',
      onSubmit: async (form) => {
        if (currentScriptKey() !== key) throw new Error('项目或连接已切换，请重新导入。');
        const saved = await state.api.importScript(w.project.id, form.elements.file.files[0], {
          base_script_id: w.script?.id ?? null,
        });
        state.scriptDrafts[key] = reconcileScriptDraft(state.scriptDrafts[key], saved);
        rememberScriptDraft(key, state.scriptDrafts[key]);
        closeOwnDialog(form);
        await refreshScriptProject(w.project.id, key, saved);
        toast(`已导入${state.api.isDemo ? '示例' : '剧本'} V${saved.version}，没有调用模型。`);
      },
    },
  );
}

async function scriptVersionDialog(scriptId, origin = captureDialogOrigin()) {
  const projectId = state.workspace?.project.id,
    key = currentScriptKey();
  const version = await state.api.getScriptVersion(scriptId);
  if (state.workspace?.project.id !== projectId || currentScriptKey() !== key) return;
  const baseId = state.workspace.script?.id ?? null;
  const isCurrent = version.id === baseId;
  const canRestore = !isCurrent && !state.scriptDraft?.dirty;
  openDialog(
    `剧本 V${version.version} · ${version.title}`,
    `<p>${h(scriptSourceName(version.workspace_meta?.source))} · ${isCurrent ? '当前已保存版本' : '历史版本，只读查看'}</p><p>${h(version.logline || '')}</p>${version.synopsis ? `<details class="script-metadata"><summary>故事梗概</summary><p>${h(version.synopsis)}</p></details>` : ''}<pre class="script-version-text">${h(version.script_text || '该历史版本尚无独立正文，可查看结构化数据。')}</pre><details class="script-metadata"><summary>结构化数据（只读）</summary><pre class="json-view">${h(JSON.stringify(scriptStructure(version), null, 2))}</pre></details>${!isCurrent && state.scriptDraft?.dirty ? '<div class="inline-note">当前有未保存草稿，请先保存或放弃，再恢复历史版本。</div>' : ''}${canRestore ? `<div class="inline-note">恢复会复制这版正文创建新版本，保留全部历史；后续人物、场景与分镜需要重新核对。</div><form id="dialog-form">${dialogFooter('恢复为新版本')}</form>` : `<div class="dialog-footer">${action('close-dialog', '关闭')}</div>`}`,
    {
      wide: true,
      label: '剧本版本',
      origin,
      onSubmit: canRestore
        ? async (form) => {
            if (currentScriptKey() !== key) throw new Error('项目或连接已切换，请重新查看版本。');
            requireCleanScriptDraft();
            const saved = await state.api.restoreScriptVersion(projectId, version.id, {
              base_script_id: baseId,
            });
            state.scriptDrafts[key] = reconcileScriptDraft(state.scriptDrafts[key], saved);
            rememberScriptDraft(key, state.scriptDrafts[key]);
            closeOwnDialog(form);
            await refreshScriptProject(projectId, key, saved);
            toast(`已将 V${version.version} 恢复为新版本 V${saved.version}。`);
          }
        : null,
    },
  );
}

function discardScriptDraftDialog() {
  const key = currentScriptKey();
  openDialog(
    '放弃当前草稿',
    `<p>已保存的历史版本会保留。本次尚未保存的正文修改将被移除。</p><form id="dialog-form">${dialogFooter('放弃草稿')}</form>`,
    {
      onSubmit: async (form) => {
        if (currentScriptKey() !== key) throw new Error('项目已切换，请重新确认。');
        state.scriptDrafts[key] = createScriptDraft(
          state.workspace.script,
          state.workspace.project.name,
        );
        rememberScriptDraft(key, state.scriptDrafts[key]);
        closeOwnDialog(form);
        render();
        // 确认放弃后原按钮会禁用，继续把焦点交给正文，方便马上重新写作。
        $('script-text')?.focus({ preventScroll: true });
      },
    },
  );
}

function rebaseScriptDraftDialog() {
  const w = state.workspace,
    key = currentScriptKey();
  if (!w?.script) return;
  openDialog(
    '核对后另存草稿',
    `<p>服务端当前为 V${h(w.script.version)}。下方是最新已保存正文，请先核对；确认后会把编辑器中的草稿另存为新版本，不自动合并两份正文。</p><pre class="script-version-text">${h(w.script.script_text || '当前版本暂无独立正文')}</pre><form id="dialog-form">${dialogFooter('确认另存我的草稿')}</form>`,
    {
      wide: true,
      onSubmit: async (form) => {
        if (currentScriptKey() !== key) throw new Error('项目已切换，请重新核对。');
        await saveScriptDraft({ baseScriptId: w.script.id });
        closeOwnDialog(form);
      },
    },
  );
}

function scriptAssistConfirmation(form) {
  requireCleanScriptDraft();
  const w = state.workspace,
    key = currentScriptKey();
  if (!w?.script) throw new Error('请先保存第一版剧本。');
  const operation = form.elements.operation.value,
    instruction = form.elements.instruction.value;
  const title = operation === 'continue' ? '续写剧本' : '润色剧本';
  state.scriptAssistDrafts[key] = { operation, instruction, error: '' };
  openDialog(
    `确认${title}`,
    `<p>项目：${h(w.project.name)} · 基于已保存 V${h(w.script.version)}</p><div class="dialog-quote">${operation === 'continue' ? '保留现有正文，再续写下一段。' : '在不丢失原版本的前提下，润色表达。'}</div><p>${state.api.isDemo ? '本次仅模拟提交：不会调用模型，也不会编造 AI 正文或创建 AI 结果版本。' : '将调用已配置的文字模型，可能产生费用。成功结果会另存为新版本；任务执行期间可以继续编辑，未保存内容会保留。'}</p>${instruction ? `<pre class="script-version-text">${h(instruction)}</pre>` : '<p class="settings-tip">未填写额外指令，将使用默认创作要求。</p>'}<form id="dialog-form">${dialogFooter(state.api.isDemo ? '确认模拟' : '确认调用模型')}</form>`,
    {
      label: state.api.isDemo ? 'DEMO · 模拟操作' : '真实 AI 任务',
      onSubmit: async (confirmationForm) => {
        if (currentScriptKey() !== key || state.workspace.script?.id !== w.script.id)
          throw new Error('项目或剧本版本已变化，请重新确认。');
        requireCleanScriptDraft();
        state.scriptTaskSubmitting = true;
        render();
        try {
          const result = await state.api.assistScript(
            w.project.id,
            { operation, instruction, base_script_id: w.script.id },
            { confirmed: true },
          );
          closeOwnDialog(confirmationForm);
          await refreshScriptProject(w.project.id, key);
          if (result.task?.status === 'failed')
            throw new Error(result.task.error || 'AI 任务未完成，请查看任务记录。');
          toast(
            state.api.isDemo
              ? '模拟操作已记录，没有调用模型或生成 AI 版本。'
              : 'AI 任务已提交，可在剧本侧栏查看状态与结果。',
          );
        } catch (error) {
          state.scriptAssistDrafts[key].error =
            error.status === 409 ? '剧本版本已变化，请刷新并核对最新正文后再发起。' : error.message;
          throw error;
        } finally {
          state.scriptTaskSubmitting = false;
          if (currentScriptKey() === key) render();
        }
      },
    },
  );
}

function uploadSourceDialog() {
  const w = state.workspace,
    key = currentScriptKey();
  if (!w) return;
  openDialog(
    '上传小说原文',
    `<p>此入口管理改编所需的小说章节。已有剧本请使用剧本编辑器的“导入剧本”。</p><form id="dialog-form"><div class="form-field"><label for="source-upload">小说文件</label><input id="source-upload" name="file" type="file" accept=".txt,.md,.docx" required></div>${dialogFooter('导入小说原文')}</form>`,
    {
      onSubmit: async (form) => {
        await state.api.uploadDocument(w.project.id, form.elements.file.files[0]);
        closeOwnDialog(form);
        await refreshScriptProject(w.project.id, key);
        toast('小说原文已导入；解析为剧本需要单独确认，不会自动调用模型。');
      },
    },
  );
}

function newProject() {
  openDialog(
    '下一个故事，叫什么？',
    `<p>先给灵感一个名字。人物、世界和镜头，稍后慢慢展开。</p><form id="dialog-form"><div class="form-field"><label for="new-project-name">项目名称</label><input id="new-project-name" name="name" placeholder="例如：雨夜书店" maxlength="120" required autofocus></div><div class="form-grid"><div class="form-field"><label for="new-project-genre">故事类型</label><select id="new-project-genre" name="genre"><option>剧情 / 文艺</option><option>悬疑 / 推理</option><option>科幻 / 奇幻</option><option>纪录 / 纪实</option><option>其他</option></select></div><div class="form-field"><label for="new-project-ratio">画面比例</label><select id="new-project-ratio" name="aspect_ratio"><option value="16:9">16:9 宽银幕</option><option value="9:16">9:16 竖屏</option><option value="1:1">1:1 方形</option></select></div></div><div class="form-field"><label for="new-project-description">一句话故事 <small>选填</small></label><textarea id="new-project-description" name="description" placeholder="你想讲述一个怎样的故事？" maxlength="2000"></textarea></div>${dialogFooter('创建项目')}</form>`,
    {
      onSubmit: async (form) => {
        const payload = Object.fromEntries(new FormData(form));
        payload.language = 'zh';
        const project = await state.api.createProject(payload);
        closeOwnDialog(form);
        state.projectId = project.id;
        await refresh();
        projectRoute(project.id);
        toast(state.api.isDemo ? '示例项目已创建，刷新后恢复初始数据。' : '项目已创建。');
      },
    },
  );
}
function chooseProject() {
  openDialog(
    '选择一个故事',
    `<p>切换当前项目，继续查看它的内容与素材。</p><div class="project-list">${state.projects.map((p, i) => `<button type="button" class="search-result" data-action="select-project" data-id="${h(p.id)}">${icon('folder')}<span>${h(p.name)}</span><small>${h(statusName(p.status))}</small></button>`).join('') || '<p class="settings-tip">还没有项目。</p>'}</div><div class="dialog-footer">${action('new-project', '新建一个故事', 'plus', 'primary')}</div>`,
  );
}
function previewStory() {
  const w = state.workspace;
  if (!w) return;
  openDialog(
    w.project.name,
    `${img(w.project.id === 'demo-rainy-bookstore' ? '/assets/rainy-bookstore.png' : w.project.cover_url, `${w.project.name} 氛围图`, 'dialog-image')}<p>${h(w.project.genre || '短片创作')} · ${h(w.project.aspect_ratio || '16:9')} · ${state.api.isDemo ? '原创氛围示意图' : '项目故事'}</p><div class="dialog-quote">${h(w.script?.logline || w.project.description || '这个故事，等待你写下第一行。')}</div>${storyPreviewContent(w.script)}<div class="dialog-footer">${action('open-project', '进入制作', 'arrow', 'primary', `data-id="${h(w.project.id)}"`)}</div>`,
    { wide: true, label: 'A STORY IN PROGRESS' },
  );
}
async function reviewDialog(id, origin = captureDialogOrigin()) {
  const key = currentScriptKey(),
    w = state.workspace;
  if (!w) return;
  const review = await state.api.getReview(id);
  if (currentScriptKey() !== key) return;
  const isStoryboard = review.stage === 'storyboard';
  const snapshot = review.target_snapshot || review.decision?.storyboard_snapshot;
  let board = null;
  if (isStoryboard && snapshot?.storyboard_id)
    board = await state.api.getStoryboardVersion(snapshot.storyboard_id);
  if (currentScriptKey() !== key) return;
  const canApprove = !isStoryboard || (review.target_status === 'current' && !!snapshot);
  const items = isStoryboard
    ? board?.shots || []
    : review.stage === 'characters_scenes'
      ? [...w.characters, ...w.scenes]
      : [];
  const preview = items.length
    ? `<div class="tags">${items
        .slice(0, 6)
        .map(
          (item, index) =>
            `<span class="tag">${h(item.name || item.description || `镜头 ${index + 1}`)}</span>`,
        )
        .join('')}</div>`
    : '';
  const baseline = isStoryboard
    ? `<div class="review-baseline"><strong>${snapshot ? `送审分镜 V${h(snapshot.storyboard_version)} · 剧本 V${h(snapshot.source_script?.version ?? '—')}` : '待审版本未记录'}</strong><p>${snapshot?.shot_fingerprints ? `${Object.keys(snapshot.shot_fingerprints).length} 个镜头已绑定送审快照。` : '缺少可验证的镜头快照。'}</p>${canApprove ? '' : `<p class="script-notice warning" role="status">${review.status === 'pending' ? '待审内容已变化或无法核验。请先退回，再提交当前分镜。' : '这份记录对应历史快照，当前内容已变化；后续制作需要重新核对与提审。'}</p>`}</div>${board ? `<details class="review-board-preview"><summary>${canApprove ? '查看待审分镜' : '查看当前内容（已不等同于旧快照）'}</summary>${storyboardVersionBody(board, { scenes: w.scenes || [], readOnly: true, history: false })}</details>` : ''}`
    : '';
  openDialog(
    review.title || stageTitle(review.stage),
    `<p>${h(review.description || '核对产物，留下意见后保存审核结论。')}</p>${status(review.status)}${baseline}${preview}<div class="inline-note">${icon('info')}本次只保存审核结论，后续生产由你单独发起。</div>${review.status === 'pending' ? `<form id="dialog-form"><div class="form-field"><label for="review-comment">审核意见</label><textarea id="review-comment" name="comment" rows="3" maxlength="10000" placeholder="记录需要保留或调整的创作选择。"></textarea></div><div class="form-field"><label for="review-decision">审核结论</label><select id="review-decision" name="status"><option value="approved" ${canApprove ? '' : 'disabled'}>通过，确认送审版本</option><option value="rejected" ${canApprove ? '' : 'selected'}>退回，需要调整</option></select></div>${dialogFooter(state.api.isDemo ? '保存模拟审核' : '保存审核结论')}</form>` : `<p class="settings-tip">审核意见：${h(review.comment || '未填写')}</p><div class="dialog-footer">${action('close-dialog', '关闭')}</div>`}`,
    {
      wide: isStoryboard,
      label: isStoryboard ? '第二轮审核' : '人工审核',
      origin,
      onSubmit: async (form) => {
        if (currentScriptKey() !== key) throw new Error('项目或连接已切换，请重新查看审核。');
        const data = Object.fromEntries(new FormData(form));
        if (data.status === 'approved' && !canApprove)
          throw new Error('待审快照已变化，请退回后重新提交。');
        const result = await state.api.decideReview(review.id, { ...data, resume_workflow: false });
        closeOwnDialog(form);
        if (currentScriptKey() === key) {
          state.workspace.reviews = (state.workspace.reviews || []).map((item) =>
            item.id === review.id ? result.review : item,
          );
          await refreshScriptProject(w.project.id, key);
        }
        toast('审核结论已保存。');
      },
    },
  );
}
function showEntity(kind, id) {
  const item = state.workspace?.[kind]?.find((e) => e.id === id);
  if (!item) return;
  openDialog(
    item.name,
    `${img(item.image_url, item.name, 'dialog-image profile-dialog-image')}<p>${h(item.summary)}</p><details class="profile-details"><summary>查看完整结构化档案</summary><pre class="json-view">${h(JSON.stringify(item.profile || {}, null, 2))}</pre></details><form id="dialog-form"><div class="form-field"><label for="entity-name">名称</label><input id="entity-name" name="name" value="${h(item.name)}" required maxlength="120"></div><div class="form-field"><label for="entity-summary">摘要</label><textarea id="entity-summary" name="summary">${h(item.summary)}</textarea></div>${dialogFooter()}</form>`,
    {
      label: kind === 'characters' ? 'CHARACTER PROFILE' : 'SCENE PROFILE',
      onSubmit: async (form) => {
        const payload = Object.fromEntries(new FormData(form));
        await state.api[kind === 'characters' ? 'updateCharacter' : 'updateScene'](id, payload);
        closeOwnDialog(form);
        await refresh();
        toast('档案字段已保存。');
      },
    },
  );
}
async function agentDetail(id, origin = captureDialogOrigin()) {
  const agent = state.agents.find((a) => a.id === id);
  if (!agent) return;
  if (agent.config_access === false) {
    openDialog(
      agent.name,
      `<p>${h(agent.description)}</p><div class="inline-note">${icon('info')}当前身份可查看角色职责；模型配置仅管理员可读取。</div><pre class="json-view">${h(JSON.stringify({ agent_ids: agent.agent_ids, registered_agent_ids: agent.registered_agent_ids }, null, 2))}</pre>`,
      { label: 'CREW / REGISTERED ROLE', origin },
    );
    return;
  }
  const configs = await state.api.getAgentConfigs();
  const target = configs.find((c) => c.id === (agent.agent_ids?.[0] || id));
  openDialog(
    agent.name,
    `<p>${h(agent.description)}</p><div class="inline-note">${icon('info')}${state.api.isDemo ? '修改仅保存在本次示例会话，不会影响后端。' : '保存将创建并激活一个后端配置版本。'}</div>${target ? `<form id="dialog-form"><div class="form-field"><label for="agent-config">执行配置 · ${h(target.id)}</label><textarea id="agent-config" name="payload" class="code-editor" spellcheck="false">${h(JSON.stringify(target.payload, null, 2))}</textarea></div><div class="form-field"><label for="config-note">修改说明</label><input id="config-note" name="note" placeholder="记录这次配置调整的原因"></div>${dialogFooter('保存配置版本')}</form>` : '<p class="settings-tip">当前角色没有可编辑的配置。</p>'}`,
    {
      wide: true,
      label: 'CREW / AGENT CONFIGURATION',
      origin,
      onSubmit: async (form) => {
        let payload;
        try {
          payload = JSON.parse(form.elements.payload.value);
        } catch {
          throw new Error('配置不是有效的 JSON，请检查后再保存。');
        }
        await state.api.updateAgentConfig(target.id, payload, { note: form.elements.note.value });
        closeOwnDialog(form);
        await refresh();
        toast('配置版本已保存。');
      },
    },
  );
}

function directingConfirmation(form) {
  const w = state.workspace;
  const draft = state.directingDraft;
  if (!w || !draft) return;
  draft.instruction = form.elements.instruction.value;
  draft.shots_target = Number(form.elements.shots_target.value);
  const availability = directingFormState({
    workspace: w,
    draft,
    scriptDraft: state.scriptDraft,
    isDemo: state.api.isDemo,
  });
  if (availability.blocked) throw new Error(availability.message);
  const key = currentScriptKey();
  const sourceId = w.script.id;
  const payload = {
    base_script_id: sourceId,
    instruction: draft.instruction,
    shots_target: draft.shots_target,
  };
  openDialog(
    '确认生成导演方案',
    `<p>项目：${h(w.project.name)} · 基于已保存剧本 V${h(w.script.version)}</p><div class="dialog-quote">目标 ${payload.shots_target} 个镜头。成功后另存新版本，历史方案保留。</div>${payload.instruction ? `<pre class="script-version-text">${h(payload.instruction)}</pre>` : ''}<p>${state.api.isDemo ? '本次只记录模拟任务，当前方案仍是静态示例。' : '将调用文字模型，可能产生费用。导演方案完成后，再进入分镜创作与第二轮审核。'}</p><form id="dialog-form">${dialogFooter(state.api.isDemo ? '记录模拟操作' : '确认生成')}</form>`,
    {
      label: state.api.isDemo ? '演示操作' : '导演创作',
      onSubmit: async (confirmationForm) => {
        if (currentScriptKey() !== key || state.workspace?.script?.id !== sourceId)
          throw new Error('项目或剧本已变化，请重新确认。');
        const ready = directingFormState({
          workspace: state.workspace,
          draft,
          scriptDraft: state.scriptDraft,
          isDemo: state.api.isDemo,
        });
        if (ready.blocked) throw new Error(ready.message);
        draft.submitting = true;
        draft.error = '';
        render();
        let failure = null;
        try {
          const result = await state.api.generateDirecting(w.project.id, payload, {
            confirmed: true,
          });
          acknowledgePlanningTask(w.project.id, key, 'directing', result);
          closeOwnDialog(confirmationForm);
          if (currentScriptKey() === key) {
            await refreshScriptProject(w.project.id, key);
          }
          if (result.task?.status === 'failed')
            throw new Error(result.task.error || '导演任务未完成，请查看任务记录。');
        } catch (error) {
          failure = error;
          draft.error =
            error.status === 409 ? '剧本基线已变化，请核对最新稿后重新确认。' : error.message;
          if (error.status === 409 && currentScriptKey() === key) {
            try {
              await loadWorkspace(w.project.id);
            } catch {
              /* 保留原始错误与创作要求。 */
            }
          }
          throw error;
        } finally {
          draft.submitting = false;
          if (currentScriptKey() === key) {
            render();
            if (!$('studio-dialog').open) {
              const notice =
                document.querySelector('[data-directing-error]') || $('directing-form-state');
              if (notice) {
                notice.tabIndex = -1;
                notice.focus({ preventScroll: true });
                if (draft.error && failure && typeof failure === 'object')
                  contextualErrors.add(failure);
              }
            }
          }
        }
      },
    },
  );
}

async function directingVersionDialog(id, origin = captureDialogOrigin()) {
  const projectId = state.workspace?.project.id,
    key = currentScriptKey();
  const plan = await state.api.getDirectingPlan(id);
  if (currentScriptKey() !== key || state.workspace?.project.id !== projectId) return;
  if (plan.project_id && plan.project_id !== projectId) throw new Error('导演方案不属于当前项目。');
  openDialog(
    `导演方案 V${plan.version}`,
    `<p>只读查看，生成新方案会保留本版。</p>${directingPlanBody(plan)}`,
    { wide: true, label: '方案历史', origin },
  );
}

function storyboardConfirmation(form) {
  const w = state.workspace,
    draft = state.storyboardDraft;
  if (!w || !draft) return;
  draft.refine_prompts = form.elements.refine_prompts.checked;
  const ready = storyboardFormState({
    workspace: w,
    draft,
    scriptDraft: state.scriptDraft,
    isDemo: state.api.isDemo,
  });
  if (ready.blocked) throw new Error(ready.message);
  const key = currentScriptKey(),
    sourceId = w.script.id,
    planId = w.directing.id;
  const payload = {
    base_script_id: sourceId,
    base_plan_id: planId,
    refine_prompts: draft.refine_prompts,
  };
  openDialog(
    '确认生成分镜',
    `<p>项目：${h(w.project.name)} · 剧本 V${h(w.script.version)} · 导演方案 V${h(w.directing.version)}</p><div class="dialog-quote">新分镜保留旧版本。完成后可以编辑镜头，再提交第二轮审核。</div><p>${state.api.isDemo ? '本次只记录模拟任务，镜头仍为静态示例。' : payload.refine_prompts ? '将调用分镜模型，并逐镜追加提示词精化调用，可能产生费用。' : '将调用分镜模型生成镜头和基础提示词，可能产生费用。'}</p><form id="dialog-form">${dialogFooter(state.api.isDemo ? '记录模拟操作' : '确认生成')}</form>`,
    {
      label: '分镜创作',
      onSubmit: async (confirmationForm) => {
        if (
          currentScriptKey() !== key ||
          state.workspace?.script?.id !== sourceId ||
          state.workspace?.directing?.id !== planId
        )
          throw new Error('创作基线已变化，请重新确认。');
        const stateNow = storyboardFormState({
          workspace: state.workspace,
          draft,
          scriptDraft: state.scriptDraft,
          isDemo: state.api.isDemo,
        });
        if (stateNow.blocked) throw new Error(stateNow.message);
        draft.submitting = true;
        draft.error = '';
        render();
        let failure = null;
        try {
          const result = await state.api.generateStoryboard(w.project.id, payload, {
            confirmed: true,
          });
          acknowledgePlanningTask(w.project.id, key, 'storyboard', result);
          closeOwnDialog(confirmationForm);
          if (currentScriptKey() === key) await refreshScriptProject(w.project.id, key);
          if (result.task?.status === 'failed')
            throw new Error(result.task.error || '分镜任务未完成，请查看任务记录。');
        } catch (error) {
          failure = error;
          draft.error =
            error.status === 409 ? '剧本或导演方案已变化，请刷新核对后重新确认。' : error.message;
          if (error.status === 409 && currentScriptKey() === key) {
            try {
              await loadWorkspace(w.project.id);
            } catch {
              /* 保留原错误。 */
            }
          }
          throw error;
        } finally {
          draft.submitting = false;
          if (currentScriptKey() === key) {
            render();
            if (!$('studio-dialog').open) {
              const notice =
                document.querySelector('[data-storyboard-error]') || $('storyboard-form-state');
              if (notice) {
                notice.tabIndex = -1;
                notice.focus({ preventScroll: true });
                if (draft.error && failure && typeof failure === 'object')
                  contextualErrors.add(failure);
              }
            }
          }
        }
      },
    },
  );
}

async function storyboardVersionDialog(id, origin = captureDialogOrigin()) {
  const projectId = state.workspace?.project.id,
    key = currentScriptKey();
  const board = await state.api.getStoryboardVersion(id);
  if (currentScriptKey() !== key || state.workspace?.project.id !== projectId) return;
  if (board.project_id && board.project_id !== projectId)
    throw new Error('分镜版本不属于当前项目。');
  openDialog(
    `分镜 V${board.version}`,
    `<p>历史分镜只读查看，当前镜头的编辑不会覆盖其他版本。</p>${storyboardVersionBody(board, { scenes: state.workspace.scenes || [], readOnly: true })}`,
    { wide: true, label: '分镜历史', origin },
  );
}

async function requestStoryboardReview(boardId) {
  const w = state.workspace,
    draft = state.storyboardDraft,
    key = currentScriptKey();
  if (!w?.storyboard || !draft || draft.reviewSubmitting) return;
  if (w.storyboard.id !== boardId) throw new Error('分镜版本已变化，请重新核对。');
  const ready = storyboardReviewState({
    workspace: w,
    draft,
    scriptDraft: state.scriptDraft,
    isDemo: state.api.isDemo,
  });
  if (!ready.canRequest) throw new Error(ready.message);
  draft.reviewSubmitting = true;
  draft.reviewError = '';
  render();
  try {
    const review = await state.api.requestStoryboardReview(w.project.id, boardId);
    if (currentScriptKey() === key) {
      state.workspace.reviews = [
        review,
        ...(state.workspace.reviews || []).filter((item) => item.id !== review.id),
      ];
      state.workspace.pending_reviews = [
        review,
        ...(state.workspace.pending_reviews || []).filter((item) => item.id !== review.id),
      ];
      await refreshScriptProject(w.project.id, key);
    }
  } catch (error) {
    draft.reviewError = error.message;
    if (error.status === 409 && currentScriptKey() === key) {
      try {
        await loadWorkspace(w.project.id);
      } catch {
        /* 保留提审冲突。 */
      }
    }
    contextualErrors.add(error);
  } finally {
    draft.reviewSubmitting = false;
    if (currentScriptKey() === key) {
      render();
      if (draft.reviewError)
        document.querySelector('[data-storyboard-review-error]')?.focus({ preventScroll: true });
      else focusProductionPanel('storyboard-review');
    }
  }
}

async function shotDetails(id, origin = captureDialogOrigin()) {
  const key = currentScriptKey();
  const shot = await state.api.getShot(id);
  if (currentScriptKey() !== key) return;
  openDialog(
    `镜头 ${shot.order || shot.order_index || ''}`,
    storyboardShotDetails(shot, { scenes: state.workspace?.scenes || [] }),
    { wide: true, label: '镜头详情', origin },
  );
}

async function editShotDialog(id, origin = captureDialogOrigin()) {
  const w = state.workspace,
    key = currentScriptKey();
  if (!w?.storyboard) return;
  const shot = await state.api.getShot(id);
  if (currentScriptKey() !== key) return;
  if (shot.storyboard_id !== state.workspace.storyboard?.id)
    throw new Error('历史分镜只读，请编辑当前版本。');
  const camera = shot.camera || {};
  const lines = (shot.dialogue || []).map((line) =>
    typeof line === 'string' ? { text: line, character_name: '' } : { ...line },
  );
  const choose = (current, choices) => {
    const values = choices.some(([value]) => value === current)
      ? choices
      : [[current, current], ...choices];
    return values
      .map(
        ([value, label]) =>
          `<option value="${h(value)}" ${value === current ? 'selected' : ''}>${h(label)}</option>`,
      )
      .join('');
  };
  const type = camera.shot_type || camera.shot_size || camera.type || 'medium_shot';
  const sceneOptions =
    `<option value="">不关联场景档案</option>` +
    (w.scenes || [])
      .map(
        (scene) =>
          `<option value="${h(scene.id)}" ${scene.id === shot.scene_id ? 'selected' : ''}>${h(scene.name)}</option>`,
      )
      .join('');
  openDialog(
    `编辑镜头 ${shot.order || shot.order_index || ''}`,
    `<p>当前分镜 V${h(w.storyboard.version)}。保存后需要重新核对第二轮审核。</p><form id="dialog-form"><div class="form-field"><label for="shot-description">画面描述</label><textarea id="shot-description" name="description" rows="3" maxlength="20000" required>${h(shot.description || '')}</textarea></div><div class="form-field"><label for="shot-action">人物与画面动作</label><textarea id="shot-action" name="action" rows="2" maxlength="20000">${h(shot.action || '')}</textarea></div><div class="form-grid"><div class="form-field"><label for="shot-duration">时长（秒）</label><input id="shot-duration" name="duration_seconds" type="number" min="0" max="60" step="any" value="${h(shot.duration_seconds || 5)}" required></div><div class="form-field"><label for="shot-scene">关联场景</label><select id="shot-scene" name="scene_id">${sceneOptions}</select></div><div class="form-field"><label for="shot-type">景别</label><select id="shot-type" name="shot_type">${choose(
      type,
      [
        ['wide_shot', '全景'],
        ['medium_shot', '中景'],
        ['close_up', '近景'],
        ['extreme_close_up', '特写'],
        ['over_the_shoulder', '过肩镜头'],
      ],
    )}</select></div><div class="form-field"><label for="shot-movement">运镜</label><select id="shot-movement" name="movement">${choose(
      camera.movement || 'static',
      [
        ['static', '固定机位'],
        ['slow_push_in', '缓慢推进'],
        ['dolly_in', '向前移动'],
        ['dolly_out', '向后移动'],
        ['pan', '横摇'],
        ['tracking', '跟拍'],
      ],
    )}</select></div><div class="form-field"><label for="shot-angle">拍摄角度</label><select id="shot-angle" name="angle">${choose(
      camera.angle || 'eye_level',
      [
        ['eye_level', '平视'],
        ['high_angle', '俯视'],
        ['low_angle', '仰视'],
        ['overhead', '顶视'],
      ],
    )}</select></div><div class="form-field"><label for="shot-lens">镜头焦距 <small>可选</small></label><input id="shot-lens" name="lens" value="${h(camera.lens || '')}" maxlength="100" placeholder="例如：50mm"></div></div>${lines.length ? `<fieldset class="shot-edit-dialogue"><legend>对白</legend>${lines.map((line, index) => `<div class="form-field"><label for="shot-dialogue-${index}">${h(line.character_name || (w.characters || []).find((item) => item.id === line.character_id)?.name || `台词 ${index + 1}`)}</label><textarea id="shot-dialogue-${index}" name="dialogue_${index}" rows="2" maxlength="10000">${h(line.text || '')}</textarea></div>`).join('')}<p class="settings-tip">清空某句台词后保存，即可移除该句。</p></fieldset>` : ''}<div class="form-field"><label for="shot-visual-prompt">画面生成提示词</label><textarea id="shot-visual-prompt" name="visual_prompt" rows="4" maxlength="30000" required>${h(shot.visual_prompt || '')}</textarea></div><div class="form-field"><label for="shot-negative-prompt">排除内容 <small>可选</small></label><textarea id="shot-negative-prompt" name="negative_prompt" rows="2" maxlength="10000">${h(shot.negative_prompt || '')}</textarea></div>${dialogFooter('保存镜头')}</form>`,
    {
      wide: true,
      label: '分镜编辑',
      origin,
      onSubmit: async (form) => {
        if (currentScriptKey() !== key || state.workspace?.storyboard?.id !== shot.storyboard_id)
          throw new Error('项目或分镜版本已变化，当前修改保留在表单中。');
        const duration = Number(form.elements.duration_seconds.value);
        if (!Number.isFinite(duration) || duration <= 0 || duration > 60)
          throw new Error('镜头时长须大于0且不超过60秒。');
        const payload = {
          base_storyboard_id: shot.storyboard_id,
          base_shot_fingerprint: shot.edit_fingerprint,
          description: form.elements.description.value,
          action: form.elements.action.value,
          duration_seconds: Number(form.elements.duration_seconds.value),
          scene_id: form.elements.scene_id.value,
          camera: {
            ...camera,
            shot_type: form.elements.shot_type.value,
            movement: form.elements.movement.value,
            angle: form.elements.angle.value,
            lens: form.elements.lens.value,
          },
          dialogue: lines
            .map((line, index) => ({ ...line, text: form.elements[`dialogue_${index}`].value }))
            .filter((line) => line.text.trim()),
          visual_prompt: form.elements.visual_prompt.value,
          negative_prompt: form.elements.negative_prompt.value,
        };
        const saved = await state.api.updateShot(id, payload);
        closeOwnDialog(form);
        if (currentScriptKey() === key) {
          state.workspace.shots = (state.workspace.shots || []).map((item) =>
            item.id === id ? saved : item,
          );
          if (!saved.approved)
            state.workspace.storyboard = {
              ...state.workspace.storyboard,
              approved: false,
              status: 'draft',
            };
          await refreshScriptProject(w.project.id, key);
        }
      },
    },
  );
}

function stageConfirmation(stage) {
  const w = state.workspace;
  if (!w) return;
  const labels = {
    analyze: '剧本解析',
    script: '剧本解析',
    directing: '导演规划',
    storyboard: '生成分镜',
    video: '生成视频',
    audio: '生成声音',
    editing: '编排剪辑',
    render: '合成预览',
    export: '导出成片',
    evaluate: '质量评估',
    evaluation: '质量评估',
    'character-assets': '生成人物形象',
  };
  const title = stage === 'workflow' ? '继续制作流程' : labels[stage] || '制作操作';
  openDialog(
    title,
    `<p>项目：<strong>${h(w.project.name)}</strong></p><div class="dialog-quote">${state.api.isDemo ? '在示例空间，演练一次制作操作。' : '让故事，向下一帧前进。'}</div><p>${state.api.isDemo ? '本次只记录示例任务，不调用模型，也不会生成真实媒体。' : '这会提交后端制作任务，可能调用已配置的供应商并产生费用。执行结果请在任务记录中查看。'}</p>${['analyze', 'script'].includes(stage) ? '<div class="inline-note">这会从小说原文重新解析并创建剧本新版本；编辑器草稿仍保留，后续产物需要重新核对。</div>' : ''}<form id="dialog-form">${dialogFooter(state.api.isDemo ? '记录示例操作' : '提交制作任务')}</form>`,
    {
      label: state.api.isDemo ? 'DEMO / SIMULATED ACTION' : 'LIVE / PRODUCTION TASK',
      onSubmit: async (form) => {
        const options = { confirmed: true };
        let result;
        if (stage === 'workflow')
          result =
            w.workflow?.status === 'awaiting_review'
              ? await state.api.resumeWorkflow(w.project.id, w.workflow.id, options)
              : await state.api.startWorkflow(w.project.id, {}, options);
        else result = await state.api.runStage(w.project.id, stage, {}, options);
        if (result?.task?.status === 'failed')
          throw new Error(result.task.error || '任务执行失败，请检查任务记录。');
        closeOwnDialog(form);
        await refresh();
        toast(
          state.api.isDemo
            ? '示例操作已记录，没有调用模型。'
            : `任务已提交：${statusName(result.task?.status || result.status || 'queued')}`,
        );
      },
    },
  );
}
async function showActivity() {
  const tasks = state.workspace?.tasks || [];
  openDialog(
    '片场任务与动态',
    `<p>${h(state.workspace?.project?.name || '尚未选择项目')} · ${state.api.isDemo ? '示例任务记录' : '后端任务记录'}</p>${tasks.length ? `<ul class="activity-list">${tasks.map((t) => `<li class="activity-item"><span class="activity-icon">${icon(t.status === 'failed' ? 'info' : 'check')}</span><div class="activity-copy"><p><strong>${h(t.message || t.type)}</strong></p><p>${h(t.type)} · ${h(statusName(t.status))}</p>${t.error ? `<p>${h(t.error)}</p>` : ''}<button class="button text-link" data-action="task-detail" data-id="${h(t.id)}">查看任务日志 ${icon('arrow')}</button></div></li>`).join('')}</ul>` : '<p class="settings-tip">开始制作后，执行记录将出现在这里。</p>'}`,
    { label: 'ACTIVITY / TASK LOG' },
  );
}
function assetDetail(id, { origin } = {}) {
  const asset = state.workspace?.assets?.find((a) => a.id === id);
  if (!asset) return;
  const info = assetPresentation(asset);
  const position = assetPreviewPosition(state.workspace.assets, id, {
    filter: state.assetFilter,
    query: state.assetQuery,
    sort: state.assetSort,
  });
  const navigation = position.index
    ? `<nav class="asset-dialog-navigation" aria-label="素材预览切换"><button id="asset-preview-previous" type="button" class="button small" data-action="asset-preview-previous" data-id="${h(position.previousId || '')}" ${position.previousId ? '' : 'disabled'}>上一个</button><span role="status" aria-live="polite">${position.index} / ${position.total}</span><button id="asset-preview-next" type="button" class="button small" data-action="asset-preview-next" data-id="${h(position.nextId || '')}" ${position.nextId ? '' : 'disabled'}>下一个</button></nav>`
    : '';
  const url = mediaUrl(asset.url || asset.image_url);
  const preview =
    info.type === 'image'
      ? img(url, info.name, 'dialog-image')
      : info.type === 'video'
        ? `<video class="dialog-image" src="${h(url)}" controls></video>`
        : info.type === 'audio'
          ? `<audio src="${h(url)}" controls></audio>`
          : '';
  const details = [
    ['文件类型', info.typeLabel],
    ['文件大小', info.sizeLabel],
    ['画面尺寸', asset.width && asset.height ? `${asset.width} × ${asset.height}` : ''],
    ['时长', Number.isFinite(asset.duration_seconds) ? `${asset.duration_seconds} 秒` : ''],
    ['素材编号', asset.id],
  ].filter(([, value]) => value !== '');
  openDialog(
    info.name,
    `${navigation}${preview}<p>${state.api.isDemo ? '此素材为内存示例。' : `来自项目「${h(state.workspace.project.name)}」。`}</p><dl class="asset-detail-meta">${details.map(([name, value]) => `<div><dt>${h(name)}</dt><dd>${h(value)}</dd></div>`).join('')}</dl>${url ? `<div class="dialog-footer"><a class="button" href="${h(url)}" target="_blank" rel="noopener">打开原文件 ${icon('arrow')}</a></div>` : ''}`,
    { label: '项目素材', ...(origin ? { origin } : {}) },
  );
}

function moveAssetPreview(button, origin) {
  if (!button.dataset.id) return;
  assetDetail(button.dataset.id, { origin });
  // 替换弹窗后保留连续浏览控件焦点；到边界时转到可用的相邻按钮。
  const preferred = $(button.id);
  const fallback = $('asset-preview-next')?.disabled
    ? $('asset-preview-previous')
    : $('asset-preview-next');
  (preferred && !preferred.disabled ? preferred : fallback)?.focus({ preventScroll: true });
}

const handlers = {
  navigate: (b) => navigate(b.dataset.view),
  'open-project': (b) => {
    if (state.view === 'projects' && b.classList.contains('project-card')) {
      libraryReturn = {
        connection: JSON.stringify(state.api.getConnection()),
        projectId: b.dataset.id,
        scrollY: window.scrollY,
      };
    }
    if (state.view === 'assets') {
      assetReturn = {
        scope: JSON.stringify([state.api.getConnection(), state.workspace?.project.id]),
        target: captureFocusTarget(b),
        scrollY: window.scrollY,
      };
    }
    closeStudioDialog({ restoreFocus: false });
    projectRoute(
      b.dataset.id,
      // 另一个项目的审核阶段不能决定当前点击项目的落点。
      state.workspace?.project.id === b.dataset.id &&
        state.workspace?.pending_reviews?.[0]?.stage === 'storyboard'
        ? 'storyboard'
        : 'story',
    );
  },
  'new-project': newProject,
  'choose-project': chooseProject,
  'preview-story': previewStory,
  'close-dialog': () => closeStudioDialog(),
  'select-project': async (b) => {
    await loadWorkspace(b.dataset.id);
    // 慢请求完成时只关闭自己的选择窗，不能关闭用户后来打开的其他弹窗。
    if (b.isConnected && $('studio-dialog').contains(b)) closeStudioDialog({ restoreFocus: false });
    if (state.view === 'workbench') projectRoute(b.dataset.id);
    else {
      if (state.view === 'assets') {
        state.assetFilter = 'all';
        state.assetQuery = '';
      }
      render();
      if (state.view === 'assets') $('asset-project-heading')?.focus({ preventScroll: true });
    }
  },
  tab: (b) => projectRoute(state.projectId, b.dataset.tab),
  filter: (b) => {
    state.filter = b.dataset.filter;
    renderLibraryControl(b);
  },
  'clear-project-filters': (b) => {
    state.filter = 'all';
    state.query = '';
    renderLibraryControl(b);
  },
  'agent-filter': (b) => {
    state.agentFilter = b.dataset.filter;
    render();
  },
  'asset-filter': (b) => {
    state.assetFilter = b.dataset.filter;
    renderLibraryControl(b);
  },
  'clear-asset-filters': (b) => {
    state.assetFilter = 'all';
    state.assetQuery = '';
    renderLibraryControl(b);
  },
  'review-filter': (b) => {
    state.reviewFilter = b.dataset.filter;
    render();
  },
  review: (b, origin) => reviewDialog(b.dataset.id, origin),
  'entity-detail': (b) => showEntity(b.dataset.kind, b.dataset.id),
  'asset-detail': (b, origin) => assetDetail(b.dataset.id, { origin }),
  'asset-preview-previous': moveAssetPreview,
  'asset-preview-next': moveAssetPreview,
  'agent-detail': (b, origin) => agentDetail(b.dataset.id, origin),
  'shot-detail': (b, origin) => shotDetails(b.dataset.id, origin),
  'edit-shot': (b, origin) => editShotDialog(b.dataset.id, origin),
  'edit-script': () => {
    projectRoute(state.projectId, 'story');
    setTimeout(() => $('script-text')?.focus(), 0);
  },
  'import-script': importScriptDialog,
  'toggle-script-focus': () => setScriptFocus(!state.scriptFocus),
  'script-panel': (button) => focusScriptPanel(button.dataset.panel),
  'script-return-editor': () => {
    $('script-text')?.focus({ preventScroll: true });
    $('script-text')?.scrollIntoView({ behavior: 'auto', block: 'center' });
  },
  'script-version': (button, origin) => scriptVersionDialog(button.dataset.id, origin),
  'discard-script-draft': discardScriptDraftDialog,
  'rebase-script-draft': rebaseScriptDraftDialog,
  'upload-source': uploadSourceDialog,
  'import-sample': async () => {
    if (!state.projectId) return;
    await state.api.importSample(state.projectId);
    await refresh();
    toast('示例原文已导入，可继续执行剧本解析。');
  },
  'start-workflow': () => stageConfirmation('workflow'),
  'run-stage': (b) => stageConfirmation(b.dataset.stage),
  activity: showActivity,
  'task-detail': async (b, origin) => {
    const events = await state.api.getTaskEvents(state.projectId, b.dataset.id);
    openDialog(
      '任务执行记录',
      `<p>${h(b.dataset.id)}</p><pre class="json-view">${h(JSON.stringify(events, null, 2))}</pre>`,
      { wide: true, label: 'TASK / EXECUTION EVENTS', origin },
    );
  },
  'directing-version': (b, origin) => directingVersionDialog(b.dataset.id, origin),
  'storyboard-version': (b, origin) => storyboardVersionDialog(b.dataset.id, origin),
  'request-storyboard-review': (b) => requestStoryboardReview(b.dataset.id),
  'production-panel': (b) => focusProductionPanel(b.dataset.panel),
  'production-return': (b) => focusProductionPanel(b.dataset.panel),
  refresh: async () => {
    await refresh();
    toast('项目内容已更新。');
  },
  'switch-demo': async () => {
    rememberScriptDraft();
    state.api.configure({ mode: 'demo' });
    state.connection = state.api.getConnection();
    state.error = null;
    state.projectId = '';
    const url = new URL(location);
    url.searchParams.set('mode', 'demo');
    url.hash = 'overview';
    history.replaceState(null, '', url);
    state.view = 'overview';
    state.workspace = null;
    render();
    await refresh();
  },
  'test-connection': async () => {
    const f = $('connection-form');
    const baseUrl = f.elements.baseUrl.value;
    const probe = createStudioApi({
      ...Object.fromEntries(new FormData(f)),
      baseUrl,
      mode: 'live',
    });
    await probe.getMeta();
    toast('接口响应正常；这不代表模型供应商已验证在线。');
  },
};

document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const fn = handlers[button.dataset.action];
  if (!fn) return;
  event.preventDefault();
  if (button.closest('#search-results')) closeSearch();
  // 禁用当前按钮会使浏览器将焦点退回 BODY，必须先记住实际触发控件。
  dialogInteraction++;
  const origin = captureDialogOrigin(button);
  try {
    button.disabled = true;
    const previousOrigin = dialogActionOrigin;
    let result;
    try {
      dialogActionOrigin = origin;
      result = fn(button, origin);
    } finally {
      // 异步弹窗通过显式 origin 传递；不能让请求期间的全局来源污染下一次点击。
      dialogActionOrigin = previousOrigin;
    }
    await result;
  } catch (e) {
    showError(e);
  } finally {
    if (button.isConnected) button.disabled = false;
  }
});
document.addEventListener('submit', async (event) => {
  if (event.target.id === 'storyboard-form') {
    event.preventDefault();
    try {
      storyboardConfirmation(event.target);
    } catch (error) {
      showError(error);
    }
  } else if (event.target.id === 'directing-form') {
    event.preventDefault();
    try {
      directingConfirmation(event.target);
    } catch (error) {
      showError(error);
    }
  } else if (event.target.id === 'script-editor-form') {
    event.preventDefault();
    for (const field of SCRIPT_FIELDS)
      updateScriptDraft(state.scriptDraft, field, event.target.elements[field].value);
    rememberScriptDraft();
    try {
      await saveScriptDraft();
    } catch (error) {
      showError(error);
    }
  } else if (event.target.id === 'script-assist-form') {
    event.preventDefault();
    try {
      scriptAssistConfirmation(event.target);
    } catch (error) {
      showError(error);
    }
  } else if (event.target.id === 'dialog-form') {
    event.preventDefault();
    if (!dialogHandler) return;
    const form = event.target,
      submit = form.querySelector('[type="submit"]');
    try {
      if (submit) submit.disabled = true;
      const previousError = form.querySelector('.dialog-form-error');
      if (previousError) previousError.remove();
      await dialogHandler(form);
    } catch (e) {
      showDialogFormError(form, e);
    } finally {
      if (submit?.isConnected) submit.disabled = false;
    }
  } else if (event.target.id === 'connection-form') {
    event.preventDefault();
    const form = event.target;
    try {
      state.controller?.abort();
      clearTimeout(state.poll);
      rememberScriptDraft();
      state.api.configure(Object.fromEntries(new FormData(form)));
      state.connection = state.api.getConnection();
      state.projectId = '';
      state.workspace = null;
      const url = new URL(location);
      url.searchParams.set('mode', state.api.mode);
      history.replaceState(null, '', url);
      render();
      await refresh();
      toast(state.api.isDemo ? '已切换到示例空间。' : '已切换后端连接，没有自动启动生成。');
    } catch (e) {
      state.error = e;
      render();
      showError(e);
    }
  }
});
document.addEventListener('input', (event) => {
  if (event.target.closest('#storyboard-form')) {
    if (state.storyboardDraft) {
      state.storyboardDraft.refine_prompts =
        event.target.closest('form').elements.refine_prompts.checked;
      state.storyboardDraft.error = '';
      document.querySelector('[data-storyboard-error]')?.remove();
      updateStoryboardControls();
    }
  } else if (event.target.closest('#directing-form')) {
    const form = event.target.closest('form'),
      draft = state.directingDraft;
    if (draft) {
      draft.instruction = form.elements.instruction.value;
      draft.shots_target = form.elements.shots_target.value;
      draft.error = '';
      document.querySelector('[data-directing-error]')?.remove();
      updateDirectingControls();
    }
  } else if (
    event.target.closest('#script-editor-form') &&
    SCRIPT_FIELDS.includes(event.target.name)
  ) {
    updateScriptDraft(state.scriptDraft, event.target.name, event.target.value);
    rememberScriptDraft();
    updateScriptControls();
  } else if (event.target.closest('#script-assist-form')) {
    const form = event.target.closest('form'),
      key = currentScriptKey();
    state.scriptAssistDrafts[key] = {
      operation: form.elements.operation.value,
      instruction: form.elements.instruction.value,
      error: '',
    };
  } else if (event.target.id === 'project-filter') {
    if (!event.target.isConnected) return;
    state.query = event.target.value;
    if (!event.isComposing && !projectSearchComposing) renderLibraryControl(event.target);
  } else if (event.target.id === 'asset-query') {
    if (!event.target.isConnected) return;
    state.assetQuery = event.target.value;
    if (!event.isComposing && !assetSearchComposing) renderLibraryControl(event.target);
  }
});
document.addEventListener('compositionstart', (event) => {
  if (event.target.id === 'project-filter') projectSearchComposing = true;
  if (event.target.id === 'asset-query') assetSearchComposing = true;
});
document.addEventListener('compositionend', (event) => {
  if (event.target.id === 'asset-query' && event.target.isConnected) {
    assetSearchComposing = false;
    state.assetQuery = event.target.value;
    renderLibraryControl(event.target);
    return;
  }
  if (event.target.id !== 'project-filter' || !event.target.isConnected) return;
  projectSearchComposing = false;
  state.query = event.target.value;
  renderLibraryControl(event.target);
});
document.addEventListener('change', (event) => {
  if (event.target.id === 'asset-sort') {
    if (['default', 'name'].includes(event.target.value)) state.assetSort = event.target.value;
    renderLibraryControl(event.target);
    return;
  }
  if (event.target.id !== 'project-sort') return;
  const value = event.target.value;
  if (PROJECT_SORTS.some(([id]) => id === value)) state.projectSort = value;
  renderLibraryControl(event.target);
});
$('global-search').addEventListener('input', (event) => {
  if (!event.isComposing) renderSearchResults();
});
$('global-search').addEventListener('focus', renderSearchResults);
$('global-search').addEventListener('compositionstart', closeSearch);
$('global-search').addEventListener('compositionend', renderSearchResults);
$('global-search').addEventListener('keydown', (event) => {
  if (
    $('search-results').hidden &&
    ['ArrowDown', 'ArrowUp'].includes(event.key) &&
    !event.isComposing &&
    event.keyCode !== 229 &&
    !event.altKey &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.shiftKey
  )
    renderSearchResults();
  const next = searchKeyboardAction(event, {
    count: globalSearchItems.length,
    index: globalSearchIndex,
    open: !$('search-results').hidden,
  });
  if (!next) return;
  if (next.preventDefault) {
    event.preventDefault();
    event.stopPropagation();
  }
  if (next.close) closeSearch();
  else if (next.activate !== undefined) {
    const option = $('search-results').querySelectorAll('button[role="option"]')[next.activate];
    closeSearch();
    option?.click();
  } else selectSearchResult(next.index);
});
// 鼠标选择与键盘选择共用按钮操作，mousedown 不把 combobox 焦点移到结果上。
$('search-results').addEventListener('mousedown', (event) => {
  if (event.target.closest('button[role="option"]')) event.preventDefault();
});
window.addEventListener('resize', positionSearchResults);
document.addEventListener('click', (e) => {
  if (!e.target.closest('.search-wrap')) closeSearch();
});
document.addEventListener('keydown', (e) => {
  // 输入法的 Escape 用于取消候选文字，不能同时退出写作布局或触发全局快捷键。
  if (e.isComposing) return;
  if (
    isScriptSaveShortcut(e, {
      view: state.view,
      tab: state.tab,
      dialogOpen: $('studio-dialog').open,
      hasEditor: !!$('script-editor-form'),
    })
  ) {
    e.preventDefault();
    if (e.repeat) return;
    const form = $('script-editor-form');
    for (const field of SCRIPT_FIELDS)
      updateScriptDraft(state.scriptDraft, field, form.elements[field].value);
    rememberScriptDraft();
    updateScriptControls();
    void saveScriptDraft().catch(showError);
    return;
  }
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    if (state.scriptFocus && !$('studio-dialog').open) setScriptFocus(false);
    $('global-search').focus();
    renderSearchResults();
  }
  if (e.key === 'Escape') {
    // 原生弹窗优先消费 Escape；不能在关闭弹窗的同时退出专注布局。
    if (state.scriptFocus && !$('studio-dialog').open) {
      e.preventDefault();
      setScriptFocus(false);
      return;
    }
    closeSearch();
    closeMenu(true);
  }
});
$('menu-toggle').addEventListener('click', () => {
  const open = $('sidebar').classList.toggle('open');
  $('sidebar-scrim').hidden = !open;
  $('menu-toggle').setAttribute('aria-expanded', String(open));
  if (open) $('primary-nav').querySelector('button')?.focus();
});
$('sidebar-scrim').addEventListener('click', () => closeMenu(true));
// 跳转链接只移动焦点，不能把当前项目路由改写成概览。
document.querySelector('.skip-link').addEventListener('click', (event) => {
  event.preventDefault();
  $('main-content').focus({ preventScroll: true });
  $('main-content').scrollIntoView({ behavior: 'auto', block: 'start' });
});
$('studio-dialog').addEventListener('cancel', (event) => {
  // Escape 只走统一关闭入口，避免浏览器默认关闭和应用关闭形成两套焦点时序。
  event.preventDefault();
  closeStudioDialog();
});
$('studio-dialog').addEventListener('close', () => {
  const closed = dialogClosures.shift();
  if (!closed?.restoreFocus) return;
  // 原生关闭先完成，再在下一帧恢复；新弹窗、后续操作或项目切换均使旧恢复失效。
  requestAnimationFrame(() => {
    if (
      $('studio-dialog').open ||
      closed.session !== dialogSession ||
      closed.interaction !== dialogInteraction
    )
      return;
    const origin = closed.origin;
    const target = resolveFocusTarget(origin?.target, {
      originalScope: origin?.scope,
      scope: dialogFocusScope(),
      candidates: document.querySelectorAll('button, a, input, select, textarea, [tabindex]'),
    });
    if (!mayRestoreDialogFocus(document.activeElement, target, $('studio-dialog'))) return;
    target?.focus({ preventScroll: true });
  });
});
$('studio-dialog').addEventListener('click', (e) => {
  if (e.target === $('studio-dialog')) {
    const rect = e.target.getBoundingClientRect();
    if (
      e.clientX < rect.left ||
      e.clientX > rect.right ||
      e.clientY < rect.top ||
      e.clientY > rect.bottom
    )
      closeStudioDialog();
  }
});
window.addEventListener('hashchange', route);
window.addEventListener('beforeunload', (event) => {
  if (Object.values(state.scriptDrafts).some((draft) => draft.dirty)) {
    event.preventDefault();
    event.returnValue = '';
  }
});
window.addEventListener('pagehide', () => {
  state.controller?.abort();
  clearTimeout(state.poll);
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) clearTimeout(state.poll);
  else schedulePoll();
});
document
  .querySelectorAll('[data-icon]')
  .forEach((node) => (node.innerHTML = icon(node.dataset.icon)));

try {
  try {
    state.projectId = localStorage.getItem(`studio.project.${state.api.mode}`) || '';
  } catch {
    /* 存储不可用不影响浏览。 */
  }
  await refresh();
  await route();
} catch (error) {
  state.error = error;
  render();
}
