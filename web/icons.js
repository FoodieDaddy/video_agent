/** 本地图标：固定 SVG 路径，无网络请求；文字与可访问名称由调用方提供。 */
const paths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3z"/><path d="M3 10h18"/>',
  layers: '<path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/>',
  agents:
    '<path d="M8 5h8a4 4 0 0 1 4 4v10H4V9a4 4 0 0 1 4-4Z"/><path d="M12 2v3M8 19v3m8-3v3M1 10v5m22-5v5M9 14h6"/><circle cx="8.5" cy="10" r=".6"/><circle cx="15.5" cy="10" r=".6"/>',
  review: '<path d="M14 3H5v18h14V8zM14 3v5h5"/><path d="m8 14 3 3 5-6"/>',
  settings:
    '<path d="m9 3-1 3-3 1v4l-2 1 2 2v4l3 1 1 3h6l1-3 3-1v-4l2-2-2-1V7l-3-1-1-3z"/><circle cx="12" cy="12" r="3"/>',
  arrow: '<path d="M4 12h15m-6-6 6 6-6 6"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  bell: '<path d="M6 9a6 6 0 0 1 12 0c0 7 3 7 3 9H3c0-2 3-2 3-9Zm4 12h4"/>',
  book: '<path d="M12 5c-3-3-7-2-10-1v15c3-1 7-2 10 1 3-3 7-2 10-1V4c-3-1-7-2-10 1Zm0 0v15"/>',
  play: '<path d="m9 5 11 7-11 7z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  check: '<path d="m5 12 4 4L20 5"/>',
  film: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4m-4 8h4m10-8h4m-4 8h4"/>',
  spark: '<path d="m12 2 2.7 7.3L22 12l-7.3 2.7L12 22l-2.7-7.3L2 12l7.3-2.7z"/>',
  image:
    '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 6"/>',
  script: '<path d="M6 3h12v18H6zM9 7h6m-6 4h6m-6 4h4"/>',
  people:
    '<circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3m2-17a3 3 0 0 1 0 6m3 11v-3a6 6 0 0 0-3-5"/>',
  location:
    '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
  sound: '<path d="m4 9 5-5v16l-5-5H1V9Zm9-2a7 7 0 0 1 0 10m4-13a11 11 0 0 1 0 16"/>',
  edit: '<path d="m15 4 5 5M4 20l5-1L21 7l-5-5L4 14z"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M3 15v6h18v-6"/>',
  download: '<path d="M12 3v13m-5-5 5 5 5-5M3 16v5h18v-5"/>',
  close: '<path d="m6 6 12 12M6 18 18 6"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  refresh: '<path d="M21 8a9 9 0 1 0 0 8M21 3v5h-5"/>',
  link: '<path d="m10 13 4-4m-5 7-2 2a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 0 2-2a4 4 0 1 1 6 6l-4 4a4 4 0 0 1-6 0"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  focus: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
  unfocus: '<path d="M3 8h5V3m13 5h-5V3M8 21v-5H3m13 5v-5h5"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
};
export function icon(name, className = '') {
  return `<svg class="icon ${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.film}</svg>`;
}
