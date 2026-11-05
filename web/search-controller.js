/** 全局搜索的纯规则：项目与功能匹配、键盘选择，不依赖 DOM 或触发网络请求。 */
export function searchMatches(query, projects = [], navigation = []) {
  const needle = String(query || '')
    .trim()
    .toLocaleLowerCase();
  if (!needle) return [];
  return [
    ...projects
      .filter((project) =>
        String(project.name || '')
          .toLocaleLowerCase()
          .includes(needle),
      )
      .slice(0, 4)
      .map((project) => ({ kind: 'project', id: project.id, label: project.name, icon: 'folder' })),
    ...navigation
      .filter(([, label]) => String(label).toLocaleLowerCase().includes(needle))
      .slice(0, 3)
      .map(([id, label, icon]) => ({ kind: 'navigation', id, label, icon })),
  ];
}

/** 浮层仍相对搜索框定位，只补足窄屏左右安全间距，不引入 fixed 包含块问题。 */
export function searchPopupOffset({ left, right }, viewportWidth, gutter = 16) {
  if (left < gutter) return gutter - left;
  if (right > viewportWidth - gutter) return viewportWidth - gutter - right;
  return 0;
}

/**
 * 方向键只更新活动项，浏览器焦点始终留在 combobox 输入框。
 * Tab 只收起而不阻止原生焦点移动；输入法确认和带修饰键的文本操作不被接管。
 */
export function searchKeyboardAction(event, { count, index = -1, open = false }) {
  if (!open || event.isComposing || event.keyCode === 229) return null;
  if (event.key === 'Tab') return { close: true, preventDefault: false };
  if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return null;
  if (event.key === 'Escape') return { close: true, preventDefault: true };
  if (!count) return null;
  if (event.key === 'ArrowDown')
    return { index: index < 0 ? 0 : (index + 1) % count, preventDefault: true };
  if (event.key === 'ArrowUp')
    return { index: index < 0 ? count - 1 : (index - 1 + count) % count, preventDefault: true };
  if (event.key === 'Enter')
    return { activate: index < 0 ? 0 : Math.min(index, count - 1), preventDefault: true };
  return null;
}
