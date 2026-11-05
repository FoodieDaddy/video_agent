/** 展示契约回归：真实字段、示例边界、文本转义与空状态。 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createStudioApi } from '../api.js';
import {
  overview,
  projectsView,
  agentsView,
  assetsView,
  reviewsView,
  settingsView,
  workbench,
  mediaUrl,
  storyPreviewContent,
} from '../views.js';

async function state() {
  const api = createStudioApi({ mode: 'demo' });
  const projects = await api.getProjects();
  return {
    api,
    projects,
    agents: await api.getAgentCatalog(),
    workspace: await api.getWorkspace(projects[0].id),
    connection: api.getConnection(),
    tab: 'story',
  };
}

test('项目文本和未知状态进入 HTML 时统一转义', async () => {
  const s = await state();
  s.workspace.project.demo = false;
  s.workspace.project.status = '<img src=x onerror="globalThis.injected=true">';
  s.workspace.project.name = '<script>injected</script>';
  const html = overview(s);
  assert.ok(html.includes('&lt;script&gt;injected&lt;/script&gt;'));
  assert.ok(html.includes('&lt;img src=x onerror='));
  assert.ok(!html.includes('<script>injected'));
  assert.ok(!html.includes('<img src=x onerror='));
});

test('概览阅读显示手写正文并转义，缺少梗概不误报没有剧本', () => {
  const html = storyPreviewContent({ version: 2, script_text: '林简：<灯还亮着>。' });
  assert.ok(html.includes('当前 V2'));
  assert.ok(html.includes('林简：&lt;灯还亮着&gt;。'));
  assert.ok(!html.includes('尚未'));
  assert.ok(storyPreviewContent({ version: 1, synopsis: '旧稿梗概' }).includes('旧稿梗概'));
  assert.ok(storyPreviewContent(null).includes('直接编写或导入'));
});

test('真实分镜读取 order，缺少图片时不混入示例电影图', async () => {
  const s = await state();
  s.api = { isDemo: false };
  s.tab = 'storyboard';
  s.workspace.project = {
    id: 'real-project',
    name: '真实项目',
    aspect_ratio: '16:9',
    status: 'created',
  };
  s.workspace.shots = [
    { id: 'real-shot', order: 7, description: '真实镜头', duration_seconds: 4, camera: {} },
  ];
  const html = workbench(s);
  assert.ok(html.includes('SHOT 07'));
  assert.ok(!html.includes('/assets/rainy-bookstore.png'));
  assert.ok(!html.includes('data:image'));
});

test('场景响应只有 approved_version 时仍显示已确认', async () => {
  const s = await state();
  s.tab = 'scenes';
  s.workspace.scenes = [
    { id: 'scene', name: '书店', approved_version: 2, profile: { description: '暖光' } },
  ];
  assert.ok(workbench(s).includes('已确认'));
});

test('素材视图读取真实文件元信息，文本归文档且不伪造缺失日期', async () => {
  const s = await state();
  s.api = { isDemo: false };
  s.workspace.assets = [
    {
      id: 'source-1',
      kind: 'source_document',
      mime_type: 'text/plain',
      size_bytes: 1004,
      meta: { filename: '<雨夜>.txt' },
    },
  ];
  const html = assetsView(s);
  assert.ok(html.includes('&lt;雨夜&gt;.txt'));
  assert.ok(html.includes('文档 · 1004 B'));
  assert.ok(!html.includes('AUDIO'));
  assert.ok(!html.includes('source_document'));
  assert.ok(!html.includes('尚无记录'));
});

test('素材筛选无匹配与项目无素材分别给出准确状态和恢复入口', async () => {
  const s = await state();
  s.workspace.assets = [{ id: 'text-1', kind: 'source_document', mime_type: 'text/plain' }];
  s.assetFilter = 'image';
  let html = assetsView(s);
  assert.ok(html.includes('没有匹配的素材'));
  assert.ok(html.includes('已载入 1 份素材 · 显示 0 份'));
  assert.ok(html.includes('data-action="clear-asset-filters"'));
  s.workspace.assets = [];
  html = assetsView(s);
  assert.ok(html.includes('这个项目还没有素材'));
  assert.ok(!html.includes('没有匹配的素材'));
  assert.ok(html.includes('id="asset-empty-project"'));
});

test('全部主入口可以呈现无项目状态', async () => {
  const s = await state();
  s.workspace = null;
  s.projects = [];
  for (const render of [
    overview,
    projectsView,
    agentsView,
    assetsView,
    reviewsView,
    settingsView,
    workbench,
  ]) {
    assert.doesNotThrow(() => render(s));
    assert.ok(render(s).length > 20);
  }
});

test('媒体地址拒绝脚本协议与协议相对地址', () => {
  assert.equal(mediaUrl('javascript:alert(1)'), '');
  assert.equal(mediaUrl('//example.com/unknown.png'), '');
  assert.equal(mediaUrl('/media/project/image.png'), '/media/project/image.png');
  assert.equal(mediaUrl('https://example.com/image.png'), 'https://example.com/image.png');
  assert.equal(mediaUrl('data:image/svg+xml,%3Csvg%3E'), 'data:image/svg+xml,%3Csvg%3E');
});

test('新建真实项目无封面时展示可阅读空态，不使用示例主视觉', async () => {
  const s = await state();
  s.api = { isDemo: false };
  s.workspace.project = {
    id: 'live-project',
    name: '真实项目',
    status: 'draft',
    aspect_ratio: '16:9',
  };
  s.projects = [s.workspace.project];
  const html = overview(s);
  assert.ok(html.includes('当前项目暂无封面'));
  assert.ok(html.includes('阅读故事'));
  assert.ok(html.includes('is-coverless'));
  assert.ok(!html.includes('/assets/rainy-bookstore.png'));
});

test('剧本无现稿时仍有正文编辑、导入和小说解析入口', async () => {
  const s = await state();
  s.workspace.script = null;
  s.workspace.chapters = [];
  const html = workbench(s);
  assert.ok(html.includes('id="script-editor-form"'));
  assert.ok(html.includes('name="script_text"'));
  assert.ok(html.includes('data-action="import-script"'));
  assert.ok(html.includes('上传小说原文'));
  assert.ok(html.includes('data-stage="analyze"'));
  assert.ok(html.includes('保存第一版完整正文后'));
});

test('剧本正文与结构化数据区分、草稿转义、冲突和历史版本可以展示', async () => {
  const s = await state();
  s.scriptDraft = {
    title: '<片名>',
    script_text: '</textarea><script>alert(1)</script>',
    logline: '',
    synopsis: '',
    dirty: true,
    restored: true,
    conflict: true,
    error: '版本冲突',
    persisted: true,
  };
  s.workspace.scriptVersions = [
    s.workspace.script,
    { id: 'older', version: 0, title: '旧版本', workspace_meta: { source: 'import' } },
  ];
  const html = workbench(s);
  assert.ok(html.includes('&lt;/textarea&gt;&lt;script&gt;alert(1)&lt;/script&gt;'));
  assert.ok(!html.includes('<script>alert(1)</script>'));
  assert.ok(html.includes('结构化解析数据'));
  assert.ok(html.includes('只读'));
  assert.ok(html.includes('草稿已保留'));
  assert.ok(html.includes('核对后另存草稿'));
  assert.ok(html.includes('旧版本'));
  assert.ok(html.includes('从小说解析新版本'));
  assert.ok(html.includes('请先保存正文'));
});

test('AI失败和新版本结果显示状态，模拟任务明确标记', async () => {
  const s = await state();
  s.scriptAssist = { operation: 'continue', instruction: '保留原文', error: '上次版本已变化' };
  s.workspace.tasks = [
    {
      id: 'failed-task',
      type: 'script_assist',
      status: 'failed',
      error: '供应商超时',
      message: '未完成',
    },
    {
      id: 'result-task',
      type: 'script_assist',
      status: 'succeeded',
      result: { script_id: 'new-version', version: 2 },
      message: '已完成',
    },
    {
      id: 'demo-task',
      type: 'script_assist',
      status: 'succeeded',
      result: { simulated: true },
      message: '仅模拟',
    },
  ];
  const html = workbench(s);
  assert.ok(html.includes('供应商超时'));
  assert.ok(html.includes('上次版本已变化'));
  assert.ok(html.includes('已生成 V2'));
  assert.ok(html.includes('data-id="new-version"'));
  assert.ok(html.includes('模拟'));
  assert.ok(html.includes('value="continue" selected'));
});

test('后续制作提醒默认收起，新项目无下游内容时不重复打断编辑', async () => {
  const s = await state();
  let html = workbench(s);
  assert.ok(html.includes('<details class="script-notice script-reconfirmation">'));
  assert.ok(html.includes('正文已更新，后续制作内容需重新核对'));
  assert.ok(!html.includes('script-reconfirmation" open'));
  s.workspace.workflow = null;
  s.workspace.characters = [];
  s.workspace.scenes = [];
  s.workspace.shots = [];
  s.workspace.assets = [];
  html = workbench(s);
  assert.ok(!html.includes('script-reconfirmation'));
  assert.match(html, /data-script-save disabled/);
  assert.ok(html.includes('已保存</button>'));
});
