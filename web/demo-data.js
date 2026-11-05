/**
 * 纯内存演示资料。所有图片由本地 SVG 构造，导入本文件不会请求后端或模型。
 * 62% 等进度仅用于 DEMO 展示，不代表真实项目的执行结果。
 */

const DEMO_TIME = '2026-11-04T10:30:00+08:00';
const copy = (value) => structuredClone(value);
const xml = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[char],
  );

/** 内联素材只提供氛围与人物轮廓，明确属于示例插图。 */
export function demoArtwork(label, variant = 'scene', palette = 'amber') {
  const colors =
    palette === 'blue'
      ? ['#17262e', '#365462', '#99b4b7']
      : palette === 'green'
        ? ['#1b2924', '#4c6655', '#c2c8a0']
        : ['#282521', '#64513b', '#d5b481'];
  const silhouette =
    variant === 'portrait'
      ? '<ellipse cx="320" cy="190" rx="68" ry="85" fill="#151c20"/><path d="M180 450q7-171 140-171t140 171" fill="#20292c"/><path d="M260 169q65-98 126 8l-5-48-49-40-63 29z" fill="#111719"/>'
      : '<path d="M94 110h210v295H94zM336 110h210v295H336z" fill="#111d22" stroke="#8d7452" stroke-width="8"/><path d="M110 130h175v255H110zM353 130h175v255H353z" fill="#a98148" opacity=".38"/><path d="M0 340h640v140H0z" fill="#111a1c" opacity=".7"/><path d="M190 330V208h72v122m112 0V180h76v150" stroke="#b39b70" stroke-width="12" opacity=".6"/><path d="M115 140l40 245m100-245 40 245m100-245 40 245m70-245 25 245" stroke="#b9d2d6" stroke-width="2" opacity=".25"/>';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480"><defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="${colors[0]}"/><stop offset="1" stop-color="${colors[1]}"/></linearGradient><radialGradient id="light"><stop stop-color="${colors[2]}" stop-opacity=".55"/><stop offset="1" stop-color="${colors[2]}" stop-opacity="0"/></radialGradient></defs><path fill="url(#bg)" d="M0 0h640v480H0z"/><ellipse cx="410" cy="200" rx="290" ry="220" fill="url(#light)"/>${silhouette}<path d="M0 410h640v70H0z" fill="#101719" opacity=".75"/><text x="30" y="447" fill="#eee3cf" font-size="23" font-family="sans-serif">${xml(label)}</text><text x="610" y="447" fill="#c3bda9" text-anchor="end" font-size="12" font-family="sans-serif">DEMO / 示例插图</text></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/** task.md 的 13 个职责；部分职责在后端由多个配置实例共同承担。 */
export const AGENT_CATALOG = Object.freeze(
  [
    {
      id: 'orchestrator',
      name: '制片统筹',
      category: '统筹',
      description: '理解创作目标，协调制作阶段与人工审核。',
      agent_ids: ['orchestrator'],
    },
    {
      id: 'script',
      name: '剧本解析',
      category: '故事',
      description: '将原文整理成章节、事件、人物与对白。',
      agent_ids: ['script'],
    },
    {
      id: 'character',
      name: '人物设定',
      category: '美术',
      description: '提取人物、完善档案并检查设定一致性。',
      agent_ids: ['character_extraction', 'character_description', 'character_consistency'],
    },
    {
      id: 'character_vision',
      name: '人物视觉分析',
      category: '美术',
      description: '理解参考图中的外观、服装与视觉特征。',
      agent_ids: ['character_vision'],
    },
    {
      id: 'character_image',
      name: '人物形象',
      category: '美术',
      description: '根据已确认的档案制作人物参考形象。',
      agent_ids: ['character_image'],
    },
    {
      id: 'scene',
      name: '场景设定',
      category: '美术',
      description: '提取地点，整理空间、光线与场景视觉设定。',
      agent_ids: ['scene_extraction', 'scene_description'],
    },
    {
      id: 'director',
      name: '导演规划',
      category: '导演',
      description: '规划影像风格、节奏与情绪走向。',
      agent_ids: ['director'],
    },
    {
      id: 'storyboard',
      name: '分镜设计',
      category: '导演',
      description: '把故事转化为可审核的镜头与调度。',
      agent_ids: ['storyboard'],
    },
    {
      id: 'prompt',
      name: '视觉提示词',
      category: '制作',
      description: '把镜头描述转换为生成模型可用的提示词。',
      agent_ids: ['prompt'],
    },
    {
      id: 'video',
      name: '视频生成',
      category: '制作',
      description: '生成镜头视频，保留版本供创作者选择。',
      agent_ids: ['video'],
    },
    {
      id: 'audio',
      name: '声音设计',
      category: '声音',
      description: '安排对白、音色、环境声与配乐。',
      agent_ids: ['audio', 'audio_voice'],
    },
    {
      id: 'editing',
      name: '剪辑合成',
      category: '后期',
      description: '规划时间线，组合画面与声音。',
      agent_ids: ['editing'],
    },
    {
      id: 'evaluation',
      name: '成片评估',
      category: '质量',
      description: '检查叙事、连续性及最终视听质量。',
      agent_ids: ['evaluation'],
    },
  ].map((agent) => ({
    ...agent,
    status: 'demo',
    enabled: true,
    model_id: '示例配置 · 不调用模型',
  })),
);

function character(id, name, summary, appearance, personality, palette = 'amber') {
  return {
    id,
    name,
    aliases: [],
    role_type: 'supporting',
    status: 'approved',
    summary,
    appearance_keywords: appearance.split('、'),
    profile: {
      name,
      appearance,
      personality,
      visual_keywords: appearance.split('、'),
      source_facts: [summary],
    },
    approved_version: 1,
    image_url: demoArtwork(name, 'portrait', palette),
  };
}

function scene(id, name, summary, description, time, mood, palette = 'amber') {
  return {
    id,
    name,
    summary,
    chapter_index: 1,
    status: 'approved',
    approved_version: 1,
    profile: {
      description,
      time_of_day: time,
      mood,
      visual_prompt: `${description}，${mood}，电影感自然光。`,
    },
    visual_prompt: `${description}，${mood}，电影感自然光。`,
    image_url: demoArtwork(name, 'scene', palette),
  };
}

function project(id, name, description, genre, status, progress, palette) {
  return {
    id,
    name,
    description,
    genre,
    status,
    language: 'zh',
    aspect_ratio: '16:9',
    owner_id: 'user_demo',
    budget_limit_usd: 100,
    spent_usd: 0,
    settings: {},
    config_version: 'demo-1',
    created_at: DEMO_TIME,
    updated_at: DEMO_TIME,
    demo: true,
    progress,
    cover_url: demoArtwork(name, 'scene', palette),
  };
}

/** 为每个适配器创建独立状态，刷新页面后恢复初始样例。 */
export function createDemoState() {
  const projects = [
    project(
      'demo-rainy-bookstore',
      '雨夜书店',
      '一封迟到十年的信，让即将关门的旧书店重新亮起灯。',
      '剧情 / 治愈',
      'awaiting_review',
      0.62,
      'amber',
    ),
    project(
      'demo-snow-letter',
      '雪线来信',
      '年轻的邮递员穿过雪山，为一座空村送去最后一封家书。',
      '公路 / 剧情',
      'draft',
      0.24,
      'blue',
    ),
    project(
      'demo-last-ferry',
      '最后一班渡轮',
      '离岛前的一夜，两位陌生人在渡口交换各自的秘密。',
      '短片 / 文艺',
      'draft',
      0.08,
      'green',
    ),
  ];
  const characters = [
    {
      ...character(
        'demo-char-lin',
        '林简',
        '32 岁，旧书店继承人。准备结束父亲留下的书店，却被一封旧信留住。',
        '短黑发、深色针织衫、旧腕表',
        '内敛、克制、心思细腻',
      ),
      role_type: 'protagonist',
    },
    character(
      'demo-char-su',
      '苏晚',
      '29 岁，雨夜来访的修书师。她认出了信封上的字迹。',
      '齐肩发、米白风衣、帆布包',
      '温柔、坚定、善于倾听',
      'blue',
    ),
    character(
      'demo-char-father',
      '林父',
      '旧书店创办人，出现在回忆与旧信中。相信每一本书都有等待的人。',
      '灰白短发、圆框眼镜、棕色围裙',
      '沉静、宽厚、念旧',
      'green',
    ),
  ];
  const scenes = [
    scene(
      'demo-scene-shop',
      '旧书店 · 主厅',
      '暖黄台灯、木质书架与玻璃上的雨痕。',
      '狭长的老书店，深色木书架围住一张旧柜台，门边挂着铜铃',
      '雨夜',
      '安静、怀旧、温暖',
    ),
    scene(
      'demo-scene-room',
      '书店 · 后屋',
      '堆满待修旧书的工作间，留着父亲生活过的痕迹。',
      '小小的修书工作台，旧台灯照着信封和泛黄的纸张',
      '深夜',
      '私密、柔和、略带伤感',
      'green',
    ),
    scene(
      'demo-scene-street',
      '雨夜 · 街巷',
      '雨水倒映书店橱窗的暖光，街道几乎无人。',
      '湿润石板路伸向街角，昏黄路灯和书店招牌倒映在积水中',
      '雨夜',
      '孤独、期待、朦胧',
      'blue',
    ),
  ];
  const descriptions = [
    [
      '雨落在橱窗上，书店的灯还亮着',
      '雨丝掠过玻璃，林简在窗后收拾最后一摞书。',
      'demo-scene-street',
      [],
      '远景',
      5,
    ],
    [
      '林简停在一封旧信前',
      '从旧书夹页滑落的信封让他停下了手。',
      'demo-scene-shop',
      ['demo-char-lin'],
      '特写',
      4,
    ],
    [
      '门铃响起，苏晚推门而入',
      '她抖落风衣上的雨水，目光落在信封上。',
      'demo-scene-shop',
      ['demo-char-su'],
      '中景',
      6,
    ],
    [
      '两人在灯下展开信纸',
      '苏晚轻轻抚平折痕，林简望向父亲的旧照片。',
      'demo-scene-room',
      ['demo-char-lin', 'demo-char-su'],
      '双人中近景',
      8,
    ],
    [
      '回忆中，父亲把一本书放回书架',
      '父亲回头微笑，窗外的雨声与记忆重合。',
      'demo-scene-shop',
      ['demo-char-father'],
      '近景',
      5,
    ],
    [
      '林简翻转门上的营业牌',
      '他重新点亮橱窗，苏晚坐在柜台边开始修书。',
      'demo-scene-shop',
      ['demo-char-lin', 'demo-char-su'],
      '远景',
      7,
    ],
  ];
  const shots = descriptions.map(
    ([description, action, scene_id, people, size, duration], index) => ({
      id: `demo-shot-${index + 1}`,
      shot_id: `demo-shot-${index + 1}`,
      storyboard_id: 'demo-board-1',
      order_index: index + 1,
      description,
      action,
      camera: { shot_size: size, movement: index === 0 ? '缓慢推进' : '固定镜头', angle: '平视' },
      duration_seconds: duration,
      scene_id,
      characters: people,
      dialogue: index === 3 ? [{ character: '苏晚', text: '有些话，只是晚一点才送到。' }] : [],
      visual_prompt: `${description}，雨夜暖光，低饱和电影质感，16:9`,
      negative_prompt: '',
      status: 'pending_review',
      approved: false,
      image_url: demoArtwork(
        `镜头 ${String(index + 1).padStart(2, '0')} · ${size}`,
        'scene',
        index === 0 ? 'blue' : 'amber',
      ),
    }),
  );
  const script = {
    id: 'demo-script-1',
    project_id: projects[0].id,
    version: 1,
    title: '雨夜书店',
    script_text:
      '第一场　外景·旧书店门前·雨夜\n\n雨落在橱窗上。街巷空荡，书店的灯还亮着。林简在窗后收拾最后一摞书。\n\n第二场　内景·书店主厅·夜\n\n一封旧信从书中滑落。林简拾起信封，认出父亲的字迹，停下了动作。门铃响起，苏晚推门而入。\n\n苏晚：还没打烊？\n林简：今天，是最后一天。\n\n第三场　内景·书店后屋·深夜\n\n两人在台灯下展开信纸。苏晚轻轻抚平折痕，林简望着父亲的旧照片。\n\n苏晚：有些话，只是晚一点才送到。\n\n林简沉默片刻，走向门边，翻转营业牌。灯光重新照亮橱窗。\n\n林简：那就再开一天吧。',
    workspace_meta: { source: 'manual', base_script_id: null, requires_reconfirmation: true },
    logline: projects[0].description,
    synopsis:
      '林简打算在雨夜关闭经营了三十年的旧书店。清理旧书时，一封父亲从未寄出的信落在他脚边。修书师苏晚恰好来访，陪他读完信中未说出口的思念。天亮以前，林简做出了新的决定。',
    genre: '剧情',
    tone: '克制而温暖',
    status: 'approved',
    approved: true,
    created_at: DEMO_TIME,
    content: {
      chapters: [
        { chapter_index: 1, title: '最后一个营业日', summary: '一封旧信改变了林简关店的决定。' },
      ],
      events: [
        '林简整理旧书，准备关店。',
        '旧信从书中滑落。',
        '苏晚雨夜来访，两人一起读信。',
        '林简重新挂起营业牌。',
      ],
      dialogues: [
        { character: '苏晚', text: '有些话，只是晚一点才送到。' },
        { character: '林简', text: '那就再开一天吧。' },
      ],
    },
  };
  const review = {
    id: 'demo-review-storyboard',
    project_id: projects[0].id,
    workflow_run_id: 'demo-run-1',
    stage: 'storyboard',
    target_type: 'storyboard',
    target_id: 'demo-board-1',
    status: 'pending',
    comment: '',
    decision: {},
    reviewer_id: null,
    reviewed_at: null,
    created_at: DEMO_TIME,
    comments: [],
    title: '分镜设计待审核',
    description: '6 个镜头已整理完成，请确认节奏、构图和人物连续性。',
  };
  const tasks = [
    {
      id: 'demo-task-storyboard',
      project_id: projects[0].id,
      type: 'storyboard',
      status: 'succeeded',
      progress: 1,
      message: '分镜示例已完成，等待人工审核',
      result: { storyboard_id: 'demo-board-1', shot_count: 6 },
      created_at: DEMO_TIME,
      started_at: DEMO_TIME,
      finished_at: DEMO_TIME,
      error: null,
    },
    {
      id: 'demo-task-characters',
      project_id: projects[0].id,
      type: 'characters',
      status: 'succeeded',
      progress: 1,
      message: '人物与场景示例已确认',
      result: {},
      created_at: DEMO_TIME,
      started_at: DEMO_TIME,
      finished_at: DEMO_TIME,
      error: null,
    },
  ];
  const workflow = {
    id: 'demo-run-1',
    project_id: projects[0].id,
    workflow_id: 'novel_to_video',
    workflow_name: '小说到短片',
    status: 'awaiting_review',
    current_node: 'review_storyboard',
    next_index: 8,
    created_at: DEMO_TIME,
    updated_at: DEMO_TIME,
    progress: 0.62,
    demo: true,
    nodes: [
      { id: 'script', name: '剧本解析', status: 'succeeded' },
      { id: 'characters', name: '人物设定', status: 'succeeded' },
      { id: 'scenes', name: '场景设定', status: 'succeeded' },
      { id: 'directing', name: '导演规划', status: 'succeeded' },
      { id: 'storyboard', name: '分镜设计', status: 'awaiting_review' },
      { id: 'video', name: '视频生成', status: 'pending' },
      { id: 'audio', name: '声音设计', status: 'pending' },
      { id: 'editing', name: '剪辑合成', status: 'pending' },
      { id: 'evaluation', name: '成片评估', status: 'pending' },
    ],
  };
  const assets = [
    ...characters.map((item) => ({
      id: `asset-${item.id}`,
      project_id: projects[0].id,
      kind: 'character_portrait',
      filename: `${item.name} · 形象示例`,
      url: item.image_url,
      image_url: item.image_url,
      mime_type: 'image/svg+xml',
      meta: { character_id: item.id },
      demo: true,
      created_at: DEMO_TIME,
    })),
    ...scenes.map((item) => ({
      id: `asset-${item.id}`,
      project_id: projects[0].id,
      kind: 'scene_reference',
      filename: `${item.name} · 氛围示例`,
      url: item.image_url,
      image_url: item.image_url,
      mime_type: 'image/svg+xml',
      meta: { scene_id: item.id },
      demo: true,
      created_at: DEMO_TIME,
    })),
  ];
  const summary = {
    project_id: projects[0].id,
    name: projects[0].name,
    language: 'zh',
    genre: '剧情',
    status: 'awaiting_review',
    script_version: 1,
    script_title: script.title,
    logline: script.logline,
    synopsis: script.synopsis,
    directing_plan_version: 1,
    visual_style: '低饱和雨夜 / 旧书店暖光',
    storyboard_version: 1,
    shot_count: shots.length,
    characters: characters.map((item) => item.name),
    scenes: scenes.map((item) => item.name),
    total_duration_seconds: 35,
    demo: true,
    progress: 0.62,
  };
  const dashboard = {
    project: projects[0],
    summary,
    workflow,
    pending_reviews: [review],
    tasks,
    editing: null,
    film: null,
    evaluation: null,
    demo: true,
    progress: 0.62,
  };
  // 静态导演规划示例：用于展示模块 4，不表示真实模型已经执行。
  const directingPlan = {
    id: 'demo-directing-plan-1',
    version: 1,
    status: 'draft',
    approved: false,
    agent_id: 'director',
    model_id: '示例配置',
    config_version: 'demo-1',
    prompt_version: 'demo-1',
    created_at: DEMO_TIME,
    demo: true,
    project_id: projects[0].id,
    source_status: 'current',
    source_script: {
      id: script.id,
      version: script.version,
      title: script.title,
      fingerprint: 'demo',
    },
    content: {
      visual_style: '克制的写实短片，雨夜冷色与书店暖光构成情绪对照',
      color_palette: ['#27343b', '#a68960', '#e2d7bd'],
      lighting_style: '台灯与橱窗暖光为主，街道保留柔和冷色雨光',
      camera_language: '以稳定构图与缓慢推进陪伴人物，重要物件使用近景',
      pacing: '前段留白，中段对话沉静，结尾略微舒展',
      narrative_arc: '从告别的克制，经由旧信触及回忆，转向重新开始的温暖',
      shot_strategy: {
        total_shots: 6,
        avg_duration_seconds: 5.8,
        pacing_notes: '读信时保留呼吸，翻转营业牌后多停留一拍',
        coverage_notes: '覆盖街巷、信封、双人关系及父亲回忆，避免无依据增加情节',
      },
      continuity_rules: [
        '林简始终佩戴旧腕表',
        '雨夜光线与服装保持一致',
        '信封和书店陈设延续已确认设定',
      ],
      scenes_order: ['雨夜街巷', '旧书店主厅', '书店后屋', '主厅回忆与结尾'],
      notes: '静态演示方案，所有创作选择均需创作者核对。',
      mood: '安静、怀旧，由微凉转向温暖',
      source_script: {
        id: script.id,
        version: script.version,
        title: script.title,
        fingerprint: 'demo',
      },
    },
  };
  // 这些来源和审核快照只描述内存示例，不能当成真实模型或真实审批的证据。
  const storyboard = {
    id: 'demo-board-1',
    project_id: projects[0].id,
    version: 1,
    status: 'pending_review',
    approved: false,
    title: '雨夜书店分镜',
    notes: '静态演示分镜',
    directing_plan_id: directingPlan.id,
    source_script: directingPlan.source_script,
    source_status: 'current',
    created_at: DEMO_TIME,
    shots,
    demo: true,
  };
  for (const shot of shots) {
    shot.storyboard_id = storyboard.id;
    shot.edit_fingerprint = `demo-${shot.id}-1`;
  }
  const storyboardSnapshot = {
    storyboard_id: storyboard.id,
    storyboard_version: 1,
    directing_plan_id: directingPlan.id,
    source_script: directingPlan.source_script,
    storyboard_fingerprint: 'demo',
    shot_fingerprints: Object.fromEntries(shots.map((shot) => [shot.id, shot.edit_fingerprint])),
  };
  Object.assign(review, {
    target_snapshot: storyboardSnapshot,
    target_status: 'current',
    decision: { storyboard_snapshot: storyboardSnapshot },
  });
  const workspaces = {
    [projects[0].id]: {
      project: projects[0],
      dashboard,
      summary,
      workflow,
      pending_reviews: [review],
      reviews: [review],
      tasks,
      script,
      scripts: [script],
      characters,
      scenes,
      shots,
      assets,
      directing: directingPlan,
      directing_versions: [directingPlan],
      storyboard,
      storyboard_versions: [storyboard],
      editing: null,
      evaluation: null,
      documents: [
        {
          id: 'demo-document-1',
          project_id: projects[0].id,
          title: '雨夜书店.txt',
          filename: '雨夜书店.txt',
          status: 'parsed',
          created_at: DEMO_TIME,
        },
      ],
      chapters: [
        {
          id: 'demo-chapter-1',
          chapter_index: 1,
          title: '最后一个营业日',
          content: script.synopsis,
        },
      ],
      activities: [
        {
          id: 'activity-1',
          title: '分镜设计完成',
          description: '6 个镜头等待你的审核',
          created_at: DEMO_TIME,
          type: 'review',
        },
        {
          id: 'activity-2',
          title: '人物与场景设定已确认',
          description: '3 位人物 · 3 个场景',
          created_at: DEMO_TIME,
          type: 'completed',
        },
      ],
      agentCatalog: copy(AGENT_CATALOG),
      demo: true,
    },
  };
  for (const item of projects.slice(1)) {
    const info = {
      project_id: item.id,
      name: item.name,
      status: item.status,
      shot_count: 0,
      characters: [],
      scenes: [],
      total_duration_seconds: 0,
      demo: true,
      progress: item.progress,
    };
    const board = {
      project: item,
      summary: info,
      workflow: null,
      pending_reviews: [],
      tasks: [],
      editing: null,
      film: null,
      evaluation: null,
      demo: true,
      progress: item.progress,
    };
    workspaces[item.id] = {
      project: item,
      dashboard: board,
      summary: info,
      workflow: null,
      pending_reviews: [],
      reviews: [],
      tasks: [],
      script: null,
      characters: [],
      scenes: [],
      shots: [],
      assets: [],
      documents: [],
      chapters: [],
      activities: [],
      agentCatalog: copy(AGENT_CATALOG),
      demo: true,
    };
  }
  const agentConfigs = AGENT_CATALOG.flatMap((family) =>
    family.agent_ids.map((id) => ({
      id,
      name: family.name,
      description: family.description,
      enabled: true,
      provider: 'demo',
      model_id: 'demo-preview',
      capability: ['video', 'character_image', 'audio'].includes(family.id)
        ? family.id
        : 'text_reasoning',
      active_version: 0,
      config_version: 'demo-1',
      payload: {
        agent: {
          id,
          name: family.name,
          enabled: true,
          version: '1.0.0',
          description: family.description,
        },
        model: { provider: 'demo', model_id: 'demo-preview', capability: 'text_reasoning' },
        generation: {
          temperature: 0.4,
          max_output_tokens: 4096,
          timeout_seconds: 120,
          max_retries: 2,
        },
        runtime: { concurrency: 1, human_review_required: true },
        prompt: { version: '1.0.0' },
      },
      versions: [],
    })),
  );
  return {
    projects,
    workspaces,
    agentConfigs,
    taskEvents: {},
    sequence: 0,
    providers: [
      {
        id: 'demo',
        name: '演示环境',
        type: 'demo',
        has_api_key: false,
        enabled: true,
        description: '所有结果来自页面内存中的示例，不调用任何模型。',
      },
    ],
    meta: {
      app: 'AI Film Studio',
      env: 'demo',
      storage_backend: 'memory',
      default_workflow: 'novel_to_video',
      agents: agentConfigs.map((item) => item.id),
      workflows: [{ id: 'novel_to_video', name: '小说到短片', version: '1.0.0' }],
      config_versions: { demo: '1' },
    },
  };
}
