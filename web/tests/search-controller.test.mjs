import test from 'node:test';
import assert from 'node:assert/strict';
import { searchMatches, searchKeyboardAction, searchPopupOffset } from '../search-controller.js';

const navigation = [
  ['projects', '我的项目', 'folder'],
  ['overview', '创作概览', 'grid'],
  ['assets', '素材管理', 'layers'],
];

test('查询先匹配真实项目再匹配功能，忽略首尾空白和大小写，不改写源数据', () => {
  const projects = [
    { id: 'p1', name: 'Studio 项目' },
    { id: 'p2', name: '雨夜' },
  ];
  const original = structuredClone(projects);
  assert.deepEqual(searchMatches(' STUDIO ', projects, navigation), [
    { kind: 'project', id: 'p1', label: 'Studio 项目', icon: 'folder' },
  ]);
  assert.deepEqual(
    searchMatches('项目', projects, navigation).map((item) => item.id),
    ['p1', 'projects'],
  );
  assert.deepEqual(projects, original);
});

test('项目和功能分别限量；空查询和无匹配查询都不填充虚构结果', () => {
  const projects = Array.from({ length: 8 }, (_, i) => ({ id: `p${i}`, name: `项目 ${i}` }));
  const nav = Array.from({ length: 5 }, (_, i) => [`n${i}`, `项目功能 ${i}`, 'folder']);
  const items = searchMatches('项目', projects, nav);
  assert.equal(items.filter((item) => item.kind === 'project').length, 4);
  assert.equal(items.filter((item) => item.kind === 'navigation').length, 3);
  assert.deepEqual(searchMatches('  ', projects, nav), []);
  assert.deepEqual(searchMatches('不存在', projects, nav), []);
});

test('方向键选择保持可循环，Enter 激活对应项目；直接 Enter 使用第一项', () => {
  const items = searchMatches('项目', [{ id: 'p1', name: '项目一' }], navigation);
  let index = -1;
  for (const key of ['ArrowDown', 'ArrowDown', 'ArrowDown', 'ArrowUp']) {
    index = searchKeyboardAction({ key }, { count: items.length, index, open: true }).index;
  }
  const action = searchKeyboardAction({ key: 'Enter' }, { count: items.length, index, open: true });
  assert.equal(items[action.activate].id, 'projects');
  assert.deepEqual(searchKeyboardAction({ key: 'Enter' }, { count: 2, index: -1, open: true }), {
    activate: 0,
    preventDefault: true,
  });
  assert.equal(
    searchKeyboardAction({ key: 'ArrowUp' }, { count: 2, index: -1, open: true }).index,
    1,
  );
});

test('空结果或已关闭列表不产生激活；缩短后的列表不会激活失效下标', () => {
  for (const key of ['Enter', 'ArrowDown', 'ArrowUp']) {
    assert.equal(searchKeyboardAction({ key }, { count: 0, index: -1, open: true }), null);
    assert.equal(searchKeyboardAction({ key }, { count: 3, index: 0, open: false }), null);
  }
  assert.equal(
    searchKeyboardAction({ key: 'Enter' }, { count: 1, index: 3, open: true }).activate,
    0,
  );
});

test('输入法确认与带修饰键的文本操作不被搜索拦截', () => {
  const state = { count: 3, index: 1, open: true };
  for (const event of [
    { key: 'Enter', isComposing: true },
    { key: 'Escape', keyCode: 229 },
    { key: 'ArrowDown', ctrlKey: true },
    { key: 'ArrowUp', shiftKey: true },
    { key: 'Enter', metaKey: true },
  ])
    assert.equal(searchKeyboardAction(event, state), null);
});

test('Escape 收起并消费本次按键，Tab 和 Shift+Tab 收起但保留原生焦点移动', () => {
  const state = { count: 2, index: 1, open: true };
  assert.deepEqual(searchKeyboardAction({ key: 'Escape' }, state), {
    close: true,
    preventDefault: true,
  });
  for (const shiftKey of [false, true])
    assert.deepEqual(searchKeyboardAction({ key: 'Tab', shiftKey }, state), {
      close: true,
      preventDefault: false,
    });
});

test('相对定位的浮层只补足视口安全间距，重测原始坐标不会累计偏移', () => {
  assert.equal(searchPopupOffset({ left: 40, right: 350 }, 390), 0);
  assert.equal(searchPopupOffset({ left: -80, right: 278 }, 390), 96);
  assert.equal(searchPopupOffset({ left: 100, right: 458 }, 390), -84);
  const offset = searchPopupOffset({ left: -38, right: 250 }, 320);
  assert.equal(offset, 54);
  assert.equal(searchPopupOffset({ left: -38 + offset, right: 250 + offset }, 320), 0);
});
