import test from 'node:test';
import assert from 'node:assert/strict';
import { projectLibraryItems } from '../project-library.js';
import { projectsView, projectCard } from '../views.js';

const projects = [
  {
    id: 'a',
    name: 'Alpha 书店',
    status: 'draft',
    created_at: '2026-01-01',
    updated_at: '2026-11-04',
  },
  {
    id: 'b',
    name: 'Beta 灯塔',
    status: 'completed',
    created_at: '2026-02-01',
    updated_at: '2026-10-01',
  },
  {
    id: 'c',
    name: 'Gamma 书店',
    status: 'exported',
    created_at: '2026-03-01',
    updated_at: 'invalid',
  },
];
const ids = (rows) => rows.map((row) => row.id);

test('项目搜索忽略两端空白及大小写，分类与搜索共同生效', () => {
  assert.deepEqual(ids(projectLibraryItems(projects, { query: '  ALPHA ' })), ['a']);
  assert.deepEqual(ids(projectLibraryItems(projects, { query: '书店', filter: 'completed' })), [
    'c',
  ]);
  assert.deepEqual(ids(projectLibraryItems(projects, { filter: 'active' })), ['a']);
  assert.deepEqual(ids(projectLibraryItems(projects, { filter: 'completed' })), ['b', 'c']);
});

test('按实际更新时间或创建时间排序，缺失时间最后，原始数组不变', () => {
  const before = structuredClone(projects);
  const withMissing = [...projects, { id: 'd', name: 'Delta', status: 'draft' }];
  assert.deepEqual(ids(projectLibraryItems(withMissing)), ['a', 'b', 'c', 'd']);
  assert.deepEqual(ids(projectLibraryItems(withMissing, { sort: 'created' })), [
    'c',
    'b',
    'a',
    'd',
  ]);
  assert.deepEqual(projects, before);
});

test('名称排序稳定，同名或同时间项目保持原顺序', () => {
  assert.deepEqual(ids(projectLibraryItems([...projects].reverse(), { sort: 'name' })), [
    'a',
    'b',
    'c',
  ]);
  const same = [
    { id: 'first', name: '同名', updated_at: '2026-01-01' },
    { id: 'second', name: '同名', updated_at: '2026-01-01' },
  ];
  assert.deepEqual(ids(projectLibraryItems(same, { sort: 'name' })), ['first', 'second']);
  assert.deepEqual(ids(projectLibraryItems(same)), ['first', 'second']);
});

test('筛选无匹配与没有项目使用不同空状态，零匹配不伪装成新建卡', () => {
  const noMatch = projectsView({ projects, query: '不存在', filter: 'all' });
  assert.ok(noMatch.includes('没有找到匹配项目'));
  assert.ok(noMatch.includes('data-action="clear-project-filters"'));
  assert.ok(noMatch.includes('显示 0 个'));
  assert.ok(!noMatch.includes('class="new-project-card"'));
  const noProjects = projectsView({ projects: [], query: '', filter: 'all' });
  assert.ok(noProjects.includes('还没有项目'));
  assert.ok(!noProjects.includes('clear-project-filters'));
});

test('当前筛选、排序和查询以可访问属性及转义文案显示', () => {
  const html = projectsView({
    projects,
    filter: 'completed',
    query: '<书店>',
    projectSort: 'created',
  });
  assert.ok(html.includes('data-filter="completed" aria-pressed="true"'));
  assert.ok(html.includes('value="created" selected'));
  assert.ok(html.includes('&lt;书店&gt;'));
  assert.ok(html.includes('aria-describedby="library-results-status"'));
});

test('排序或筛选后非首位真实项目仍使用自身封面，完整名称可访问', () => {
  const html = projectCard(
    { id: 'real', name: '很长的<项目名称>', cover_url: '/media/real-cover.png' },
    4,
  );
  assert.ok(html.includes('src="/media/real-cover.png"'));
  assert.ok(html.includes('aria-label="进入项目：很长的&lt;项目名称&gt;"'));
  assert.ok(html.includes('class="project-card-name"'));
});
