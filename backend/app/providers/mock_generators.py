"""Deterministic offline generators behind the mock providers.

These make the full pipeline runnable with no credentials: novel parsing,
character/scene extraction, directing, storyboard, evaluation.  Output is derived
strictly from the prompt variables supplied by the calling agent, so it behaves
like a (very small) deterministic model rather than a canned fixture.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.utils import narrative


def _rng(text: str, low: float, high: float) -> float:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    ratio = int(digest[:8], 16) / 0xFFFFFFFF
    return round(low + (high - low) * ratio, 3)


def _chapters(variables: dict[str, Any]) -> list[dict]:
    return list(variables.get("chapters") or variables.get("chapter_texts") or [])


def _all_text(chapters: list[dict]) -> str:
    return "\n\n".join(str(chapter.get("content", "")) for chapter in chapters)


def _script_summary(variables: dict[str, Any]) -> dict:
    return dict(variables.get("script") or {})


# --------------------------------------------------------------------- script
def generate_script(variables: dict[str, Any]) -> dict:
    chapters = _chapters(variables)
    title_hint = variables.get("title_hint") or ""
    genre = variables.get("genre") or "剧情"

    all_text = _all_text(chapters)
    chapter_summaries = []
    events = []
    dialogues: list[dict] = []
    known_names = narrative.extract_character_names(all_text, limit=8)
    for chapter in chapters:
        content = str(chapter.get("content", ""))
        index = int(chapter.get("index") or len(chapter_summaries) + 1)
        chapter_title = str(chapter.get("title") or f"第{index}章")
        summary = narrative.summarize(content, 160)
        chapter_summaries.append({"index": index, "title": chapter_title, "summary": summary})
        names = narrative.extract_character_names(content, limit=4)
        locations = narrative.extract_locations(content, limit=1)
        events.append(
            {
                "title": chapter_title,
                "description": summary or "（本章内容较少）",
                "chapter_index": index,
                "characters": names,
                "location": locations[0] if locations else "",
                "importance": 0.6 if index == 1 else 0.5,
            }
        )
        dialogues.extend(
            narrative.extract_dialogues(content, chapter_index=index, known_names=known_names)
        )

    title = title_hint or (chapter_summaries[0]["title"] if chapter_summaries else "未命名故事")
    key_names = known_names
    logline = narrative.summarize(events[0]["description"], 80) if events else ""
    return {
        "title": title,
        "logline": logline or f"一个关于{key_names[0] if key_names else '主角'}的故事",
        "synopsis": narrative.summarize(all_text, 300),
        "genre": genre,
        "tone": "写实" if "现实" in all_text else "叙事",
        "chapters": chapter_summaries,
        "events": events,
        "dialogues": dialogues[:60],
    }


# ----------------------------------------------------------------- character
def generate_character_extraction(variables: dict[str, Any]) -> dict:
    chapters = _chapters(variables)
    text = _all_text(chapters)
    script = _script_summary(variables)
    script_dialogues = script.get("dialogues") or []

    counts: dict[str, int] = {}
    evidence: dict[str, str] = {}
    for chapter in chapters:
        content = str(chapter.get("content", ""))
        for name in narrative.extract_character_names(content, limit=6):
            counts[name] = counts.get(name, 0) + 1
            if name not in evidence:
                for sentence in narrative.split_sentences(content):
                    if name in sentence:
                        evidence[name] = sentence[:120]
                        break
    for line in script_dialogues:
        speaker = (line.get("character_name") or "").strip()
        if speaker and speaker != "未知":
            counts[speaker] = counts.get(speaker, 0) + 1
            evidence.setdefault(speaker, line.get("text", "")[:120])

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    characters = []
    for position, (name, count) in enumerate(ranked):
        snippet = evidence.get(name, "")
        if position == 0:
            role = "protagonist"
        elif position == 1 and len(ranked) > 1:
            role = "antagonist"
        else:
            role = "supporting"
        characters.append(
            {
                "name": name,
                "aliases": [],
                "role_hint": role,
                "gender_hint": narrative.guess_gender(text),
                "age_hint": "",
                "evidence": snippet or f"{name} 在故事中被多次提及（{count} 次）",
            }
        )
    if not characters:
        characters.append(
            {
                "name": "主角",
                "aliases": [],
                "role_hint": "protagonist",
                "gender_hint": "unknown",
                "age_hint": "",
                "evidence": "原文未识别出明确人名，按主角占位创建",
            }
        )

    relationships = []
    protagonist = characters[0]["name"]
    for candidate in characters[1:]:
        if not narrative.split_sentences(text):
            break
        relationships.append(
            {
                "source": protagonist,
                "target": candidate["name"],
                "relation": "同场出现",
                "description": f"{protagonist} 与 {candidate['name']} 在原文中同时出现",
            }
        )
    return {"characters": characters, "relationships": relationships[:6]}


def generate_character_profile(variables: dict[str, Any]) -> dict:
    name = str(variables.get("name") or "角色")
    evidence = [str(item) for item in variables.get("evidence") or []]
    context = "\n".join(evidence)
    chapters = _chapters(variables)
    if not context:
        context = _all_text(chapters)[:1200]
    gender = narrative.guess_gender(context)
    visual_words = []
    for keyword in ("长发", "短发", "白衣", "黑衣", "长袍", "西装", "刀", "剑", "眼镜", "伤疤", "斗篷"):
        if keyword in context:
            visual_words.append(keyword)
    appearance = (
        f"{name}的公开形象：{('、'.join(visual_words)) if visual_words else '衣着整洁、神情克制'}。"
        f"原文未给出完整外貌描写，需人工确认后固化。"
    )
    facts = [line[:100] for line in evidence[:4]]
    return {
        "name": name,
        "aliases": [],
        "gender": gender,
        "age_range": "20-30",
        "role_type": "protagonist" if name else "supporting",
        "appearance": appearance,
        "hairstyle": "短发" if "短发" in context else "中长发",
        "body": "中等身形",
        "clothing_default": "、".join(visual_words[:3]) or "日常便装",
        "personality": ["克制", "敏锐"] if "冷" in context else ["温和", "坚定"],
        "background": narrative.summarize(context, 120) or f"{name}的来历尚待补充。",
        "motivation": "查明真相" if "真相" in context else "守护在意的人",
        "speech_style": "简短克制" if "冷" in context else "自然口语",
        "visual_keywords": visual_words or ["自然光", "写实风格"],
        "source_facts": facts or ["原文信息有限"],
        "inferred_items": ["年龄区间为推断值", "服装细节需人工确认"],
    }


def generate_character_vision(variables: dict[str, Any]) -> dict:
    filename = variables.get("filename") or "uploaded_image"
    width = int(variables.get("image_width") or 0)
    height = int(variables.get("image_height") or 0)
    known_name = variables.get("known_name") or "未命名角色"
    mode = variables.get("image_mode") or "RGB"
    return {
        "summary": f"参考图 {filename}（{width}x{height}，{mode}）。离线视觉分析仅记录技术特征，"
        f"正式环境接入视觉模型后可获得外貌细节。",
        "gender": "unknown",
        "age_range": "",
        "hair": "",
        "face": "",
        "body": f"画面比例 {width}:{height}" if width and height else "",
        "clothing": "",
        "accessories": [],
        "visual_keywords": [known_name, "参考图", "写实风格"],
        "confidence": 0.4,
    }


# --------------------------------------------------------------------- scene
def generate_scene_extraction(variables: dict[str, Any]) -> dict:
    chapters = _chapters(variables)
    scenes: list[dict] = []
    seen: set[str] = set()
    for chapter in chapters:
        content = str(chapter.get("content", ""))
        locations = narrative.extract_locations(content, limit=3)
        title = str(chapter.get("title") or f"第{chapter.get('index', 1)}章")
        if not locations:
            locations = [f"{title}场景"]
        for location in locations:
            if location in seen:
                continue
            seen.add(location)
            scenes.append(
                {
                    "name": location,
                    "chapter_index": chapter.get("index"),
                    "time_of_day": "夜晚" if "夜" in content else "白天",
                    "environment": narrative.summarize(content, 100) or f"{location}的内景",
                    "architecture": "室内空间" if "屋" in location or "房" in location else "室外空间",
                    "lighting": "低照度冷光" if "夜" in content else "自然光",
                    "mood": "紧张" if "紧张" in content or "危险" in content else "平静",
                    "evidence": narrative.summarize(content, 80),
                }
            )
    if not scenes:
        scenes.append(
            {
                "name": "主场景",
                "chapter_index": 1,
                "time_of_day": "白天",
                "environment": "原文未提供明确地点，按通用场景处理",
                "architecture": "未指定",
                "lighting": "自然光",
                "mood": "平静",
                "evidence": "",
            }
        )
    # Per-chapter extraction can yield fragments of the same place; keep the
    # longest spelling so "书店" does not duplicate "旧书店".
    keep = set(narrative.dedupe_locations([item["name"] for item in scenes]))
    scenes = [item for item in scenes if item["name"] in keep]
    return {"scenes": scenes[:8]}


def generate_scene_profile(variables: dict[str, Any]) -> dict:
    name = str(variables.get("name") or "场景")
    evidence = str(variables.get("evidence") or "")
    time_of_day = variables.get("time_of_day") or ("夜晚" if "夜" in evidence else "白天")
    mood = variables.get("mood") or "平静"
    description = narrative.summarize(evidence, 140) or f"{name}的基础场景描述。"
    return {
        "name": name,
        "description": description,
        "time_of_day": time_of_day,
        "environment": description,
        "architecture": variables.get("architecture") or "未指定建筑风格",
        "lighting": "低照度冷光" if time_of_day == "夜晚" else "自然侧光",
        "mood": mood,
        "palette": ["#1b2a41", "#4a6785"] if time_of_day == "夜晚" else ["#c9d6df", "#8aa1b1"],
        "props": ["门", "桌"] if "屋" in name else ["天空", "地面"],
        "visual_prompt": f"{name}，{time_of_day}，{description}，电影感画面，宽银幕构图",
        "negative_prompt": "低清晰度，文字水印，畸形结构",
    }


# ------------------------------------------------------------------- director
def generate_directing_plan(variables: dict[str, Any]) -> dict:
    script = _script_summary(variables)
    events = script.get("events") or []
    characters = list(variables.get("characters") or [])
    scenes = list(variables.get("scenes") or [])
    target_shots = int(variables.get("shots_target") or 0) or max(4, min(12, len(events) * 2 or 4))
    genre = script.get("genre") or variables.get("genre") or "剧情"
    return {
        "visual_style": f"{genre}写实电影风格，克制色调，强调人物关系与空间层次",
        "color_palette": ["#1b2a41", "#4a6785", "#d9c6a5"],
        "lighting_style": "以自然光为主，夜景使用低照度冷光与局部暖光对比",
        "camera_language": "以中景与近景为主，关键情绪点使用缓慢推镜，避免无动机的剧烈运镜",
        "pacing": "前段平缓铺垫，中段逐步加快，结尾留白",
        "narrative_arc": narrative.summarize(script.get("synopsis", ""), 120) or "起承转合完整",
        "shot_strategy": {
            "total_shots": target_shots,
            "avg_duration_seconds": 5.0,
            "pacing_notes": "每 1-2 个事件至少一个近景以交代情绪",
            "coverage_notes": "对话镜头采用正反打，动作镜头保留全景与近景各一",
        },
        "continuity_rules": [
            "同一场景内光线方向保持一致",
            "人物服装与人物档案默认造型一致",
            "相邻镜头运动方向遵循 180 度轴线规则",
        ],
        "scenes_order": [scene.get("name", "") for scene in scenes][:10],
        "notes": f"共识别 {len(characters)} 个角色、{len(scenes)} 个场景，目标镜头数 {target_shots}。",
    }


# ---------------------------------------------------------------- storyboard
_CAMERA_ROTATION = [
    {"shot_type": "wide_shot", "movement": "static", "angle": "eye_level"},
    {"shot_type": "medium_shot", "movement": "slow_dolly_in", "angle": "eye_level"},
    {"shot_type": "close_up", "movement": "static", "angle": "eye_level"},
    {"shot_type": "medium_shot", "movement": "pan_left", "angle": "slightly_low"},
    {"shot_type": "over_the_shoulder", "movement": "handheld_follow", "angle": "eye_level"},
]


def generate_storyboard(variables: dict[str, Any]) -> dict:
    script = _script_summary(variables)
    events = list(script.get("events") or [])
    dialogues = list(script.get("dialogues") or [])
    characters = list(variables.get("characters") or [])
    scenes = list(variables.get("scenes") or [])
    plan = dict(variables.get("plan") or {})
    style = plan.get("visual_style") or "电影感写实风格"
    shot_strategy = plan.get("shot_strategy") or {}
    target_shots = int(shot_strategy.get("total_shots") or variables.get("shots_target") or 0)
    max_shots = max(1, target_shots or max(1, min(10, len(events) * 2)))

    if not events:
        events = [{"title": "开场", "description": script.get("synopsis", "故事开场"), "characters": []}]

    name_to_character = {str(item.get("name")): item for item in characters}
    scene_names = [str(item.get("name")) for item in scenes] or [""]

    shots: list[dict] = []
    order = 0
    for event_index, event in enumerate(events):
        if len(shots) >= max_shots:
            break
        scene_name = str(event.get("location") or scene_names[event_index % len(scene_names)])
        event_characters = [name for name in (event.get("characters") or []) if name in name_to_character]
        if not event_characters and characters:
            event_characters = [str(characters[order % len(characters)].get("name"))]
        event_dialogues = [
            line
            for line in dialogues
            if line.get("chapter_index") == event.get("chapter_index")
            or line.get("character_name") in event_characters
        ]
        shots_for_event = 1 if order >= max_shots - 1 else 2
        for part in range(shots_for_event):
            if len(shots) >= max_shots:
                break
            camera = dict(_CAMERA_ROTATION[order % len(_CAMERA_ROTATION)])
            shot_characters = []
            for character_name in event_characters[:2]:
                shot_characters.append(
                    {
                        "character_id": "",
                        "character_name": character_name,
                        "costume_id": None,
                        "state_id": None,
                        "action": event.get("description", "")[:60],
                        "emotion": narrative.emotion_from_context(str(event.get("description", ""))),
                    }
                )
            shot_dialogue = []
            for line in event_dialogues[:2] if part == 1 or len(event_dialogues) <= 2 else event_dialogues[:1]:
                shot_dialogue.append(
                    {
                        "character_id": "",
                        "character_name": line.get("character_name") or "",
                        "text": line.get("text") or "",
                        "emotion": line.get("emotion") or "",
                    }
                )
            visual_prompt = (
                f"{style}，{scene_name}，{event.get('description', '')[:80]}，"
                f"{camera['shot_type']}，{camera['movement']}，"
                + "，".join(character["character_name"] for character in shot_characters)
            ).strip("，")
            shots.append(
                {
                    "temp_id": f"shot_{len(shots) + 1:03d}",
                    "scene_name": scene_name,
                    "order": len(shots) + 1,
                    "description": f"{event.get('title', '')}：{event.get('description', '')[:100]}",
                    "characters": shot_characters,
                    "camera": camera,
                    "duration_seconds": float(shot_strategy.get("avg_duration_seconds") or 5.0),
                    "dialogue": shot_dialogue,
                    "action": event.get("description", "")[:120],
                    "visual_prompt": visual_prompt,
                    "negative_prompt": "模糊，畸变，文字水印，多余肢体",
                    "reference_asset_ids": [],
                }
            )
            order += 1

    return {
        "title": script.get("title") or "分镜表",
        "shots": shots,
        "notes": f"由导演规划拆解，共 {len(shots)} 个镜头。",
    }


# -------------------------------------------------------------------- prompt
def generate_prompt_pack(variables: dict[str, Any]) -> dict:
    shot = dict(variables.get("shot") or {})
    style = str(variables.get("visual_style") or "电影感写实风格")
    character_tokens = [str(item.get("character_name")) for item in shot.get("characters") or [] if item.get("character_name")]
    camera = shot.get("camera") or {}
    return {
        "visual_prompt": (
            f"{style}，{shot.get('description', '')}，{camera.get('shot_type', 'medium_shot')}，"
            f"{camera.get('movement', 'static')}，{camera.get('angle', 'eye_level')}，"
            f"人物：{'、'.join(character_tokens) or '无'}，电影感灯光，高细节"
        ),
        "negative_prompt": str(shot.get("negative_prompt") or "模糊，畸变，文字水印，多余肢体"),
        "style_tokens": ["cinematic", "film grain", "shallow depth of field"],
        "camera_tokens": [camera.get("shot_type", "medium_shot"), camera.get("movement", "static")],
        "character_tokens": character_tokens,
    }


# --------------------------------------------------------------- consistency
def generate_consistency(variables: dict[str, Any]) -> dict:
    character_id = str(variables.get("character_id") or "")
    checked_assets = int(variables.get("checked_assets") or 0)
    issues = []
    score = 0.88
    if checked_assets == 0:
        score = 0.65
        issues.append(
            {
                "type": "missing_assets",
                "severity": "medium",
                "description": "该角色尚无已批准的形象资产，一致性无法验证",
            }
        )
    return {
        "character_id": character_id,
        "overall_score": score,
        "checked_assets": checked_assets,
        "issues": issues,
        "recommendation": "accept" if score >= 0.75 else "regenerate",
    }


# ------------------------------------------------------------------- audio
def generate_audio_plan(variables: dict[str, Any]) -> dict:
    shots = list(variables.get("shots") or [])
    synopsis = str(variables.get("synopsis") or "")
    voice_lines = []
    for shot in shots:
        for line_index, line in enumerate(shot.get("dialogue") or []):
            text = str(line.get("text") or "").strip()
            if not text:
                continue
            character_name = str(line.get("character_name") or "未知")
            voice_lines.append(
                {
                    "line_id": f"{shot.get('shot_id', 'shot')}_line{line_index + 1}",
                    "character_name": character_name,
                    "text": text,
                    "emotion": str(line.get("emotion") or ""),
                    "duration_seconds": narrative.estimate_speech_duration(text),
                    "shot_id": shot.get("shot_id", ""),
                }
            )
    narration = narrative.summarize(synopsis, 120) if synopsis else ""
    return {
        "narration": narration,
        "voice_lines": voice_lines,
        "music_cue": "低沉弦乐铺底，音量低于人声" if voice_lines else "轻柔环境音",
        "sfx_cues": ["环境底噪"] if shots else [],
    }


# ----------------------------------------------------------------- editing
def generate_editing_plan(variables: dict[str, Any]) -> dict:
    shots = list(variables.get("shots") or [])
    timeline = []
    cursor = 0.0
    for index, shot in enumerate(shots):
        duration = float(shot.get("duration_seconds") or 5.0)
        timeline.append(
            {
                "clip_id": f"clip_{index + 1:03d}",
                "shot_id": str(shot.get("shot_id") or ""),
                "order": index + 1,
                "start": round(cursor, 2),
                "duration": duration,
                "video_asset_id": shot.get("video_asset_id") or None,
                "audio_asset_id": shot.get("audio_asset_id") or None,
                "transition": "cut" if index else "fade_in",
            }
        )
        cursor += duration
    return {
        "timeline": timeline,
        "subtitles": True,
        "total_duration": round(cursor, 2),
        "notes": f"{len(timeline)} 个镜头按叙事顺序排列。",
    }


# -------------------------------------------------------------- evaluation
def generate_evaluation(variables: dict[str, Any]) -> dict:
    metrics = dict(variables.get("metrics") or {})
    stage = str(variables.get("stage") or "final")
    has_video = bool(metrics.get("shots_with_video"))
    has_audio = bool(metrics.get("audio_tracks"))
    has_subtitles = bool(metrics.get("subtitles"))
    character_score = float(metrics.get("character_consistency") or 0.85)
    scores = {
        "story_consistency": _rng(f"story{stage}", 0.82, 0.95),
        "character_consistency": round(character_score, 3),
        "scene_consistency": _rng(f"scene{stage}", 0.8, 0.93),
        "motion_quality": _rng(f"motion{stage}", 0.78, 0.92) if has_video else 0.0,
        "visual_quality": _rng(f"visual{stage}", 0.8, 0.94),
        "audio_quality": _rng(f"audio{stage}", 0.8, 0.95) if has_audio else 0.0,
    }
    issues = []
    if not has_video:
        issues.append(
            {"type": "missing_video", "severity": "high", "description": "部分镜头缺少视频候选"}
        )
    if not has_audio:
        issues.append(
            {"type": "missing_audio", "severity": "medium", "description": "尚未生成配音或旁白"}
        )
    if not has_subtitles:
        issues.append(
            {"type": "missing_subtitles", "severity": "low", "description": "尚未生成字幕文件"}
        )
    overall = round(sum(scores.values()) / max(1, len([value for value in scores.values() if value])), 3)
    return {
        "overall_score": overall,
        "scores": scores,
        "issues": issues,
        "recommendation": "accept" if overall >= 0.8 and not any(i["severity"] == "high" for i in issues) else "review",
        "summary": f"{stage} 阶段质量评估完成，整体得分 {overall}。",
    }


# ------------------------------------------------------------ orchestrator
def generate_orchestrator_plan(variables: dict[str, Any]) -> dict:
    objective = str(variables.get("objective") or "把小说制作成短视频")
    return {
        "objective": objective,
        "nodes": [
            {"node_id": "analyze_script", "purpose": "解析章节并生成结构化剧本", "agent": "script"},
            {"node_id": "extract_characters", "purpose": "提取人物及人物关系", "agent": "character_extraction"},
            {"node_id": "extract_scenes", "purpose": "提取场景与视觉描述", "agent": "scene"},
            {"node_id": "direct", "purpose": "制定导演规划", "agent": "director"},
            {"node_id": "storyboard", "purpose": "拆解镜头", "agent": "storyboard"},
            {"node_id": "generate_shots", "purpose": "生成镜头视频", "agent": "video"},
            {"node_id": "generate_audio", "purpose": "生成配音与字幕", "agent": "audio"},
            {"node_id": "edit", "purpose": "剪辑合成", "agent": "editing"},
        ],
        "review_stages": ["characters_scenes", "storyboard", "shots", "final"],
        "notes": "按人工审核节点暂停，审核通过后继续。",
    }


GENERATORS = {
    "script": generate_script,
    "character_extraction": generate_character_extraction,
    "character_profile": generate_character_profile,
    "character_vision": generate_character_vision,
    "scene_extraction": generate_scene_extraction,
    "scene_profile": generate_scene_profile,
    "directing_plan": generate_directing_plan,
    "storyboard": generate_storyboard,
    "prompt_pack": generate_prompt_pack,
    "character_consistency": generate_consistency,
    "audio_plan": generate_audio_plan,
    "editing_plan": generate_editing_plan,
    "evaluation": generate_evaluation,
    "orchestrator_plan": generate_orchestrator_plan,
}


def generate(schema_name: str, variables: dict[str, Any]) -> dict:
    generator = GENERATORS.get(schema_name)
    if generator is None:
        raise KeyError(f"No offline generator registered for schema '{schema_name}'")
    return generator(variables)
