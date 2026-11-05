/** 纯展示层：只接收已取得的数据，不直接访问后端或触发生成。 */
import { icon } from './icons.js';
import { PROJECT_SORTS, projectLibraryItems } from './project-library.js';
import { assetPresentation, filterAssets } from './asset-library.js';
import { directingFormState, planningTaskError } from './directing-state.js';
import { storyboardFormState, storyboardReviewState } from './storyboard-state.js';
import {
  createScriptDraft,
  scriptSourceName,
  scriptStructure,
  scriptAssistState,
  scriptSaveState,
} from './script-editor.js';

export const NAV = [
  ['overview', '创作概览', 'grid'],
  ['projects', '我的项目', 'folder'],
  ['assets', '素材管理', 'layers'],
  ['agents', '智能体团队', 'agents'],
  ['reviews', '审核中心', 'review'],
  ['settings', '工作室设置', 'settings'],
];
export const TABS = [
  ['story', '剧本', 'script'],
  ['characters', '人物', 'people'],
  ['scenes', '场景', 'location'],
  ['directing', '导演', 'film'],
  ['storyboard', '分镜', 'grid'],
  ['video', '视频', 'play'],
  ['audio', '声音', 'sound'],
  ['editing', '剪辑', 'edit'],
  ['evaluation', '评估', 'review'],
  ['reviews', '审核', 'check'],
  ['models', '模型配置', 'settings'],
];
export const h = (value) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
export const action = (name, text, symbol = '', classes = '', extra = '') =>
  `<button type="button" class="button ${classes}" data-action="${h(name)}" ${extra}>${symbol ? icon(symbol) : ''}${h(text)}</button>`;
export function mediaUrl(value) {
  const url = String(value || '');
  return /^(\/|https?:\/\/|data:image\/(svg\+xml|png|jpeg|webp)[;,])/i.test(url) &&
    !url.startsWith('//')
    ? url
    : '';
}
export const img = (url, alt, classes = '', extra = '') =>
  mediaUrl(url)
    ? `<img src="${h(mediaUrl(url))}" alt="${h(alt)}" class="${classes}" loading="lazy" ${extra}>`
    : '';
export const statusName = (value) =>
  ({
    awaiting_review: '等待审核',
    pending_review: '待审核',
    pending: '待处理',
    draft: '筹备中',
    created: '新建项目',
    ingested: '原文已导入',
    script_ready: '剧本已保存',
    approved: '已确认',
    completed: '已完成',
    succeeded: '已完成',
    running: '制作中',
    queued: '排队中',
    failed: '未完成',
    rejected: '已退回',
    cancelled: '已取消',
    characters_ready: '设定已就绪',
    storyboard_ready: '分镜已就绪',
    exported: '已导出',
    demo: '示例配置',
  })[value] ||
  value ||
  '准备中';
export function status(value) {
  return `<span class="status-label ${['awaiting_review', 'pending_review', 'pending', 'running', 'queued'].includes(value) ? 'orange' : ['draft', 'created', 'cancelled'].includes(value) ? 'gray' : ''}">${h(statusName(value))}</span>`;
}
export function empty(title, text, button = '', symbol = 'film') {
  return `<div class="empty-state">${icon(symbol)}<h3>${h(title)}</h3><p>${h(text)}</p>${button}</div>`;
}
export function heading(title, subtitle, label = 'YOUR CREATIVE WORKSPACE', controls = '') {
  return `<div class="page-heading reveal"><div><div class="eyebrow">${h(label)}</div><h1>${h(title)}</h1><p class="subtitle">${h(subtitle)}</p></div><div class="heading-actions">${controls}</div></div>`;
}
export function section(title, english = '', controls = '') {
  return `<div class="section-heading"><h2>${h(title)}${english ? `<small>${h(english)}</small>` : ''}</h2>${controls}</div>`;
}
const percent = (project) =>
  project?.demo && Number.isFinite(project.progress) ? Math.round(project.progress * 100) : null;
const date = (value) =>
  value
    ? new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
    : '尚无记录';
const cover = (project, index = 0) =>
  project?.id === 'demo-rainy-bookstore'
    ? '/assets/rainy-bookstore.png'
    : index === 0 && !project?.demo
      ? project?.cover_url
      : '';

export function projectCard(project, index = 0) {
  const progress = percent(project);
  return `<button class="project-card" data-action="open-project" data-id="${h(project.id)}" aria-label="进入项目：${h(project.name)}" title="${h(project.name)}"><div class="project-art ${index % 3 === 1 ? 'sunrise' : index % 3 === 2 ? 'bluehour' : ''}">${img(cover(project), `${project.name} 项目封面`)}<span class="art-number">PROJECT / ${String(index + 1).padStart(2, '0')}</span><span class="project-art-title">${h(project.name)}</span></div><div class="project-card-body"><div class="project-card-title"><span class="project-card-name">${h(project.name)}</span>${icon('arrow')}</div><div class="project-card-meta"><span>${h(project.genre || '短片创作')} · ${h(project.aspect_ratio || '16:9')}</span>${status(project.status)}</div>${progress !== null ? `<div class="task-track"><span style="width:${progress}%"></span></div>` : `<div class="table-meta">更新于 ${h(date(project.updated_at))}</div>`}</div></button>`;
}
export function timeline(w) {
  const labels = [
    ['剧本解析', 'script'],
    ['人物场景', 'people'],
    ['分镜设计', 'grid'],
    ['视频生成', 'film'],
    ['声音制作', 'sound'],
    ['剪辑成片', 'edit'],
  ];
  const ready = [
    !!w.script,
    !!w.characters?.length && !!w.scenes?.length,
    !!w.shots?.length,
    !!w.assets?.some((a) => a.mime_type?.startsWith('video/')),
    !!w.assets?.some((a) => a.mime_type?.startsWith('audio/')),
    !!w.dashboard?.film,
  ];
  const pending = w.pending_reviews?.[0];
  let current =
    pending?.stage === 'storyboard'
      ? 2
      : pending?.stage === 'characters_scenes'
        ? 1
        : pending?.stage === 'shots'
          ? 3
          : pending?.stage === 'final'
            ? 5
            : ready.findIndex((v) => !v);
  if (current === -1) current = 6;
  return `<div class="workflow-steps">${labels.map(([label, symbol], i) => `<div class="workflow-step ${i < current ? 'done' : i === current ? 'current' : ''}"><span class="step-symbol">${icon(i < current ? 'check' : symbol)}</span><span class="step-label">${label}</span><span class="step-order">${String(i + 1).padStart(2, '0')}</span></div>`).join('')}</div>`;
}
function activityList(w) {
  const items = w.activities?.length
    ? w.activities
    : w.tasks?.map((t) => ({
        title: t.message || statusName(t.status),
        description: t.type,
        created_at: t.created_at,
        type: t.status,
      })) || [];
  return items.length
    ? `<ul class="activity-list">${items
        .slice(0, 4)
        .map(
          (a, i) =>
            `<li class="activity-item"><span class="activity-icon ${i === 0 ? 'orange' : ''}">${icon(a.type === 'review' ? 'review' : a.type === 'running' ? 'spark' : 'check')}</span><div class="activity-copy"><p><strong>${h(a.title)}</strong></p><p>${h(a.description || '')}</p><small>${h(date(a.created_at))} · ${w.demo ? '示例记录' : '制作记录'}</small></div></li>`,
        )
        .join('')}</ul>`
    : `<p class="settings-tip">这里会记录任务执行与审核动态。</p>`;
}
function reviewRail(w) {
  const review = w.pending_reviews?.[0];
  return `<div class="review-panel">${section('待办审核', '', '<span class="count-badge">' + (w.pending_reviews?.length || 0) + '</span>')}${
    review
      ? `<div class="review-card"><span class="review-type">${icon('review')}需要你的创作判断</span><h3>${h(review.title || stageTitle(review.stage))}</h3><p>${h(review.description || '请检查当前产物，确认后再进入下一阶段。')}</p><div class="review-mini-shots">${(
          w.shots || []
        )
          .slice(0, 3)
          .map(
            (s, i) =>
              `<div class="mini-shot">${img(s.image_url, '示例分镜')}<span>SHOT ${String(i + 1).padStart(2, '0')}</span></div>`,
          )
          .join(
            '',
          )}</div>${action('review', '查看并审核', 'arrow', 'primary full', `data-id="${h(review.id)}"`)}</div><div class="review-secondary">${icon('clock')}每一步重要决定，始终由你掌握</div>`
      : `<div class="review-card"><h3>暂时没有待审内容</h3><p>智能体完成阶段产物后，审核任务将显示在这里。</p></div>`
  }</div>`;
}
export const stageTitle = (stage) =>
  ({
    characters_scenes: '人物与场景审核',
    storyboard: '分镜设计审核',
    shots: '镜头视频审核',
    final: '最终成片审核',
  })[stage] || '制作内容审核';

/** 真实项目无封面时显示明确空态，不借用示例电影画面。 */
function projectVisual(project) {
  const source = cover(project);
  if (source) return img(source, `${project.name}电影氛围图`, 'hero-image', 'fetchpriority="high"');
  return `<div class="hero-cover-placeholder"><span>${icon('film')}</span><strong>每一帧，从故事开始</strong><small>当前项目暂无封面</small>${action('preview-story', '阅读故事', 'arrow', 'text-link')}</div>`;
}

/** 概览阅读已有正文；手写稿不需要先有模型生成的梗概，也不能被误报为没有剧本。 */
export function storyPreviewContent(script) {
  if (!script) return '<p>尚未保存剧本，可以进入项目直接编写或导入。</p>';
  const text = script.script_text || script.content?.script_text || '';
  if (text.trim())
    return `<p class="settings-tip">当前 V${h(script.version)} · 已保存正文，只读预览</p><pre class="script-version-text">${h(text)}</pre>`;
  return `<p>${h(script.synopsis || '当前剧本尚无独立正文，可进入项目补充；已有结构化内容仍保留。')}</p>`;
}

export function overview(state) {
  const { projects, workspace: w, agents } = state;
  const dateText = new Date().toLocaleDateString('zh-CN', {
    month: 'long',
    day: 'numeric',
    weekday: 'long',
  });
  const intro = heading(
    '你的故事，正在成形。',
    '从第一行文字，到最后一帧画面。',
    'A NEW DAY. A NEW STORY.',
    `<span class="date-note">${h(dateText)}</span>${action('new-project', '新建项目', 'plus', 'primary')}`,
  );
  if (!w)
    return (
      intro +
      empty(
        '让第一个故事开始',
        '创建项目，导入你的小说，为下一部作品准备片场。',
        action('new-project', '创建第一个项目', 'plus', 'primary'),
        'folder',
      )
    );
  const p = w.project;
  const stats = [
    ['创作项目', projects.length, '部作品', 'folder'],
    ['智能体角色', agents.length, '协作分工', 'agents'],
    ['等待你审核', w.pending_reviews?.length || 0, '待处理', 'review'],
    ['项目素材', w.assets?.length || 0, '已归档', 'layers'],
  ];
  return (
    intro +
    `<div class="stats-strip overview-stats reveal delay-1">${stats.map(([label, value, note, symbol], i) => `<div class="stat"><div class="stat-top">${label}${icon(symbol)}</div><div class="stat-value"><strong class="${i === 2 ? 'orange' : ''}">${String(value).padStart(2, '0')}</strong>${i === 1 ? '<span class="unit">/ 13</span>' : ''}<small>${note}</small></div></div>`).join('')}</div><div class="overview-grid"><div class="main-column"><section class="reveal delay-1">${section('继续创作', 'CONTINUE CREATING', action('navigate', '全部项目', 'arrow', 'text-link', 'data-view="projects"'))}<div class="featured-project ${cover(p) ? '' : 'is-coverless'}">${projectVisual(p)}<div class="featured-content"><div class="hero-kicker"><span>当前创作项目</span><span class="hero-counter">01 — ${String(projects.length).padStart(2, '0')}</span></div><span class="hero-tag">${h(p.genre || '短片创作')}</span><h2>${h(p.name)}</h2><p class="hero-description">${h(p.description || '每一个值得讲述的故事，都从这里开始。')}</p><div class="hero-bottom"><div class="hero-meta"><span>${icon('film')}${h(p.aspect_ratio || '16:9')} 宽银幕</span><span class="hero-status">${h(statusName(p.status))}</span></div><div class="hero-actions">${!cover(p) ? action('preview-story', '阅读故事', 'script', 'text-link hero-reading-link') : ''}${action('open-project', '进入制作', 'arrow', '', `data-id="${h(p.id)}"`)}</div></div></div><button class="hero-play" data-action="preview-story" aria-label="预览项目故事">${icon('play')}</button></div></section><section class="panel production-panel reveal delay-2">${section('制作进程', 'PRODUCTION FLOW', `<span class="progress-caption">${p.demo ? '示例进度' : ''}<strong>${percent(p) !== null ? percent(p) + '%' : h(statusName(p.status))}</strong></span>`)}${timeline(w)}<div class="workflow-note"><span>${icon('info')}${w.pending_reviews?.length ? '阶段产物已准备好，等待你的确认。' : '按阶段推进，为每个重要决定保留空间。'}</span>${action(w.pending_reviews?.length ? 'review' : 'open-project', w.pending_reviews?.length ? '前往审核' : '查看流程', 'arrow', 'text-link', `data-id="${h(w.pending_reviews?.[0]?.id || p.id)}"`)}</div></section><section class="reveal delay-3">${section('我的项目', 'YOUR STORIES', action('navigate', '管理项目', 'arrow', 'text-link', 'data-view="projects"'))}<div class="project-row-grid">${projects.slice(0, 3).map(projectCard).join('')}</div></section></div><aside class="right-column"><section class="reveal delay-2">${reviewRail(w)}</section><section class="panel activity-panel reveal delay-3">${section('片场动态', 'ACTIVITY', action('activity', '全部', '', 'text-link'))}${activityList(w)}</section><div class="rail-note reveal delay-3">${icon('agents')}<div><strong>13 个角色，一个共同的故事</strong>从剧本、美术到后期，让专业分工陪你完成创作。</div></div></aside></div>`
  );
}
export function projectsView(state) {
  const projects = state.projects || [];
  const filtered = projectLibraryItems(projects, {
    filter: state.filter,
    query: state.query,
    sort: state.projectSort,
  });
  const query = String(state.query || '').trim();
  const filter = ['active', 'completed'].includes(state.filter) ? state.filter : 'all';
  const title = heading(
    '把灵感，存进片场。',
    '每一个项目，都是一个正在展开的世界。',
    'YOUR STORY COLLECTION',
    action('new-project', '新建项目', 'plus', 'primary'),
  );
  if (!projects.length)
    return (
      title +
      `<section class="library-empty">${empty('还没有项目', '创建第一个项目，为你的故事准备一个片场。', action('new-project', '创建第一个项目', 'plus', 'primary'), 'folder')}</section>`
    );
  const toolbar = `<div class="filter-bar library-toolbar"><div class="filter-tabs">${[
    ['all', '全部项目'],
    ['active', '创作中'],
    ['completed', '已完成'],
  ]
    .map(
      ([id, name]) =>
        `<button class="filter-button ${filter === id ? 'active' : ''}" data-action="filter" data-filter="${id}" aria-pressed="${filter === id}">${name}</button>`,
    )
    .join(
      '',
    )}</div><label class="filter-search">${icon('search')}<input id="project-filter" type="search" aria-label="搜索项目名称" aria-describedby="library-results-status" placeholder="按项目名称查找" value="${h(state.query || '')}"></label><label class="library-sort" for="project-sort">排序<select id="project-sort" aria-label="项目排序">${PROJECT_SORTS.map(([id, name]) => `<option value="${id}" ${(state.projectSort || 'updated') === id ? 'selected' : ''}>${name}</option>`).join('')}</select></label></div>`;
  const summary = `<p class="library-results-status" id="library-results-status" role="status" aria-live="polite" tabindex="-1">已载入 ${projects.length} 个项目 · 显示 ${filtered.length} 个${query ? ` · 搜索“${h(query)}”` : ''}${filter === 'active' ? ' · 创作中' : filter === 'completed' ? ' · 已完成' : ''}</p>`;
  if (!filtered.length)
    return (
      title +
      toolbar +
      summary +
      `<section class="library-empty">${empty('没有找到匹配项目', query ? `没有名称匹配“${query}”的项目，可调整关键词或清除筛选。` : '当前分类没有项目，可清除筛选查看其他项目。', action('clear-project-filters', '清除筛选', 'refresh'), 'search')}</section>`
    );
  return (
    title +
    toolbar +
    summary +
    `<div class="library-grid">${filtered.map(projectCard).join('')}<button class="new-project-card" data-action="new-project">${icon('plus')}<span>一个新故事，从这里开始</span><small>导入小说 · 定义风格 · 开始创作</small></button></div>`
  );
}
export function agentsView(state) {
  const filtered = state.agents.filter(
    (a) => !state.agentFilter || state.agentFilter === 'all' || a.category === state.agentFilter,
  );
  const categories = [...new Set(state.agents.map((a) => a.category).filter(Boolean))];
  const symbols = [
    'agents',
    'script',
    'people',
    'image',
    'image',
    'location',
    'film',
    'grid',
    'spark',
    'play',
    'sound',
    'edit',
    'review',
  ];
  return (
    heading(
      '你的幕后创作团队。',
      '专业分工，各司其职；创作的方向，始终在你手中。',
      'MEET YOUR CREW',
      action('navigate', '模型与连接', 'settings', '', 'data-view="settings"'),
    ) +
    `<section class="agent-intro reveal delay-1"><div><h2>从一个想法，到一部作品。</h2><p>13 类智能体角色 · 17 个执行配置 · ${state.api.isDemo ? '示例配置展示' : '已注册能力，不代表供应商在线'}</p></div><div class="agent-orbit"><span>${icon('script')}</span><span>${icon('people')}</span><span>${icon('film')}</span><span>${icon('sound')}</span></div></section><div class="filter-bar"><div class="filter-tabs">${['all', ...categories].map((c) => `<button class="filter-button ${(!state.agentFilter && c === 'all') || state.agentFilter === c ? 'active' : ''}" data-action="agent-filter" data-filter="${h(c)}">${c === 'all' ? '全部角色' : h(c)}</button>`).join('')}</div><span class="date-note">${filtered.length} 个创作角色</span></div><div class="agent-grid reveal delay-2">${filtered.map((a) => `<article class="agent-card"><div class="agent-card-top"><span class="agent-icon ${a.id === 'orchestrator' ? 'orange' : ''}">${icon(symbols[state.agents.indexOf(a)] || 'agents')}</span><span class="status-label gray">${state.api.isDemo ? '示例角色' : a.status === 'unregistered' ? '未注册' : a.enabled === false ? '未启用' : a.config_access === false ? '已注册' : '已配置'}</span></div><h3>${h(a.name)}</h3><p>${h(a.description)}</p><div class="agent-card-footer"><code>${h((a.agent_ids || [a.id]).join(' / '))}</code><button data-action="agent-detail" data-id="${h(a.id)}" aria-label="查看${h(a.name)}配置">${icon('arrow')}</button></div></article>`).join('')}</div>`
  );
}
export function reviewsView(state) {
  const reviews = state.workspace?.reviews || [];
  const visible = reviews.filter(
    (r) => !state.reviewFilter || state.reviewFilter === 'all' || r.status === state.reviewFilter,
  );
  return (
    heading(
      '好的作品，经得起推敲。',
      '检查产物、留下意见，再决定故事的下一步。',
      'THE HUMAN TOUCH',
      action('refresh', '刷新审核', 'refresh'),
    ) +
    `<div class="filter-bar"><div class="filter-tabs">${[
      ['all', '全部记录'],
      ['pending', '待审核'],
      ['approved', '已通过'],
      ['rejected', '已退回'],
    ]
      .map(
        ([id, name]) =>
          `<button class="filter-button ${(!state.reviewFilter && id === 'all') || state.reviewFilter === id ? 'active' : ''}" data-action="review-filter" data-filter="${id}">${name}</button>`,
      )
      .join(
        '',
      )}</div><span class="date-note">${h(state.workspace?.project?.name || '请选择项目')}</span></div>${visible.length ? `<div class="table-shell reveal"><table><thead><tr><th>审核内容</th><th>所属项目</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>${visible.map((r) => `<tr><td><div class="table-title">${h(r.title || stageTitle(r.stage))}</div><div class="table-meta">${h(r.stage)}</div></td><td>${h(state.workspace?.project.name)}</td><td>${status(r.status)}</td><td>${h(date(r.created_at))}</td><td>${action('review', r.status === 'pending' ? '查看审核' : '查看记录', 'arrow', 'small', `data-id="${h(r.id)}"`)}</td></tr>`).join('')}</tbody></table></div>` : empty('这里暂时没有审核内容', '每次重要的阶段产物完成后，你都可以在这里检查与确认。', '', 'review')}`
  );
}
export function assetsView(state) {
  const w = state.workspace;
  const title = heading(
    '项目素材',
    '按项目查找图像、视频、声音和文档。',
    'THE CREATIVE ARCHIVE',
    action('choose-project', '切换项目', 'folder'),
  );
  if (!w)
    return (
      title +
      empty(
        '先选择一个项目',
        '素材按项目收纳，选择后查看已有文件。',
        action('choose-project', '选择项目', 'folder'),
        'layers',
      )
    );
  const all = w.assets || [];
  const filter =
    { 'image/': 'image', 'video/': 'video', 'audio/': 'audio' }[state.assetFilter] ||
    state.assetFilter ||
    'all';
  const query = String(state.assetQuery || '').trim();
  const visible = filterAssets(all, { filter, query, sort: state.assetSort });
  const types = [
    ['all', '全部素材'],
    ['image', '图像'],
    ['video', '视频'],
    ['audio', '声音'],
    ['document', '文档'],
    ['other', '其他'],
  ];
  const context = `<section class="asset-project-context" aria-label="当前素材项目"><div><span>当前项目</span><strong id="asset-project-heading" tabindex="-1">${h(w.project.name)}</strong></div>${action('open-project', '进入项目', 'arrow', 'small', `id="asset-open-project" data-id="${h(w.project.id)}"`)}</section>`;
  const toolbar = `<div class="filter-bar library-toolbar asset-library-toolbar"><div class="filter-tabs" role="group" aria-label="素材类型">${types.map(([id, label]) => `<button class="filter-button ${filter === id ? 'active' : ''}" data-action="asset-filter" data-filter="${id}" aria-pressed="${filter === id}">${label}</button>`).join('')}</div><label class="filter-search">${icon('search')}<input id="asset-query" type="search" aria-label="搜索素材名称" aria-describedby="asset-results-status" placeholder="按文件名查找" value="${h(state.assetQuery || '')}"></label><label class="library-sort" for="asset-sort">排序<select id="asset-sort" aria-label="素材排序"><option value="default" ${state.assetSort !== 'name' ? 'selected' : ''}>默认顺序</option><option value="name" ${state.assetSort === 'name' ? 'selected' : ''}>文件名称</option></select></label></div>`;
  const summary = `<p id="asset-results-status" class="library-results-status" role="status" aria-live="polite">已载入 ${all.length} 份素材 · 显示 ${visible.length} 份${query ? ` · 搜索“${h(query)}”` : ''}</p>`;
  if (!all.length)
    return (
      title +
      context +
      toolbar +
      summary +
      `<section class="library-empty">${empty('这个项目还没有素材', '可进入项目继续创作，或切换项目查看已有文件。', action('open-project', '进入项目', 'arrow', '', `id="asset-empty-project" data-id="${h(w.project.id)}"`), 'layers')}</section>`
    );
  if (!visible.length)
    return (
      title +
      context +
      toolbar +
      summary +
      `<section class="library-empty">${empty('没有匹配的素材', query ? `已载入的素材中没有匹配“${query}”的文件，可调整关键词或清除筛选。` : `当前列表没有${filter === 'other' ? '其他文件' : types.find(([id]) => id === filter)?.[1] || '此类型'}，可清除筛选查看已载入素材。`, action('clear-asset-filters', '清除筛选', 'refresh'), 'search')}</section>`
    );
  return (
    title +
    context +
    toolbar +
    summary +
    `<div class="asset-grid">${visible
      .map((asset) => {
        const info = assetPresentation(asset);
        return `<button class="asset-tile" data-action="asset-detail" data-id="${h(asset.id)}" aria-label="查看素材：${h(info.name)}" title="${h(info.name)}"><div class="asset-thumb">${info.type === 'image' ? img(asset.image_url || asset.url, info.name) : icon(info.icon)}<span class="asset-type">${h(info.typeLabel)}</span></div><div class="asset-caption"><strong>${h(info.name)}</strong><small>${h([state.api.isDemo ? '示例素材' : info.typeLabel, info.sizeLabel, asset.created_at ? date(asset.created_at) : ''].filter(Boolean).join(' · '))}</small></div></button>`;
      })
      .join('')}</div>`
  );
}
/** 正文、结构化解析和小说原文各有边界；正文只通过版本化保存入口写入。 */
export function scriptWorkspace(state) {
  const w = state.workspace;
  const draft = state.scriptDraft || createScriptDraft(w.script, w.project.name);
  const structure = scriptStructure(w.script);
  const versions = w.scriptVersions || (w.script ? [w.script] : []);
  const assist = state.scriptAssist || { operation: 'polish', instruction: '' };
  const tasks = (w.tasks || []).filter((task) => task.type === 'script_assist').slice(0, 3);
  const ai = scriptAssistState({
    script: w.script,
    draft,
    tasks: w.tasks,
    submitting: state.scriptTaskSubmitting,
    isDemo: state.api.isDemo,
  });
  const save = scriptSaveState({ script: w.script, draft });
  const hasDownstream = !!(
    w.workflow ||
    w.characters?.length ||
    w.scenes?.length ||
    w.shots?.length ||
    w.assets?.length
  );
  return `<div class="script-workspace">
    <div class="script-editor-column">
      <section class="panel screenplay-editor" aria-labelledby="screenplay-heading">
        <div class="script-editor-heading"><div><h2 id="screenplay-heading">${state.scriptFocus ? '专注写作' : w.script ? '剧本正文' : '写下第一场戏'}</h2><p>${w.script ? `当前 V${h(w.script.version)} · ${h(scriptSourceName(w.script.workspace_meta?.source))}` : '直接创作，或导入一份已有剧本，无需先调用模型。'}${state.api.isDemo ? ' · DEMO 内存示例' : ''}</p></div><div class="script-editor-tools"><button type="button" class="button small script-focus-toggle" data-action="toggle-script-focus" aria-pressed="${!!state.scriptFocus}" aria-label="${state.scriptFocus ? '退出专注写作' : '专注写作'}" title="${state.scriptFocus ? '退出专注写作（Escape）' : '专注写作'}">${icon(state.scriptFocus ? 'unfocus' : 'focus')}<span>${state.scriptFocus ? '退出专注' : '专注写作'}</span></button>${action('import-script', '导入剧本', 'upload', 'small')}</div></div>
        <nav class="script-context-links" aria-label="剧本辅助面板"><button type="button" data-action="script-panel" data-panel="script-assistant" aria-controls="script-assistant">${icon('spark')}AI 辅助${icon('down')}</button><button type="button" data-action="script-panel" data-panel="script-history" aria-controls="script-history">${icon('clock')}版本历史 <span>${versions.length}</span>${icon('down')}</button></nav>
        ${draft.restored && draft.dirty ? '<div class="script-notice" role="status">已恢复本标签页尚未保存的草稿。保存后会创建新版本。</div>' : ''}
        ${draft.conflict ? `<div class="script-notice warning" role="alert" tabindex="-1" data-script-conflict><strong>当前版本已变化，草稿已保留。</strong><p>先查看最新稿，再决定是否另存当前草稿。</p>${action('script-version', '查看最新版本', 'script', 'small', `data-id="${h(w.script?.id)}"`)}${action('rebase-script-draft', '核对后另存草稿', 'edit', 'small')}</div>` : ''}
        ${draft.error && !draft.conflict ? `<div class="script-notice warning" role="alert" tabindex="-1" data-script-error>${h(draft.error)}</div>` : ''}
        ${w.script?.workspace_meta?.requires_reconfirmation && hasDownstream ? `<details class="script-notice script-reconfirmation"><summary>正文已更新，后续制作内容需重新核对</summary><p>已有工作流若基于旧稿，请先取消旧流程，再重新开始；不要沿用旧版本的审批续跑。人物、场景、分镜及审核需要重新核对。</p><a class="button text-link" href="/legacy/index.html" target="_blank" rel="noopener">管理现有流程 ${icon('arrow')}</a></details>` : ''}
        <form id="script-editor-form">
          <div class="form-field script-title-field"><label for="script-title">剧本标题</label><input id="script-title" name="title" maxlength="200" value="${h(draft.title)}" placeholder="为这个故事起个名字" required></div>
          <details class="script-metadata"><summary>一句话故事与梗概 <span>可选</span></summary><div class="form-field"><label for="script-logline">一句话故事</label><textarea id="script-logline" name="logline" rows="2" maxlength="10000" placeholder="谁遇到了什么，又作出了怎样的选择？">${h(draft.logline)}</textarea></div><div class="form-field"><label for="script-synopsis">故事梗概</label><textarea id="script-synopsis" name="synopsis" rows="3" maxlength="50000" placeholder="概括故事的起承转合">${h(draft.synopsis)}</textarea></div></details>
          <div class="form-field script-body-field"><label for="script-text">剧本正文 <small>场景、动作与对白</small></label><textarea id="script-text" name="script_text" class="screenplay-text" spellcheck="false" maxlength="200000" placeholder="第一场　内景·书店·夜&#10;&#10;雨落在橱窗上。灯还亮着。&#10;&#10;林简：今天，还不打烊。" required>${h(draft.script_text)}</textarea></div>
          <div class="script-editor-footer"><div><span id="script-char-count">${draft.script_text.length.toLocaleString()} 字符</span><span id="script-save-state" role="status" aria-live="polite">${h(save.message)}</span></div><div class="script-editor-actions"><button type="button" class="button small script-discard" data-action="discard-script-draft" aria-label="放弃草稿" title="放弃尚未保存的修改" ${draft.dirty && !draft.saving ? '' : 'disabled'}>${icon('close')}<span>放弃草稿</span></button><button type="submit" class="button primary" data-script-save ${save.disabled ? 'disabled' : ''}>${icon('check')}${h(save.label)}</button></div></div>
        </form>
      </section>
      <details class="panel script-structured"><summary>结构化解析数据 <span>只读</span></summary><p class="settings-tip">这里的章节、事件与台词结构供后续智能体使用，与上方正文分开管理。修改正文不会自动重建人物、场景或分镜；保存新版本后请重新核对后续产物。</p>${Object.keys(structure).length ? `<pre class="json-view">${h(JSON.stringify(structure, null, 2))}</pre>` : '<p class="settings-tip">当前版本尚无结构化解析数据。</p>'}</details>
      <section class="panel script-source"><div class="script-editor-heading"><div><h2>从小说原文开始</h2><p>适用于小说改编，与导入现有剧本分别管理。</p></div><span class="count-badge">${w.documents?.length || 0}</span></div><div class="script-source-actions">${action('upload-source', '上传小说原文', 'upload', 'small')}${action('import-sample', '导入示例小说', '', 'small')}${action('run-stage', w.script ? '从小说解析新版本' : '解析小说为剧本', 'spark', 'small', 'data-stage="analyze"')}</div><p class="settings-tip">小说解析会调用已配置模型，并创建新的剧本版本；有现稿时仍可重新解析，旧版本保留。</p>${w.chapters?.length ? `<details class="script-source-chapters"><summary>查看原文章节 · ${w.chapters.length} 章</summary>${w.chapters.map((chapter, i) => `<article class="chapter-item"><h3>${h(chapter.title || `第 ${chapter.index || chapter.chapter_index || i + 1} 章`)}</h3><p>${h(chapter.content || chapter.summary || '')}</p></article>`).join('')}</details>` : '<p class="settings-tip">还没有小说章节。你也可以直接在上方编写剧本。</p>'}</section>
    </div>
    <aside class="script-sidebar">
      <section class="panel script-assistant" id="script-assistant" aria-labelledby="script-assistant-heading"><div class="script-side-heading">${icon('spark')}<h2 id="script-assistant-heading" tabindex="-1">AI 写作辅助</h2><button type="button" class="button text-link script-return-editor" data-action="script-return-editor">返回正文${icon('arrow')}</button></div><p class="settings-tip">在已保存的正文上润色或续写，结果另存为新版本。续写保留原文，再追加新内容。</p>${assist.error ? `<div class="script-notice warning" role="alert">${h(assist.error)}</div>` : ''}<form id="script-assist-form"><div class="form-field"><label for="script-operation">创作方式</label><select id="script-operation" name="operation"><option value="polish" ${assist.operation === 'polish' ? 'selected' : ''}>润色现稿</option><option value="continue" ${assist.operation === 'continue' ? 'selected' : ''}>接着续写</option></select></div><div class="form-field"><label for="script-instruction">创作指令 <small>可选</small></label><textarea id="script-instruction" name="instruction" rows="4" maxlength="8000" placeholder="例如：对白更克制，保留雨夜的温暖氛围。">${h(assist.instruction)}</textarea></div><p class="script-ai-state" role="status">${h(ai.message)}</p><button type="submit" class="button primary full" ${ai.blocked ? 'disabled' : ''}>${icon('spark')}${state.api.isDemo ? '确认模拟操作' : '确认 AI 辅助'}</button></form>
        ${tasks.length ? `<div class="script-tasks" aria-live="polite">${tasks.map((task) => `<article class="script-task"><div>${status(task.status)}${task.result?.simulated ? '<span class="tag">模拟</span>' : ''}</div><p>${h(task.message || '剧本辅助任务')}</p>${task.error ? `<p class="script-task-error">${h(typeof task.error === 'string' ? task.error : JSON.stringify(task.error))}</p>` : ''}${task.result?.script_id ? `<p>已生成 V${h(task.result.version)}，需要重新核对后续产物。</p>${action('script-version', '查看结果', 'arrow', 'text-link', `data-id="${h(task.result.script_id)}"`)}` : ''}${action('task-detail', '任务日志', '', 'text-link', `data-id="${h(task.id)}"`)}</article>`).join('')}</div>` : ''}
      </section>
      <section class="panel script-history" id="script-history" aria-labelledby="script-history-heading"><div class="script-editor-heading"><h2 id="script-history-heading" tabindex="-1">版本历史</h2><span class="count-badge">${versions.length}</span><button type="button" class="button text-link script-return-editor" data-action="script-return-editor">返回正文${icon('arrow')}</button></div><p class="settings-tip">每次保存、导入和恢复都新建一版。</p>${versions.length ? `<ol class="script-version-list">${versions.map((version) => `<li><button type="button" data-action="script-version" data-id="${h(version.id)}"><span class="version-number">V${h(version.version)}</span><span><strong>${h(version.title || '未命名剧本')}</strong><small>${h(scriptSourceName(version.workspace_meta?.source))} · ${h(date(version.created_at))}</small></span>${version.id === w.script?.id ? '<span class="tag">当前</span>' : icon('arrow')}</button></li>`).join('')}</ol>` : '<p class="settings-tip">保存第一版后，这里会保留修改记录。</p>'}</section>
    </aside>
  </div>`;
}

const directingText = (value, fallback = '') =>
  typeof value === 'string' && value.trim() ? value.trim() : fallback;
const directingList = (value) =>
  Array.isArray(value) ? value.filter((item) => typeof item === 'string' && item.trim()) : [];
const directingDate = (value) =>
  value && Number.isFinite(new Date(value).getTime()) ? date(value) : '时间未记录';

/** 历史与当前方案复用同一正文投影；来源状态由后端判定，不能从当前剧本猜测。 */
export function directingPlanBody(plan) {
  const content = plan?.content || {};
  const source = plan?.source_script || content.source_script || null;
  const sourceStatus = plan?.source_status || 'unknown';
  const strategy = content.shot_strategy || {};
  const colors = directingList(content.color_palette);
  const continuity = directingList(content.continuity_rules);
  const scenes = directingList(content.scenes_order);
  const request = content.generation_request;
  const requestRecorded = !!request && typeof request === 'object' && !Array.isArray(request);
  const total = Number(strategy.total_shots);
  const average = Number(strategy.avg_duration_seconds);
  const sourceMessage =
    sourceStatus === 'stale'
      ? '剧本已更新，这份方案基于旧稿。请重新生成导演方案，再继续制作新的分镜。'
      : sourceStatus === 'current'
        ? '方案对应当前已保存剧本。导演方案与分镜一起进入第二轮审核。'
        : '这份方案没有可验证的剧本来源，继续制作新的分镜前请先核对或重新生成。';
  const sourceTitle = source
    ? `基于剧本 V${source.version ?? '—'}${source.title ? ` · ${source.title}` : ''}`
    : '剧本来源未记录';
  const list = (items, emptyText, ordered = false) =>
    items.length
      ? `<${ordered ? 'ol' : 'ul'}>${items.map((item) => `<li>${h(item)}</li>`).join('')}</${ordered ? 'ol' : 'ul'}>`
      : `<p class="settings-tip">${h(emptyText)}</p>`;
  return `<div class="directing-plan-body">
    <div class="directing-source"><strong>${h(sourceTitle)}</strong><span class="tag">${sourceStatus === 'current' ? '当前基线' : sourceStatus === 'stale' ? '基线已变化' : '来源待核对'}</span></div>
    <p class="directing-source-note ${sourceStatus === 'current' ? '' : 'warning'}">${h(sourceMessage)}</p>
    <section class="directing-section directing-statement"><h3>视觉风格</h3><p>${h(directingText(content.visual_style, '尚未提供视觉风格。'))}</p></section>
    <div class="directing-sections-grid">
      <section class="directing-section"><h3>色彩与光线</h3>${colors.length ? `<ul class="directing-palette">${colors.map((color) => `<li>${/^#(?:[a-f\d]{3}|[a-f\d]{6})$/i.test(color) ? `<span class="directing-color" style="background-color:${color}" aria-hidden="true"></span>` : ''}<span>${h(color)}</span></li>`).join('')}</ul>` : '<p class="settings-tip">尚未提供配色。</p>'}<p>${h(directingText(content.lighting_style, '尚未提供光线规划。'))}</p></section>
      <section class="directing-section"><h3>镜头语言</h3><p>${h(directingText(content.camera_language, '尚未提供镜头语言。'))}</p></section>
      <section class="directing-section"><h3>叙事节奏</h3><p>${h(directingText(content.pacing, '尚未提供节奏规划。'))}</p></section>
      <section class="directing-section"><h3>叙事弧线</h3><p>${h(directingText(content.narrative_arc, '尚未提供叙事弧线。'))}</p></section>
    </div>
    <section class="directing-section"><h3>镜头策略</h3><dl class="directing-metrics"><div><dt>目标镜头</dt><dd>${Number.isFinite(total) && total > 0 ? `${h(total)} 个` : '未提供'}</dd></div><div><dt>平均时长</dt><dd>${Number.isFinite(average) && average > 0 ? `${h(average)} 秒` : '未提供'}</dd></div></dl><p>${h(directingText(strategy.coverage_notes, '尚未提供覆盖策略。'))}</p>${directingText(strategy.pacing_notes) ? `<p>${h(strategy.pacing_notes)}</p>` : ''}</section>
    <div class="directing-sections-grid"><section class="directing-section"><h3>连续性约束</h3>${list(continuity, '尚未记录连续性约束。')}</section><section class="directing-section"><h3>场景顺序</h3>${list(scenes, '尚未提供场景顺序。', true)}</section></div>
    ${directingText(content.notes) ? `<section class="directing-section"><h3>导演备注</h3><p>${h(content.notes)}</p></section>` : ''}
    <details class="directing-provenance"><summary>创作要求与生成记录</summary><dl><div><dt>创作要求</dt><dd>${h(requestRecorded ? directingText(request.instruction, '未填写额外创作要求。') : '生成时的创作要求未记录。')}</dd></div>${requestRecorded && request.shots_target != null ? `<div><dt>请求镜头数</dt><dd>${h(request.shots_target)}</dd></div>` : ''}<div><dt>生成模型</dt><dd>${h(directingText(plan?.model_id, '未记录'))}</dd></div>${plan?.prompt_version ? `<div><dt>提示词版本</dt><dd>${h(plan.prompt_version)}</dd></div>` : ''}${plan?.config_version ? `<div><dt>配置版本</dt><dd>${h(plan.config_version)}</dd></div>` : ''}</dl></details>
  </div>`;
}

/** 导演页只展示已有数据；提交、历史读取与轮询由 app.js 负责。 */
export function directingWorkspace(state) {
  const w = state.workspace;
  const draft = state.directingDraft || {
    instruction: '',
    shots_target: 6,
    error: '',
    submitting: false,
  };
  const form = directingFormState({
    workspace: w,
    draft,
    scriptDraft: state.scriptDraft,
    isDemo: state.api.isDemo,
  });
  const plan = w.directing;
  const versions = w.directing_versions?.length ? w.directing_versions : plan ? [plan] : [];
  const tasks = (w.tasks || []).filter((task) => task.type === 'directing').slice(0, 4);
  const planStatus = plan?.approved ? '已随分镜确认' : '待分镜与审核';
  const links = `<nav class="production-context-links" aria-label="导演辅助面板">${action('production-panel', '调整创作要求', 'edit', 'small', 'data-panel="directing-brief"')}${action('production-panel', '方案历史', 'clock', 'small', 'data-panel="directing-history"')}</nav>`;
  const back = action(
    'production-return',
    '返回方案',
    'arrow',
    'text-link production-return',
    'data-panel="directing-plan"',
  );
  return `<div class="directing-workspace ${plan ? 'has-plan' : 'is-empty'}">
    <div class="directing-main"><section class="panel directing-plan" id="directing-plan" aria-labelledby="directing-plan-heading"><div class="directing-plan-heading"><div><h2 id="directing-plan-heading" tabindex="-1">导演方案</h2><p>${plan ? `当前 V${h(plan.version)} · ${planStatus}` : '从故事出发，确定影像、节奏与连续性。'}</p></div>${state.api.isDemo ? '<span class="tag">DEMO 静态示例</span>' : plan ? `<span class="tag">${planStatus}</span>` : ''}</div>${links}${state.api.isDemo ? '<p class="directing-source-note">当前方案是静态示例；模拟操作仅记录任务，不作为真实生成或审核依据。</p>' : ''}${plan ? directingPlanBody(plan) : empty('为故事确定影像方向', w.script ? '填写创作要求，生成第一版导演方案。已有剧本和历史版本会保留。' : '先保存或导入剧本，再制定视觉风格与镜头策略。', !w.script ? action('tab', '前往剧本', 'script', '', 'data-tab="story"') : '', 'film')}${plan ? `<div class="directing-next-note"><p>导演方案随分镜进入模块四的第二轮审核，当前页不单独批准。</p>${action('tab', '前往分镜', 'arrow', '', 'data-tab="storyboard"')}</div>` : ''}</section></div>
    <aside class="directing-sidebar">
      <section class="panel directing-brief" id="directing-brief" aria-labelledby="directing-brief-heading"><div class="production-panel-heading"><h2 id="directing-brief-heading" tabindex="-1">创作要求</h2>${back}</div><p class="settings-tip">基于已保存剧本制定方案，每次生成另存新版本。</p>${draft.error ? `<div class="script-notice warning" role="alert" tabindex="-1" data-directing-error>${h(typeof draft.error === 'string' ? draft.error : JSON.stringify(draft.error))}</div>` : ''}<form id="directing-form"><div class="form-field"><label for="directing-shots-target">目标镜头数</label><input id="directing-shots-target" type="number" name="shots_target" min="1" max="120" step="1" value="${h(draft.shots_target ?? 6)}" aria-describedby="directing-shots-help" required><p class="settings-tip" id="directing-shots-help">1–120 个镜头，用于确定方案规模。</p></div><div class="form-field"><label for="directing-instruction">导演创作要求 <small>可选</small></label><textarea id="directing-instruction" name="instruction" rows="5" maxlength="8000" placeholder="例如：保留雨夜的冷暖对照，对白克制，以静态机位和近景推进情绪。">${h(draft.instruction || '')}</textarea></div><p id="directing-form-state" role="status" aria-live="polite">${h(form.message)}</p><button type="submit" class="button primary full" data-directing-submit ${form.blocked ? 'disabled' : ''}>${icon('spark')}${h(form.label)}</button>${form.missingScript || form.hasUnsavedScript ? action('tab', '返回剧本保存', 'arrow', 'text-link', 'data-tab="story"') : ''}</form></section>
      <section class="panel directing-history" id="directing-history" aria-labelledby="directing-history-heading"><div class="production-panel-heading"><h2 id="directing-history-heading" tabindex="-1">方案历史 <span class="count-badge">${versions.length}</span></h2>${back}</div><p class="settings-tip">每次生成保留旧方案，历史版本只读查看。</p>${versions.length ? `<ol class="script-version-list">${versions.map((version) => `<li><button type="button" data-action="directing-version" data-id="${h(version.id)}" aria-label="查看导演方案 V${h(version.version)}"><span class="version-number">V${h(version.version)}</span><span><strong>${version.approved ? '已随分镜确认' : '导演方案草稿'}</strong><small>${h(directingDate(version.created_at))}</small></span>${version.id === plan?.id ? '<span class="tag">当前</span>' : icon('arrow')}</button></li>`).join('')}</ol>` : '<p class="settings-tip">生成第一版后，这里会保留创作记录。</p>'}</section>
      <section class="panel directing-tasks" aria-labelledby="directing-tasks-heading"><h2 id="directing-tasks-heading">任务记录</h2>${tasks.length ? `<div aria-live="polite">${tasks.map((task) => `<article class="directing-task"><div>${status(task.status)}${task.result?.simulated ? '<span class="tag">模拟任务</span>' : ''}</div><p>${h(task.message || '导演方案任务')}</p>${task.result?.simulated ? '<p class="settings-tip">本次仅记录模拟任务，未生成真实方案。</p>' : ''}${task.error ? `<p class="script-task-error">${h(planningTaskError(task.error))}</p>` : ''}<div>${task.result?.plan_id && !task.result?.simulated ? action('directing-version', '查看方案', 'arrow', 'text-link', `data-id="${h(task.result.plan_id)}"`) : ''}${action('task-detail', '任务日志', '', 'text-link', `data-id="${h(task.id)}"`)}</div></article>`).join('')}</div>` : '<p class="settings-tip">提交后在这里查看执行状态与结果。</p>'}</section>
    </aside>
  </div>`;
}

const STORYBOARD_SHOT_TYPES = {
  extreme_wide_shot: '远景',
  wide_shot: '全景',
  wide: '全景',
  long_shot: '全景',
  medium_shot: '中景',
  medium: '中景',
  medium_close_up: '中近景',
  close_up: '特写',
  close: '特写',
  extreme_close_up: '大特写',
  over_the_shoulder: '越肩镜头',
  two_shot: '双人镜头',
  pov: '主观视角',
};
const STORYBOARD_MOVEMENTS = {
  static: '固定机位',
  locked_off: '固定机位',
  pan: '摇镜',
  tilt: '俯仰',
  dolly: '轨道移动',
  dolly_in: '推近',
  push_in: '推近',
  slow_push_in: '缓慢推近',
  dolly_out: '拉远',
  pull_out: '拉远',
  tracking: '跟拍',
  handheld: '手持',
  crane: '升降',
  zoom: '变焦',
};
const STORYBOARD_ANGLES = {
  eye_level: '平视',
  high_angle: '俯拍',
  low_angle: '仰拍',
  overhead: '顶视',
  dutch_angle: '倾斜视角',
};
const storyboardTerm = (value, names, fallback) => {
  const raw = directingText(value);
  return raw ? (Object.hasOwn(names, raw) ? names[raw] : raw) : fallback;
};
const storyboardDuration = (value) => {
  const duration = Number(value);
  return value != null && Number.isFinite(duration) && duration > 0
    ? `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(duration)} 秒`
    : '时长待补充';
};

function storyboardShotBody(shot, index, { scenes, readOnly }) {
  const id = shot.id || shot.shot_id || '';
  const orderValue = Number(shot.order ?? shot.order_index);
  const order = String(
    Number.isInteger(orderValue) && orderValue > 0 ? orderValue : index + 1,
  ).padStart(2, '0');
  const scene = scenes.find((item) => item.id === shot.scene_id);
  const sceneName = directingText(scene?.name, directingText(shot.scene_name, '场景未关联'));
  const camera = shot.camera && typeof shot.camera === 'object' ? shot.camera : {};
  const shotType = storyboardTerm(
    camera.shot_type || camera.shot_size || camera.type,
    STORYBOARD_SHOT_TYPES,
    '景别未指定',
  );
  const movement = storyboardTerm(camera.movement, STORYBOARD_MOVEMENTS, '运镜未指定');
  const angle = storyboardTerm(camera.angle, STORYBOARD_ANGLES, '角度未指定');
  const people = Array.isArray(shot.characters)
    ? shot.characters.filter(
        (item) => typeof item === 'string' || (item && typeof item === 'object'),
      )
    : [];
  const lines = Array.isArray(shot.dialogue)
    ? shot.dialogue.filter((item) => typeof item === 'string' || (item && typeof item === 'object'))
    : [];
  const image = mediaUrl(shot.image_url || shot.thumbnail_url);
  return `<article class="storyboard-shot shot-card" data-shot-id="${h(id)}"><div class="storyboard-shot-heading"><div><span class="storyboard-shot-number">SHOT ${h(order)}</span><h3>${h(sceneName)}</h3></div><span class="status-label ${shot.approved ? '' : 'gray'}">${shot.approved ? '已确认' : '待确认'}</span>${!image ? `<span class="storyboard-shot-symbol" aria-hidden="true">${icon('film')}</span>` : ''}</div>${image ? img(image, `镜头 ${order} 参考图`, 'storyboard-shot-preview') : ''}<div class="shot-content"><div class="storyboard-shot-facts"><span>${h(storyboardDuration(shot.duration_seconds))}</span><span>${h(shotType)}</span><span>${h(movement)}</span><span>${h(angle)}</span>${directingText(camera.lens) ? `<span>${h(camera.lens)}</span>` : ''}</div><p class="storyboard-shot-description">${h(directingText(shot.description, '尚未填写画面描述。'))}</p><dl class="storyboard-shot-action"><dt>动作</dt><dd>${h(directingText(shot.action, '尚未记录动作。'))}</dd></dl><div class="storyboard-shot-people"><h4>出场人物</h4>${people.length ? `<ul>${people.map((person) => (typeof person === 'string' ? `<li>${h(person)}</li>` : `<li><strong>${h(directingText(person.character_name || person.name, '未命名人物'))}</strong>${person.action || person.emotion ? `<span>${h([person.action, person.emotion].filter(Boolean).join(' · '))}</span>` : ''}</li>`)).join('')}</ul>` : '<p class="settings-tip">尚未关联人物。</p>'}</div><div class="storyboard-shot-dialogue"><h4>台词</h4>${lines.length ? lines.map((line) => (typeof line === 'string' ? `<blockquote><p>${h(line)}</p></blockquote>` : `<blockquote><span>${h(directingText(line.character_name, '对白'))}${directingText(line.emotion) ? ` · ${h(line.emotion)}` : ''}</span><p>${h(directingText(line.text, '台词尚未填写。'))}</p></blockquote>`)).join('') : '<p class="settings-tip">此镜头暂无对白。</p>'}</div><details class="storyboard-shot-prompt" id="${readOnly ? 'history-' : ''}shot-prompt-${h(id || order)}"><summary>生成提示词</summary><p>${h(directingText(shot.visual_prompt, '尚未填写画面提示词。'))}</p>${directingText(shot.negative_prompt) ? `<h4>排除内容</h4><p>${h(shot.negative_prompt)}</p>` : ''}</details>${!readOnly && id ? `<div class="storyboard-shot-actions">${action('edit-shot', '编辑镜头', 'edit', 'small', `data-id="${h(id)}"`)}${action('shot-detail', '镜头详情', 'arrow', 'text-link', `data-id="${h(id)}"`)}</div>` : ''}</div></article>`;
}

/** 当前镜头只读详情与历史共用镜头结构，不带历史标签或编辑入口。 */
export function storyboardShotDetails(shot, { scenes = [] } = {}) {
  return shot
    ? storyboardShotBody(shot, 0, { scenes, readOnly: true })
    : '<p class="settings-tip">没有找到可查看的镜头。</p>';
}

/** 历史版本只读复用完整镜头结构，不把当前工作区的编辑入口带入历史弹窗。 */
export function storyboardVersionBody(
  board,
  { scenes = [], readOnly = true, history = true } = {},
) {
  const shots = Array.isArray(board?.shots) ? board.shots : [];
  const source = board?.source_script;
  const sourceStatus = board?.source_status || 'unknown';
  const sourceLabel = source
    ? `基于剧本 V${source.version ?? '—'}${source.title ? ` · ${source.title}` : ''}`
    : '剧本来源未记录';
  const sourceMessage =
    sourceStatus === 'current'
      ? readOnly
        ? history
          ? '该版本的剧本与导演来源一致；历史版本只读查看，不在此提审。'
          : '当前分镜与导演来源一致，可在只读预览中核对内容。'
        : board?.approved
          ? '本版导演与分镜已完成第二轮确认，后续生产由你单独发起。'
          : '分镜的剧本与导演来源一致，核对后可提交第二轮审核。'
      : sourceStatus === 'stale'
        ? '剧本或导演方案已更新，这份分镜基于旧来源。请重新生成后再提审。'
        : '这份分镜没有可验证的来源，提审前请先核对并重新生成。';
  const durations = shots.map((shot) => Number(shot.duration_seconds));
  const totalKnown =
    shots.length > 0 && durations.every((value) => Number.isFinite(value) && value > 0);
  const total = totalKnown ? durations.reduce((sum, value) => sum + value, 0) : null;
  return `<div class="storyboard-version-body"><div class="storyboard-source"><strong>${h(sourceLabel)}</strong><span class="tag">${sourceStatus === 'current' ? '来源一致' : sourceStatus === 'stale' ? '来源已变化' : '来源待核对'}</span>${board?.directing_plan_id ? action('directing-version', '查看关联导演', 'film', 'text-link', `data-id="${h(board.directing_plan_id)}"`) : ''}</div><p class="storyboard-source-note ${sourceStatus === 'current' ? '' : 'warning'}">${h(sourceMessage)}</p><div class="storyboard-version-meta"><span>${shots.length} 个镜头</span><span>${totalKnown ? `预计总时长 ${h(storyboardDuration(total))}` : '部分镜头时长待补充'}</span>${readOnly ? `<span class="tag">${history ? '历史版本 · 只读' : '审核预览 · 只读'}</span>` : ''}</div>${directingText(board?.notes) ? `<p class="storyboard-notes">${h(board.notes)}</p>` : ''}${shots.length ? `<div class="storyboard-shot-list">${shots.map((shot, index) => storyboardShotBody(shot, index, { scenes, readOnly })).join('')}</div>` : '<p class="settings-tip">这份分镜尚无镜头。</p>'}<details class="storyboard-provenance"><summary>生成记录</summary><dl><div><dt>生成模型</dt><dd>${h(directingText(board?.model_id, '未记录'))}</dd></div>${board?.prompt_version ? `<div><dt>提示词版本</dt><dd>${h(board.prompt_version)}</dd></div>` : ''}${board?.config_version ? `<div><dt>配置版本</dt><dd>${h(board.config_version)}</dd></div>` : ''}</dl></details></div>`;
}

/** 第二关只面向服务端绑定的分镜快照；旧 pending 只提供查看与退回入口。 */
function storyboardReviewPanel(state, draft) {
  const w = state.workspace;
  const board = w.storyboard;
  const reviewState = storyboardReviewState({
    workspace: w,
    draft,
    scriptDraft: state.scriptDraft,
    isDemo: state.api.isDemo,
  });
  const review = reviewState.review;
  const snapshot = review?.target_snapshot;
  const hasSnapshot = snapshot && typeof snapshot === 'object' && !Array.isArray(snapshot);
  const shotFingerprints =
    hasSnapshot &&
    snapshot.shot_fingerprints &&
    typeof snapshot.shot_fingerprints === 'object' &&
    !Array.isArray(snapshot.shot_fingerprints)
      ? snapshot.shot_fingerprints
      : null;
  const label = {
    missing: '等待分镜',
    ready: '准备提审',
    pending: '等待审核',
    'stale-pending': '旧审核待处理',
    approved: '已确认',
    'approved-stale': '已有确认记录',
    rejected: '已退回',
    edited: '编辑后待重审',
    submitting: '正在提交',
    blocked: '需要先核对来源',
  }[reviewState.state];
  return `<section class="panel storyboard-review" id="storyboard-review" data-review-state="${reviewState.state}" aria-labelledby="storyboard-review-heading"><div class="production-panel-heading"><h2 id="storyboard-review-heading" tabindex="-1">第二轮审核</h2>${action('production-return', '返回分镜', 'arrow', 'text-link production-return', 'data-panel="storyboard-overview"')}</div>${state.api.isDemo ? '<span class="tag">DEMO 模拟审核</span>' : ''}<p class="storyboard-review-status">${h(label)}</p><p class="${reviewState.state === 'stale-pending' || reviewState.state === 'blocked' || reviewState.state === 'approved-stale' ? 'storyboard-source-note warning' : 'settings-tip'}">${h(reviewState.message)}</p>${draft.reviewError ? `<div class="script-notice warning" data-storyboard-review-error role="alert" tabindex="-1">${h(typeof draft.reviewError === 'string' ? draft.reviewError : JSON.stringify(draft.reviewError))}</div>` : ''}${hasSnapshot ? `<dl class="storyboard-review-snapshot"><div><dt>提审分镜</dt><dd>${snapshot.storyboard_version != null ? `V${h(snapshot.storyboard_version)}` : '版本未记录'}</dd></div><div><dt>基于剧本</dt><dd>${snapshot.source_script?.version != null ? `V${h(snapshot.source_script.version)}` : '版本未记录'}</dd></div><div><dt>快照镜头</dt><dd>${shotFingerprints ? `${Object.keys(shotFingerprints).length} 个` : '未记录'}</dd></div></dl>` : ''}${review?.status === 'rejected' && directingText(review.comment) ? `<blockquote class="storyboard-review-comment">${h(review.comment)}</blockquote>` : ''}<div class="storyboard-review-actions">${review ? action('review', reviewState.reviewActionLabel, 'review', reviewState.pendingCurrent ? 'primary full' : 'small', `data-id="${h(review.id)}"`) : ''}${board && !reviewState.pending && !reviewState.confirmed ? action('request-storyboard-review', reviewState.requestLabel, 'check', 'primary full', `data-id="${h(board.id)}" ${reviewState.canRequest ? '' : 'disabled'}`) : ''}</div></section>`;
}

/** 分镜页的结构化阅读、生成与二审分区；表单派发和编辑由控制器完成。 */
export function storyboardWorkspace(state) {
  const w = state.workspace;
  const draft = state.storyboardDraft || {
    refine_prompts: false,
    error: '',
    submitting: false,
    reviewError: '',
    reviewSubmitting: false,
  };
  const form = storyboardFormState({
    workspace: w,
    draft,
    scriptDraft: state.scriptDraft,
    isDemo: state.api.isDemo,
  });
  const board = w.storyboard;
  const shots = Array.isArray(w.shots) ? w.shots : board?.shots || [];
  const versions = w.storyboard_versions?.length ? w.storyboard_versions : board ? [board] : [];
  const tasks = (w.tasks || []).filter((task) => task.type === 'storyboard').slice(0, 4);
  const links = `<nav class="production-context-links" aria-label="分镜辅助面板">${action('production-panel', '生成要求', 'settings', 'small', 'data-panel="storyboard-brief"')}${action('production-panel', '第二轮审核', 'review', 'small', 'data-panel="storyboard-review"')}${action('production-panel', '版本历史', 'clock', 'small', 'data-panel="storyboard-history"')}</nav>`;
  const back = action(
    'production-return',
    '返回分镜',
    'arrow',
    'text-link production-return',
    'data-panel="storyboard-overview"',
  );
  return `<div class="storyboard-workspace ${board ? 'has-plan' : 'is-empty'}"><div class="storyboard-main"><section class="panel storyboard-overview" id="storyboard-overview" aria-labelledby="storyboard-overview-heading"><div class="production-panel-heading"><div><h2 id="storyboard-overview-heading" tabindex="-1">${h(directingText(board?.title, '分镜与镜头'))}</h2><p class="settings-tip">${board ? `当前 V${h(board.version)} · ${board.approved ? '已确认' : '待核对与审核'}` : '将导演方案转为可编辑的镜头，再共同确认。'}</p></div>${state.api.isDemo ? '<span class="tag">DEMO 静态示例</span>' : ''}</div>${links}${state.api.isDemo ? '<p class="settings-tip">当前镜头为静态示例；模拟操作不会调用模型或生成真实分镜。</p>' : ''}${board ? storyboardVersionBody({ ...board, shots }, { scenes: w.scenes || [], readOnly: false }) : empty('把故事拆解为镜头', form.missingScript ? '先保存剧本，再准备导演与分镜。' : '先完成来源可验证的导演方案，再生成第一版分镜。', action('tab', form.missingScript ? '前往剧本' : '前往导演方案', form.missingScript ? 'script' : 'film', '', `data-tab="${form.missingScript ? 'story' : 'directing'}"`), 'film')}</section></div><aside class="storyboard-sidebar"><section class="panel storyboard-brief" id="storyboard-brief" aria-labelledby="storyboard-brief-heading"><div class="production-panel-heading"><h2 id="storyboard-brief-heading" tabindex="-1">生成要求</h2>${back}</div><p class="settings-tip">生成新版本会保留旧分镜，核对后再提交审核。</p>${draft.error ? `<div class="script-notice warning" data-storyboard-error role="alert" tabindex="-1">${h(typeof draft.error === 'string' ? draft.error : JSON.stringify(draft.error))}</div>` : ''}<form id="storyboard-form"><label class="storyboard-refine-option" for="storyboard-refine-prompts"><input id="storyboard-refine-prompts" type="checkbox" name="refine_prompts" ${draft.refine_prompts === true ? 'checked' : ''}><span><strong>额外精化提示词</strong><small>逐镜追加模型调用；基础提示词已随分镜生成。</small></span></label><p id="storyboard-form-state" role="status" aria-live="polite">${h(form.message)}</p><button type="submit" class="button primary full" data-storyboard-submit ${form.blocked ? 'disabled' : ''}>${icon('spark')}${h(form.label)}</button>${form.missingDirector || form.unverifiedDirector ? action('tab', '核对导演方案', 'film', 'text-link', 'data-tab="directing"') : ''}${form.missingScript || form.hasUnsavedScript ? action('tab', '返回剧本保存', 'script', 'text-link', 'data-tab="story"') : ''}</form></section>${storyboardReviewPanel(state, draft)}<section class="panel storyboard-history" id="storyboard-history" aria-labelledby="storyboard-history-heading"><div class="production-panel-heading"><h2 id="storyboard-history-heading" tabindex="-1">版本历史 <span class="count-badge">${versions.length}</span></h2>${back}</div><p class="settings-tip">历史版本只读查看，编辑仅作用于当前镜头。</p>${versions.length ? `<ol class="script-version-list">${versions.map((version) => `<li><button type="button" data-action="storyboard-version" data-id="${h(version.id)}" aria-label="查看分镜 V${h(version.version)}"><span class="version-number">V${h(version.version)}</span><span><strong>${h(directingText(version.title, '分镜版本'))}</strong><small>${h(directingDate(version.created_at))} · ${version.approved ? '已确认' : '草稿'}</small></span>${version.id === board?.id ? '<span class="tag">当前</span>' : icon('arrow')}</button></li>`).join('')}</ol>` : '<p class="settings-tip">生成第一版后，这里会保留历史。</p>'}</section><section class="panel storyboard-tasks" aria-labelledby="storyboard-tasks-heading"><h2 id="storyboard-tasks-heading">任务记录</h2>${tasks.length ? tasks.map((task) => `<article class="storyboard-task"><div>${status(task.status)}${task.result?.simulated ? '<span class="tag">模拟任务</span>' : ''}</div><p>${h(task.message || '分镜任务')}</p>${task.result?.simulated ? '<p class="settings-tip">本次仅记录模拟任务，未生成真实分镜。</p>' : ''}${task.error ? `<p class="script-task-error">${h(planningTaskError(task.error))}</p>` : ''}<div>${task.result?.storyboard_id && !task.result?.simulated ? action('storyboard-version', '查看分镜', 'arrow', 'text-link', `data-id="${h(task.result.storyboard_id)}"`) : ''}${action('task-detail', '任务日志', '', 'text-link', `data-id="${h(task.id)}"`)}</div></article>`).join('') : '<p class="settings-tip">提交后在这里查看执行状态与结果。</p>'}</section></aside></div>`;
}

export function workbench(state) {
  const w = state.workspace;
  if (!w)
    return empty(
      '先为故事准备一个片场',
      '创建或选择项目后，就可以开始制作。',
      action('new-project', '新建项目', 'plus', 'primary'),
    );
  const tab = state.tab || 'story';
  const productionNavigation =
    tab === 'directing'
      ? action('tab', '分镜与审核', 'arrow', 'primary', 'data-tab="storyboard"')
      : tab === 'storyboard'
        ? action('tab', '导演方案', 'film', '', 'data-tab="directing"')
        : action('start-workflow', '继续制作', 'play', 'primary');
  const banner = `<div class="workbench-banner reveal">${img(cover(w.project) || w.project.cover_url, w.project.name, 'workbench-poster')}<div><div class="eyebrow">PROJECT WORKSPACE ${w.demo ? ' / DEMO' : ''}</div><h1 aria-label="${h(w.project.name)}" title="${h(w.project.name)}">${h(w.project.name)}</h1><p class="subtitle">${h(w.project.genre || '短片创作')} · ${h(w.project.aspect_ratio)} · ${status(w.project.status)}</p></div><div class="heading-actions">${action('choose-project', '切换项目', 'folder')}${productionNavigation}</div></div><nav class="project-tabs" aria-label="项目制作步骤">${TABS.map(([id, label, symbol]) => `<button class="project-tab ${tab === id ? 'active' : ''}" data-action="tab" data-tab="${id}" aria-current="${tab === id ? 'page' : 'false'}">${icon(symbol)}${label}</button>`).join('')}</nav>`;
  let content = '';
  if (tab === 'story') content = scriptWorkspace(state);
  else if (tab === 'directing') content = directingWorkspace(state);
  else if (tab === 'characters' || tab === 'scenes') {
    const isCharacter = tab === 'characters',
      items = isCharacter ? w.characters : w.scenes;
    content = `${section(isCharacter ? '人物设定' : '场景设定', '', action('start-workflow', '继续设定流程', 'spark'))}${
      items?.length
        ? `<div class="${isCharacter ? 'character-grid' : 'scene-grid'}">${items
            .map(
              (item, i) =>
                `<article class="character-card"><div class="character-portrait">${img(item.image_url, item.name)}<span class="portrait-number">${isCharacter ? 'CHARACTER' : 'LOCATION'} / ${String(i + 1).padStart(2, '0')}</span></div><div class="character-card-body"><div class="character-card-title"><h3>${h(item.name)}</h3>${status(item.status || (item.approved_version ? 'approved' : 'draft'))}</div><p>${h(item.summary || item.profile?.description || '尚未填写描述')}</p><div class="tags">${(isCharacter
                  ? item.appearance_keywords || item.profile?.visual_keywords || []
                  : [item.profile?.time_of_day, item.profile?.mood]
                )
                  .filter(Boolean)
                  .slice(0, 3)
                  .map((t) => `<span class="tag">${h(t)}</span>`)
                  .join(
                    '',
                  )}</div></div><button class="card-action" data-action="entity-detail" data-kind="${tab}" data-id="${h(item.id)}">查看完整档案 ${icon('arrow')}</button></article>`,
            )
            .join('')}</div>`
        : empty(
            isCharacter ? '人物尚未登场' : '场景尚未展开',
            '完成剧本后，按流程提取并完善设定。',
            '',
            'people',
          )
    }`;
  } else if (tab === 'storyboard') content = storyboardWorkspace(state);
  else if (tab === 'reviews') content = reviewsView(state);
  else if (tab === 'models')
    content = `<div class="panel">${section('智能体执行配置', 'MODEL CONFIGURATION', action('navigate', '连接设置', 'settings', '', 'data-view="settings"'))}<p class="settings-tip">点击角色查看执行配置。凭据始终保留在后端环境中。</p><div class="agent-grid" style="margin-top:20px">${state.agents.map((a) => `<article class="agent-card"><span class="agent-icon">${icon('agents')}</span><h3>${h(a.name)}</h3><p>${h(a.model_id || '从后端配置读取')}</p>${action('agent-detail', '查看配置', 'arrow', 'text-link', `data-id="${h(a.id)}"`)}</article>`).join('')}</div></div>`;
  else {
    const definitions = {
      directing: [
        '导演规划',
        '让影像风格、情绪与节奏形成一致的创作方向。',
        'directing',
        'film',
        w.directing || null,
      ],
      video: ['镜头视频', '从审核后的分镜出发，生成并选择合适的镜头版本。', 'video', 'play', null],
      audio: ['声音制作', '为角色安排声音，让对白、环境与画面彼此呼应。', 'audio', 'sound', null],
      editing: [
        '剪辑与成片',
        '将镜头与声音编排成时间线，再合成你的作品。',
        'editing',
        'edit',
        w.editing || w.dashboard?.editing,
      ],
      evaluation: [
        '成片评估',
        '检查结构指标与制作报告，最终质量由创作者判断。',
        'evaluate',
        'review',
        w.evaluation || w.dashboard?.evaluation,
      ],
    };
    const [title, description, stage, symbol, value] = definitions[tab] || definitions.directing;
    content = `<div class="panel">${section(title, '', action('run-stage', `执行${title}`, 'spark', 'primary', `data-stage="${stage}"`))}<p class="settings-tip">${description}</p>${value ? `<pre class="json-view">${h(JSON.stringify(value, null, 2))}</pre>` : empty('为下一帧，做好准备', description, '', symbol)}${tab === 'editing' ? `<div class="form-footer">${action('run-stage', '合成预览', 'play', '', 'data-stage="render"')}${action('run-stage', '导出 MP4', 'download', 'primary', 'data-stage="export"')}</div>` : ''}<div class="inline-note">${icon('info')}${state.api.isDemo ? '示例模式仅更新内存记录，不生成真实视频或声音。' : '执行操作可能创建任务并调用已配置模型；提交前会再次确认。'}</div><a class="button small" href="/legacy/index.html" target="_blank" rel="noopener">打开经典工作台进行完整版本操作 ${icon('arrow')}</a></div>`;
  }
  return banner + `<div class="reveal delay-1">${content}</div>`;
}
export function settingsView(state) {
  return (
    heading(
      '为创作，准备好工具。',
      '管理工作空间与接口连接，让你的制作流程保持清晰。',
      'STUDIO PREFERENCES',
    ) +
    `<div class="settings-grid"><div><form id="connection-form" class="panel settings-panel"><h2>数据与接口连接</h2><p>界面与请求层独立，支持示例浏览和现有后端接口。</p><div class="mode-options"><label class="mode-option"><input type="radio" name="mode" value="demo" ${state.api.isDemo ? 'checked' : ''}><span><strong>示例空间</strong><small>内存数据，无模型请求</small></span></label><label class="mode-option"><input type="radio" name="mode" value="live" ${!state.api.isDemo ? 'checked' : ''}><span><strong>连接后端</strong><small>读取并操作真实项目</small></span></label></div><div class="form-grid" style="margin-top:20px"><div class="form-field full"><label for="api-url">API 地址</label><input id="api-url" name="baseUrl" value="${h(state.connection.baseUrl)}" placeholder="/api/v1" required><small>同源默认 /api/v1；跨域地址需由服务端允许访问。</small></div><div class="form-field"><label for="identity-user">开发身份</label><input id="identity-user" name="userId" value="${h(state.connection.userId)}" autocomplete="off"></div><div class="form-field"><label for="identity-role">开发角色</label><select id="identity-role" name="userRole"><option value="admin" ${state.connection.userRole === 'admin' ? 'selected' : ''}>管理员</option><option value="user" ${state.connection.userRole === 'user' ? 'selected' : ''}>成员</option></select></div></div><div class="inline-note">${icon('info')}此处用于现有开发身份接入；正式用户鉴权应由后端提供。模型密钥不进入前端。</div><div class="form-footer">${action('test-connection', '测试连接', 'link')}<button class="button primary" type="submit">应用连接 ${icon('arrow')}</button></div></form><section class="panel settings-panel"><h2>界面与工作习惯</h2><p>当前创作空间默认中文，使用本地字体与资源。</p><ul class="detail-list"><li>界面语言<strong>简体中文</strong></li><li>创作模式<strong>${state.api.isDemo ? '示例空间' : '真实项目'}</strong></li><li>显示主题<strong>冰白 / 玻璃卡片</strong></li><li>示例数据<strong>刷新后恢复初始内容</strong></li></ul></section></div><aside><section class="panel"><span class="agent-icon">${icon('link')}</span><h2 style="font-size:13px;margin-top:17px">接口已经准备就绪</h2><p class="settings-tip">项目、剧本、人物、场景、分镜、任务、审核与模型配置统一通过 API 适配层访问。</p><div class="settings-links"><a href="/docs" target="_blank" rel="noopener">查看后端 API 文档 ${icon('arrow')}</a><a href="/legacy/index.html" target="_blank" rel="noopener">打开经典工作台 ${icon('arrow')}</a></div></section><div class="inline-note">${icon('info')}切换连接会重新加载项目，不会自动启动生成任务。</div></aside></div>`
  );
}
