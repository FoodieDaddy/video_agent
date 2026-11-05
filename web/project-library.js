/** 项目库的只读规则：筛选与排序均基于已载入项目，不修改 API 返回数组。 */
export const PROJECT_SORTS = [
  ['updated', '最近更新'],
  ['created', '创建时间'],
  ['name', '项目名称'],
];

const finished = new Set(['completed', 'exported']);

function timestamp(value) {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : null;
}

export function projectLibraryItems(
  projects = [],
  { filter = 'all', query = '', sort = 'updated' } = {},
) {
  const needle = String(query || '')
    .trim()
    .toLocaleLowerCase();
  return projects
    .map((project, index) => ({ project, index }))
    .filter(({ project }) => {
      const category =
        filter === 'active'
          ? !finished.has(project.status)
          : filter === 'completed'
            ? finished.has(project.status)
            : true;
      return (
        category &&
        String(project.name || '')
          .toLocaleLowerCase()
          .includes(needle)
      );
    })
    .sort((a, b) => {
      if (sort === 'name')
        return (
          String(a.project.name || '').localeCompare(String(b.project.name || ''), 'zh-CN') ||
          a.index - b.index
        );
      const field = sort === 'created' ? 'created_at' : 'updated_at';
      const left = timestamp(a.project[field]);
      const right = timestamp(b.project[field]);
      // 未提供或无效的时间放在最后，不能用编造的时间改变项目顺序。
      if (left === null && right !== null) return 1;
      if (right === null && left !== null) return -1;
      return left === right ? a.index - b.index : right - left;
    })
    .map(({ project }) => project);
}
