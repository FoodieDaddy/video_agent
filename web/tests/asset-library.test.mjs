import test from 'node:test';
import assert from 'node:assert/strict';
import {
  assetType,
  assetName,
  assetTypeLabel,
  assetSizeLabel,
  assetPresentation,
  filterAssets,
  assetPreviewPosition,
} from '../asset-library.js';

test('详情前后浏览遵循当前类型、查询和名称顺序，并在首尾停止', () => {
  const assets = [
    { id: 'image-b', filename: '画面2.png', mime_type: 'image/png' },
    { id: 'audio', filename: '声音.wav', mime_type: 'audio/wav' },
    { id: 'image-a', filename: '画面1.png', mime_type: 'image/png' },
  ];
  const options = { filter: 'image', query: '画面', sort: 'name' };
  assert.deepEqual(assetPreviewPosition(assets, 'image-a', options), {
    index: 1,
    total: 2,
    previousId: null,
    nextId: 'image-b',
  });
  assert.deepEqual(assetPreviewPosition(assets, 'image-b', options), {
    index: 2,
    total: 2,
    previousId: 'image-a',
    nextId: null,
  });
  assert.deepEqual(assetPreviewPosition(assets, 'audio', options), {
    index: 0,
    total: 2,
    previousId: null,
    nextId: null,
  });
});

test('真实接口的文本原文读取 meta.filename，归文档且不虚构时间或音频信息', () => {
  const asset = {
    id: 'source-1',
    kind: 'source_document',
    mime_type: 'text/plain',
    size_bytes: 1536,
    meta: { filename: '雨夜·不归人.txt' },
  };
  assert.deepEqual(assetPresentation(asset), {
    name: '雨夜·不归人.txt',
    type: 'document',
    typeLabel: '文档',
    icon: 'book',
    sizeLabel: '1.5 KiB',
  });
  assert.equal(asset.created_at, undefined);
});

test('媒体按 MIME 分类，未知 MIME 或只有媒体扩展名的文件不伪装成声音', () => {
  for (const [mime, type] of [
    ['image/svg+xml', 'image'],
    ['VIDEO/MP4; codecs=avc1', 'video'],
    ['audio/wav', 'audio'],
    ['application/octet-stream', 'other'],
    ['', 'other'],
  ])
    assert.equal(assetType({ mime_type: mime }), type);
  assert.equal(assetType({ filename: '旧素材.mp3' }), 'other');
  assert.equal(assetTypeLabel({ mime_type: 'application/octet-stream' }), '文件');
  assert.equal(assetTypeLabel('audio'), '声音');
  assert.equal(assetTypeLabel('unknown'), '文件');
  assert.equal(assetTypeLabel('__proto__'), '文件');
});

test('文本、PDF、JSON 和 DOCX 使用同一文档过滤，原文的通用 MIME 也有准确归属', () => {
  for (const mime of [
    'text/markdown',
    'text/plain; charset=utf-8',
    'application/pdf',
    'application/json',
    'application/ld+json',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  ])
    assert.equal(assetType({ mime_type: mime }), 'document');
  assert.equal(
    assetType({ kind: 'source_document', mime_type: 'application/octet-stream' }),
    'document',
  );
});

test('名称优先级兼容示例与真实响应，空值使用友好类别，未知类别不暴露内部名称', () => {
  assert.equal(assetName({ filename: ' 显示名 ', meta: { filename: '原文件.txt' } }), '显示名');
  assert.equal(assetName({ filename: ' ', meta: { filename: ' 原文件.txt ' } }), '原文件.txt');
  assert.equal(assetName({ kind: 'source_document' }), '小说原文');
  assert.equal(assetName({ kind: 'character_portrait' }), '人物形象');
  assert.equal(assetName({ kind: 'unrecognized_internal_kind', filename: {} }), '项目文件');
  assert.equal(assetName({ kind: 'constructor' }), '项目文件');
});

test('检索显示名称并忽略首尾空白和大小写，媒体旧过滤值继续兼容', () => {
  const assets = [
    { id: 'doc', meta: { filename: 'STUDIO 剧本.json' }, mime_type: 'application/json' },
    { id: 'image', filename: 'STUDIO 参考.png', mime_type: 'image/png' },
    { id: 'audio', filename: '对白.wav', mime_type: 'audio/wav' },
  ];
  assert.deepEqual(
    filterAssets(assets, { filter: 'document', query: ' studio ' }).map((a) => a.id),
    ['doc'],
  );
  assert.deepEqual(
    filterAssets(assets, { filter: 'image/' }).map((a) => a.id),
    ['image'],
  );
  assert.deepEqual(
    filterAssets(assets, { filter: 'audio/' }).map((a) => a.id),
    ['audio'],
  );
  assert.deepEqual(filterAssets(assets, { query: '不存在' }), []);
  assert.deepEqual(filterAssets(assets, { filter: 'other' }), []);
});

test('默认保留服务端顺序，名称使用自然排序，同名稳定且不改写原数组或对象', () => {
  const assets = [
    { id: '10', filename: 'Frame 10.png', mime_type: 'image/png' },
    { id: '2a', filename: 'Frame 2.png', mime_type: 'image/png' },
    { id: '2b', meta: { filename: 'Frame 2.png' }, mime_type: 'image/png' },
  ];
  const original = structuredClone(assets);
  assert.deepEqual(
    filterAssets(assets).map((a) => a.id),
    ['10', '2a', '2b'],
  );
  assert.deepEqual(
    filterAssets(assets, { sort: 'name' }).map((a) => a.id),
    ['2a', '2b', '10'],
  );
  assert.deepEqual(assets, original);
  assert.notEqual(filterAssets(assets), assets);
});

test('大小缺失或不合法时不伪造数值，真实零字节与各单位可以区分', () => {
  for (const value of [undefined, null, '', '1024', -1, NaN, Infinity, 1.5])
    assert.equal(assetSizeLabel({ size_bytes: value }), '');
  assert.equal(assetSizeLabel({ size_bytes: 0 }), '0 B');
  assert.equal(assetSizeLabel({ size_bytes: 999 }), '999 B');
  assert.equal(assetSizeLabel({ size_bytes: 1024 }), '1 KiB');
  assert.equal(assetSizeLabel({ size_bytes: 1048576 }), '1 MiB');
});
