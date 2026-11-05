/** 素材库纯规则：按真实 MIME 分类，读取公开元信息，不把缺失字段变成虚构内容。 */
const DOCUMENT_MIMES = new Set([
  'application/pdf',
  'application/json',
  'application/xml',
  'application/rtf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.oasis.opendocument.text',
  'application/epub+zip',
]);
const TYPES = {
  image: { label: '图像', icon: 'image' },
  video: { label: '视频', icon: 'play' },
  audio: { label: '声音', icon: 'sound' },
  document: { label: '文档', icon: 'book' },
  other: { label: '文件', icon: 'layers' },
};
const KIND_NAMES = {
  source_document: '小说原文',
  script_document: '剧本文档',
  character_portrait: '人物形象',
  character_image: '人物图像',
  scene_reference: '场景参考',
  scene_image: '场景图像',
  storyboard_image: '分镜图像',
  shot_image: '分镜图像',
  shot_video: '镜头视频',
  dialogue_audio: '对白声音',
  narration_audio: '旁白声音',
  background_music: '背景音乐',
  music: '音乐素材',
  final_video: '成片',
  film: '成片',
};
const FILTER_ALIASES = { 'image/': 'image', 'video/': 'video', 'audio/': 'audio' };
const nameOrder = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' });
const nonemptyName = (value) => (typeof value === 'string' ? value.trim() : '');

export function assetType(asset = {}) {
  const mime = String(asset?.mime_type || '')
    .split(';', 1)[0]
    .trim()
    .toLowerCase();
  // 媒体类型以 MIME 为准；未知文件不能因为兜底分支而被标成声音。
  for (const type of ['image', 'video', 'audio']) {
    if (mime.startsWith(`${type}/`)) return type;
  }
  if (
    asset?.kind === 'source_document' ||
    mime.startsWith('text/') ||
    DOCUMENT_MIMES.has(mime) ||
    mime.endsWith('+json')
  )
    return 'document';
  return 'other';
}

export function assetName(asset = {}) {
  return (
    nonemptyName(asset?.filename) ||
    nonemptyName(asset?.meta?.filename) ||
    (Object.hasOwn(KIND_NAMES, asset?.kind) ? KIND_NAMES[asset.kind] : '') ||
    '项目文件'
  );
}

export function assetTypeLabel(typeOrAsset) {
  const type = typeof typeOrAsset === 'string' ? typeOrAsset : assetType(typeOrAsset);
  return (Object.hasOwn(TYPES, type) ? TYPES[type] : TYPES.other).label;
}

/** 文件大小只使用实际字节数；缺失、非法数字与真实的零字节分别处理。 */
export function assetSizeLabel(asset = {}) {
  const size = asset?.size_bytes;
  if (!Number.isInteger(size) || size < 0) return '';
  if (size < 1024) return `${size} B`;
  const units = ['KiB', 'MiB', 'GiB', 'TiB'];
  const exponent = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length);
  const value = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(
    size / 1024 ** exponent,
  );
  return `${value} ${units[exponent - 1]}`;
}

export function assetPresentation(asset = {}) {
  const type = assetType(asset);
  return {
    name: assetName(asset),
    type,
    typeLabel: TYPES[type].label,
    icon: TYPES[type].icon,
    sizeLabel: assetSizeLabel(asset),
  };
}

/** 过滤／检索／排序只作用于列表副本；默认顺序不暗示不存在的创建或更新时间。 */
export function filterAssets(assets = [], { filter = 'all', query = '', sort = 'default' } = {}) {
  const type = Object.hasOwn(FILTER_ALIASES, filter) ? FILTER_ALIASES[filter] : filter;
  const needle = String(query || '')
    .trim()
    .toLocaleLowerCase();
  const matches = assets.filter(
    (asset) =>
      (type === 'all' || assetType(asset) === type) &&
      assetName(asset).toLocaleLowerCase().includes(needle),
  );
  if (sort === 'name' || sort === 'name-asc')
    matches.sort((left, right) => nameOrder.compare(assetName(left), assetName(right)));
  return matches;
}

/** 详情前后浏览只沿当前筛选结果移动，不跳到被隐藏的类型或改写列表顺序。 */
export function assetPreviewPosition(assets, id, options = {}) {
  const matches = filterAssets(assets, options);
  const index = matches.findIndex((asset) => asset.id === id);
  return {
    index: index < 0 ? 0 : index + 1,
    total: matches.length,
    previousId: index > 0 ? matches[index - 1].id : null,
    nextId: index >= 0 && index + 1 < matches.length ? matches[index + 1].id : null,
  };
}
