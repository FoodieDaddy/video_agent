"""Story pipeline services: script, characters, scenes, directing, storyboard.

Each stage is a *pure* function over the current project state: it reads the
latest approved-ish artifacts, calls one or more agents through
:func:`app.services.agent_runner.run_agent`, then persists new immutable
versions.  Nothing here knows about HTTP or about the workflow engine, which
keeps stages independently testable and reusable from the API.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import CharacterStatus, ProjectStatus, ShotStatus
from app.core.exceptions import WorkflowError
from app.core.ids import new_id
from app.models.character import Character, CharacterProfile, CharacterRelationship
from app.models.ops import Task
from app.models.production import DirectingPlan, Shot, ShotCharacter, Storyboard
from app.models.project import Project
from app.models.scene import Scene, SceneProfile
from app.models.story import Script, SourceDocument, StoryEvent
from app.schemas.character import CharacterDescriptionInput, CharacterExtractionInput
from app.schemas.director import DirectingPlanInput
from app.schemas.prompt import PromptInput
from app.schemas.scene import SceneDescriptionInput, SceneExtractionInput
from app.schemas.script import ScriptInput
from app.schemas.storyboard import StoryboardInput
from app.services import documents
from app.services.agent_runner import run_agent
from app.services.projects import touch_status
from app.services.runtime import AppRuntime

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- queries
def latest_script(db: Session, project_id: str) -> Script | None:
    return db.scalar(
        select(Script).where(Script.project_id == project_id).order_by(Script.version.desc())
    )


def latest_plan(db: Session, project_id: str) -> DirectingPlan | None:
    return db.scalar(
        select(DirectingPlan)
        .where(DirectingPlan.project_id == project_id)
        .order_by(DirectingPlan.version.desc())
    )


def latest_board(db: Session, project_id: str) -> Storyboard | None:
    return db.scalar(
        select(Storyboard)
        .where(Storyboard.project_id == project_id)
        .order_by(Storyboard.version.desc())
    )


def list_characters(db: Session, project_id: str) -> list[Character]:
    return list(
        db.scalars(
            select(Character)
            .where(Character.project_id == project_id)
            .order_by(Character.created_at, Character.name)
        )
    )


def list_scenes(db: Session, project_id: str) -> list[Scene]:
    return list(
        db.scalars(
            select(Scene).where(Scene.project_id == project_id).order_by(Scene.created_at, Scene.name)
        )
    )


def list_shots(db: Session, project_id: str, *, board: Storyboard | None = None) -> list[Shot]:
    board = board or latest_board(db, project_id)
    if board is None:
        return []
    return list(
        db.scalars(
            select(Shot).where(Shot.storyboard_id == board.id).order_by(Shot.order_index)
        )
    )


def profile_of(db: Session, character: Character) -> CharacterProfile | None:
    if not character.canonical_profile_id:
        return None
    return db.get(CharacterProfile, character.canonical_profile_id)


def scene_profile_of(db: Session, scene: Scene) -> SceneProfile | None:
    if not scene.canonical_profile_id:
        return None
    return db.get(SceneProfile, scene.canonical_profile_id)


def _next_version(db: Session, column, model, project_id: str) -> int:
    current = db.scalar(select(func.max(column)).where(model.project_id == project_id))
    return int(current or 0) + 1


# -------------------------------------------------------------------- payloads
def script_payload(script: Script | None) -> dict:
    if script is None:
        return {}
    return {
        "id": script.id,
        "version": script.version,
        "title": script.title,
        "logline": script.logline,
        "synopsis": script.synopsis,
        "genre": script.genre,
        "tone": script.tone,
        "content": script.content or {},
        "approved": script.approved,
    }


def character_payload(db: Session, character: Character) -> dict:
    profile = profile_of(db, character)
    return {
        "id": character.id,
        "name": character.name,
        "aliases": character.aliases or [],
        "role_type": character.role_type,
        "status": character.status,
        "summary": character.summary,
        "appearance_keywords": character.appearance_keywords or [],
        "profile": (profile.content if profile else {}) or {},
    }


def scene_payload(db: Session, scene: Scene) -> dict:
    profile = scene_profile_of(db, scene)
    content = (profile.content if profile else {}) or {}
    return {
        "id": scene.id,
        "name": scene.name,
        "summary": scene.summary,
        "profile": content,
        "visual_prompt": content.get("visual_prompt", ""),
    }


def shot_payload(db: Session, shot: Shot) -> dict:
    characters = list(
        db.scalars(select(ShotCharacter).where(ShotCharacter.shot_id == shot.id))
    )
    names = {
        character.id: character.name for character in list_characters(db, shot.project_id)
    }
    return {
        "shot_id": shot.id,
        "order": shot.order_index,
        "scene_id": shot.scene_id,
        "description": shot.description,
        "action": shot.action,
        "camera": shot.camera or {},
        "characters": [
            {
                "character_id": ref.character_id,
                "character_name": names.get(ref.character_id, ""),
                "costume_id": ref.costume_id,
                "state_id": ref.state_id,
                "action": ref.action,
                "emotion": ref.emotion,
            }
            for ref in characters
        ],
        "dialogue": shot.dialogue or [],
        "duration_seconds": shot.duration_seconds,
        "visual_prompt": shot.visual_prompt,
        "negative_prompt": shot.negative_prompt,
        "reference_asset_ids": shot.reference_asset_ids or [],
        "video_asset_id": shot.selected_video_id,
        "audio_asset_id": shot.selected_audio_id,
        "approved": shot.approved,
    }


def public_character(db: Session, character: Character) -> dict:
    payload = character_payload(db, character)
    payload.update(
        {
            "canonical_profile_id": character.canonical_profile_id,
            "approved_version": character.approved_version,
            "meta": character.meta or {},
        }
    )
    return payload


def public_scene(db: Session, scene: Scene) -> dict:
    payload = scene_payload(db, scene)
    payload.update(
        {
            "canonical_profile_id": scene.canonical_profile_id,
            "approved_version": scene.approved_version,
            "chapter_index": scene.chapter_index,
        }
    )
    return payload


def public_shot(db: Session, shot: Shot) -> dict:
    payload = shot_payload(db, shot)
    payload.update(
        {
            "id": shot.id,
            "storyboard_id": shot.storyboard_id,
            "status": shot.status,
            "approved": shot.approved,
            "config_version": shot.config_version,
            "prompt_version": shot.prompt_version,
        }
    )
    return payload


# ---------------------------------------------------------------- human edits
def update_script(
    db: Session,
    *,
    script: Script,
    title: str | None = None,
    logline: str | None = None,
    synopsis: str | None = None,
    content: dict | None = None,
    status: str = "edited",
) -> Script:
    """Apply a human edit in place.

    Generation history is kept by the agent runs; the script row itself is the
    working copy the director edits, so it is updated rather than duplicated.
    """
    if title is not None:
        script.title = title.strip()[:255]
    if logline is not None:
        script.logline = logline
    if synopsis is not None:
        script.synopsis = synopsis
    if content is not None:
        script.content = content
    script.status = status
    db.flush()
    return script


def update_character(
    db: Session,
    *,
    character: Character,
    name: str | None = None,
    summary: str | None = None,
    appearance_keywords: list[str] | None = None,
    profile: dict | None = None,
) -> Character:
    """Human edits create a new profile version so images stay traceable."""
    if name is not None and name.strip():
        character.name = name.strip()[:120]
    if summary is not None:
        character.summary = summary
    if appearance_keywords is not None:
        character.appearance_keywords = [str(item) for item in appearance_keywords]
    if profile is not None:
        current = profile_of(db, character)
        merged = dict(current.content or {}) if current else {}
        merged.update(profile)
        row = CharacterProfile(
            id=new_id("cprofile"),
            project_id=character.project_id,
            character_id=character.id,
            version=_profile_version(db, character.id),
            status="edited",
            content=merged,
            source="human",
            approved=False,
            agent_id="human",
        )
        db.add(row)
        db.flush()
        character.canonical_profile_id = row.id
        character.status = CharacterStatus.DRAFT.value
        character.approved_version = 0
    db.flush()
    return character


def update_scene(
    db: Session,
    *,
    scene: Scene,
    name: str | None = None,
    summary: str | None = None,
    profile: dict | None = None,
) -> Scene:
    if name is not None and name.strip():
        scene.name = name.strip()[:200]
    if summary is not None:
        scene.summary = summary
    if profile is not None:
        current = scene_profile_of(db, scene)
        merged = dict(current.content or {}) if current else {}
        merged.update(profile)
        version = int(
            db.scalar(
                select(func.max(SceneProfile.version)).where(SceneProfile.scene_id == scene.id)
            )
            or 0
        ) + 1
        row = SceneProfile(
            id=new_id("sprofile"),
            project_id=scene.project_id,
            scene_id=scene.id,
            version=version,
            content=merged,
            approved=False,
            agent_id="human",
        )
        db.add(row)
        db.flush()
        scene.canonical_profile_id = row.id
        scene.status = "draft"
        scene.approved_version = 0
    db.flush()
    return scene


def update_shot(
    db: Session,
    *,
    shot: Shot,
    description: str | None = None,
    action: str | None = None,
    camera: dict | None = None,
    dialogue: list | None = None,
    duration_seconds: float | None = None,
    visual_prompt: str | None = None,
    negative_prompt: str | None = None,
    scene_id: str | None = None,
) -> Shot:
    """Edit a shot card; any content change invalidates the previous approval."""
    changed = False
    if description is not None:
        shot.description = description
        changed = True
    if action is not None:
        shot.action = action
        changed = True
    if camera is not None:
        shot.camera = camera
        changed = True
    if dialogue is not None:
        shot.dialogue = dialogue
        changed = True
    if duration_seconds is not None:
        shot.duration_seconds = max(0.5, float(duration_seconds))
        changed = True
    if visual_prompt is not None:
        shot.visual_prompt = visual_prompt
        changed = True
    if negative_prompt is not None:
        shot.negative_prompt = negative_prompt
    if scene_id is not None:
        shot.scene_id = scene_id
        changed = True
    if changed:
        shot.approved = False
        if shot.visual_prompt:
            shot.status = ShotStatus.PROMPT_READY.value
    db.flush()
    return shot


# ---------------------------------------------------------------------- stages
async def generate_script(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> Script:
    chapters = documents.chapter_payloads(db, project.id)
    if not chapters:
        raise WorkflowError("请先上传并解析小说文本，再进行剧本解析")

    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="script",
        payload=ScriptInput(
            chapters=chapters,
            language=project.language,
            genre=project.genre,
            title_hint=project.name,
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    output = result.output
    version = _next_version(db, Script.version, Script, project.id)
    script = Script(
        id=new_id("script"),
        project_id=project.id,
        version=version,
        status="draft",
        title=output.title or project.name,
        logline=output.logline,
        synopsis=output.synopsis,
        genre=output.genre or project.genre,
        tone=output.tone,
        content=output.model_dump(mode="json"),
        source_document_id=_latest_document_id(db, project.id),
        agent_id="script",
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        config_version=result.config_version,
    )
    db.add(script)
    db.flush()

    for index, event in enumerate(output.events, start=1):
        db.add(
            StoryEvent(
                id=new_id("event"),
                project_id=project.id,
                script_id=script.id,
                order_index=index,
                title=event.title,
                description=event.description,
                chapter_index=event.chapter_index,
                location_name=event.location,
                character_names=list(event.characters),
                importance=float(event.importance),
            )
        )

    touch_status(db, project, ProjectStatus.SCRIPT_READY)
    db.flush()
    logger.info("script v%s generated for project %s", version, project.id)
    return script


def _latest_document_id(db: Session, project_id: str) -> str:
    row = db.scalar(
        select(SourceDocument)
        .where(SourceDocument.project_id == project_id)
        .order_by(SourceDocument.created_at.desc())
    )
    return row.id if row else ""


async def extract_characters(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> list[Character]:
    script = latest_script(db, project.id)
    if script is None:
        raise WorkflowError("还没有剧本，无法提取人物")

    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="character_extraction",
        payload=CharacterExtractionInput(
            script=script.content or {},
            chapter_texts=documents.chapter_payloads(db, project.id),
            language=project.language,
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    output = result.output

    existing = {character.name: character for character in list_characters(db, project.id)}
    characters: list[Character] = []
    for candidate in output.characters:
        character = existing.get(candidate.name)
        if character is None:
            character = Character(
                id=new_id("char"),
                project_id=project.id,
                name=candidate.name,
                status=CharacterStatus.DRAFT.value,
                source="extracted",
            )
            db.add(character)
            existing[candidate.name] = character
        character.aliases = list(candidate.aliases)
        character.role_type = candidate.role_hint or character.role_type
        character.summary = candidate.evidence or character.summary
        character.meta = {
            **(character.meta or {}),
            "evidence": candidate.evidence,
            "gender_hint": candidate.gender_hint,
            "age_hint": candidate.age_hint,
        }
        characters.append(character)
    db.flush()

    by_name = {character.name: character for character in characters}
    db.query(CharacterRelationship).filter(
        CharacterRelationship.project_id == project.id
    ).delete(synchronize_session=False)
    for relation in output.relationships:
        source, target = by_name.get(relation.source), by_name.get(relation.target)
        if source is None or target is None or source.id == target.id:
            continue
        db.add(
            CharacterRelationship(
                id=new_id("crel"),
                project_id=project.id,
                source_character_id=source.id,
                target_character_id=target.id,
                relation=relation.relation,
                description=relation.description,
            )
        )
    db.flush()
    logger.info("extracted %s characters for project %s", len(characters), project.id)
    return characters


async def describe_characters(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    characters: list[Character],
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> list[CharacterProfile]:
    """Create one new immutable profile version per character."""
    script = latest_script(db, project.id)
    chapter_texts = documents.chapter_payloads(db, project.id)
    profiles: list[CharacterProfile] = []
    for character in characters:
        evidence = [character.summary] if character.summary else []
        evidence.extend(str(item) for item in (character.meta or {}).get("evidence_list", []) if item)
        result = await run_agent(
            db,
            runtime,
            project=project,
            agent_id="character_description",
            payload=CharacterDescriptionInput(
                name=character.name,
                evidence=evidence,
                chapter_texts=chapter_texts,
                script=script.content if script else {},
                language=project.language,
            ),
            task=task,
            workflow_run_id=workflow_run_id,
            user_id=user_id,
        )
        output = result.output
        version = _profile_version(db, character.id)
        profile = CharacterProfile(
            id=new_id("cprofile"),
            project_id=project.id,
            character_id=character.id,
            version=version,
            status="draft",
            content=output.model_dump(mode="json"),
            source="ai",
            agent_id="character_description",
            model_id=result.model_id,
            prompt_version=result.prompt_version,
            config_version=result.config_version,
        )
        db.add(profile)
        db.flush()
        character.canonical_profile_id = profile.id
        character.appearance_keywords = list(output.visual_keywords)
        character.summary = output.appearance or character.summary
        if character.role_type in ("", "supporting") and output.role_type:
            character.role_type = output.role_type
        profiles.append(profile)
    db.flush()
    touch_status(db, project, ProjectStatus.CHARACTERS_READY)
    return profiles


def _profile_version(db: Session, character_id: str) -> int:
    current = db.scalar(
        select(func.max(CharacterProfile.version)).where(
            CharacterProfile.character_id == character_id
        )
    )
    return int(current or 0) + 1


async def extract_scenes(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> list[Scene]:
    script = latest_script(db, project.id)
    if script is None:
        raise WorkflowError("还没有剧本，无法提取场景")

    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="scene_extraction",
        payload=SceneExtractionInput(
            chapter_texts=documents.chapter_payloads(db, project.id),
            script=script.content or {},
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    existing = {scene.name: scene for scene in list_scenes(db, project.id)}
    scenes: list[Scene] = []
    for candidate in result.output.scenes:
        scene = existing.get(candidate.name)
        if scene is None:
            scene = Scene(
                id=new_id("scene"),
                project_id=project.id,
                name=candidate.name,
                slug=candidate.name,
                chapter_index=candidate.chapter_index,
            )
            db.add(scene)
            existing[candidate.name] = scene
        scene.summary = scene.summary or candidate.environment
        scene.chapter_index = candidate.chapter_index or scene.chapter_index
        scene.status = "draft"
        scenes.append(scene)
    db.flush()
    return scenes


async def describe_scenes(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    scenes: list[Scene],
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> list[SceneProfile]:
    profiles: list[SceneProfile] = []
    for scene in scenes:
        result = await run_agent(
            db,
            runtime,
            project=project,
            agent_id="scene_description",
            payload=SceneDescriptionInput(
                name=scene.name,
                evidence=scene.summary or "",
                time_of_day="",
                mood="",
                architecture="",
            ),
            task=task,
            workflow_run_id=workflow_run_id,
            user_id=user_id,
        )
        output = result.output
        current = db.scalar(
            select(func.max(SceneProfile.version)).where(SceneProfile.scene_id == scene.id)
        )
        profile = SceneProfile(
            id=new_id("sprofile"),
            project_id=project.id,
            scene_id=scene.id,
            version=int(current or 0) + 1,
            content=output.model_dump(mode="json"),
            agent_id="scene_description",
            model_id=result.model_id,
            prompt_version=result.prompt_version,
            config_version=result.config_version,
        )
        db.add(profile)
        db.flush()
        scene.canonical_profile_id = profile.id
        scene.summary = output.description or scene.summary
        profiles.append(profile)
    db.flush()
    return profiles


async def build_directing_plan(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> DirectingPlan:
    script = latest_script(db, project.id)
    if script is None:
        raise WorkflowError("还没有剧本，无法生成导演规划")
    characters = [character_payload(db, item) for item in list_characters(db, project.id)]
    scenes = [scene_payload(db, item) for item in list_scenes(db, project.id)]
    shots_target = int((project.settings or {}).get("shots_target") or 6)

    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="director",
        payload=DirectingPlanInput(
            script=script.content or {},
            characters=characters,
            scenes=scenes,
            genre=project.genre or script.genre,
            shots_target=shots_target,
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    version = _next_version(db, DirectingPlan.version, DirectingPlan, project.id)
    plan = DirectingPlan(
        id=new_id("plan"),
        project_id=project.id,
        version=version,
        status="draft",
        content=result.output.model_dump(mode="json"),
        agent_id="director",
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        config_version=result.config_version,
    )
    db.add(plan)
    db.flush()
    return plan


async def build_storyboard(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> Storyboard:
    script = latest_script(db, project.id)
    plan = latest_plan(db, project.id)
    if script is None or plan is None:
        raise WorkflowError("生成分镜前需要先完成剧本解析与导演规划")
    characters = [character_payload(db, item) for item in list_characters(db, project.id)]
    scenes = [scene_payload(db, item) for item in list_scenes(db, project.id)]
    shots_target = int(
        (plan.content or {}).get("shot_strategy", {}).get("total_shots")
        or (project.settings or {}).get("shots_target")
        or 6
    )

    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="storyboard",
        payload=StoryboardInput(
            script=script.content or {},
            characters=characters,
            scenes=scenes,
            plan=plan.content or {},
            shots_target=shots_target,
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    output = result.output
    version = _next_version(db, Storyboard.version, Storyboard, project.id)
    board = Storyboard(
        id=new_id("board"),
        project_id=project.id,
        version=version,
        status="draft",
        directing_plan_id=plan.id,
        title=output.title or script.title,
        notes=output.notes,
        agent_id="storyboard",
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        config_version=result.config_version,
    )
    db.add(board)
    db.flush()

    scene_by_name = {scene.name: scene.id for scene in list_scenes(db, project.id)}
    character_by_id = {
        character.id: character for character in list_characters(db, project.id)
    }
    shots: list[Shot] = []
    for index, draft in enumerate(output.shots, start=1):
        shot = Shot(
            id=new_id("shot"),
            project_id=project.id,
            storyboard_id=board.id,
            scene_id=scene_by_name.get(draft.scene_name, ""),
            order_index=index,
            status=ShotStatus.DRAFT.value,
            description=draft.description,
            action=draft.action,
            camera=draft.camera.model_dump(mode="json"),
            characters=[ref.model_dump(mode="json") for ref in draft.characters],
            dialogue=[line.model_dump(mode="json") for line in draft.dialogue],
            duration_seconds=float(draft.duration_seconds or 5.0),
            visual_prompt=draft.visual_prompt,
            negative_prompt=draft.negative_prompt,
            reference_asset_ids=list(draft.reference_asset_ids),
            config_version=result.config_version,
        )
        db.add(shot)
        db.flush()
        for ref in draft.characters:
            if not ref.character_id or ref.character_id not in character_by_id:
                continue
            db.add(
                ShotCharacter(
                    id=new_id("shotchar"),
                    project_id=project.id,
                    shot_id=shot.id,
                    character_id=ref.character_id,
                    costume_id=ref.costume_id or "",
                    state_id=ref.state_id or "",
                    action=ref.action,
                    emotion=ref.emotion,
                )
            )
        shots.append(shot)
    db.flush()

    await refine_prompts(
        db,
        runtime,
        project=project,
        shots=shots,
        plan=plan,
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    touch_status(db, project, ProjectStatus.STORYBOARD_READY)
    return board


async def refine_prompts(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    shots: list[Shot],
    plan: DirectingPlan | None = None,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> None:
    """Run the Prompt agent so every shot carries an engine-ready prompt."""
    plan = plan or latest_plan(db, project.id)
    plan_content = (plan.content if plan else {}) or {}
    style = str(plan_content.get("visual_style") or "")
    rules = [str(item) for item in plan_content.get("continuity_rules") or []]
    for shot in shots:
        try:
            result = await run_agent(
                db,
                runtime,
                project=project,
                agent_id="prompt",
                payload=PromptInput(
                    shot=shot_payload(db, shot),
                    visual_style=style,
                    continuity_rules=rules,
                ),
                task=task,
                workflow_run_id=workflow_run_id,
                user_id=user_id,
            )
        except Exception:  # prompt refinement is an enhancement, never a blocker
            logger.warning("prompt agent failed for shot %s", shot.id, exc_info=True)
            continue
        output = result.output
        shot.visual_prompt = output.visual_prompt or shot.visual_prompt
        shot.negative_prompt = output.negative_prompt or shot.negative_prompt
        shot.prompt_version = result.prompt_version
        shot.status = ShotStatus.PROMPT_READY.value
    db.flush()


def project_summary(db: Session, project: Project) -> dict[str, Any]:
    script = latest_script(db, project.id)
    plan = latest_plan(db, project.id)
    board = latest_board(db, project.id)
    shots = list_shots(db, project.id)
    return {
        "project_id": project.id,
        "name": project.name,
        "language": project.language,
        "genre": project.genre,
        "status": project.status,
        "script_version": script.version if script else 0,
        "script_title": script.title if script else "",
        "logline": script.logline if script else "",
        "synopsis": (script.synopsis if script else "")[:1200],
        "directing_plan_version": plan.version if plan else 0,
        "visual_style": ((plan.content or {}).get("visual_style") if plan else ""),
        "storyboard_version": board.version if board else 0,
        "shot_count": len(shots),
        "characters": [character.name for character in list_characters(db, project.id)],
        "scenes": [scene.name for scene in list_scenes(db, project.id)],
        "total_duration_seconds": round(sum(shot.duration_seconds for shot in shots), 2),
    }
