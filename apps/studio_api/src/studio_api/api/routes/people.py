"""Character and scene workbenches."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.models.character import Character
from app.models.scene import Scene
from studio_api.api.deps import RuntimeDep, SessionDep, UserDep, owner_project, project_scope, run_task
from studio_api.api.schemas import CharacterImagesRequest, CharacterUpdate, SceneUpdate
from studio_characters import public as character_module
from studio_platform.exceptions import NotFoundError
from studio_production import public as media
from studio_reviews import public as reviews
from studio_scenes import public as scene_module

router = APIRouter(tags=["people"])


@router.get("/projects/{project_id}/characters")
def list_characters(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = character_module.list_characters(db, project.id)
    return {
        "items": [character_module.public_character(db, row) for row in rows],
        "count": len(rows),
    }


@router.get("/characters/{character_id}")
def get_character(character_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    character = _load_character(db, character_id)
    project_scope(db, character.project_id, user)
    payload = character_module.public_character(db, character)
    payload["assets"] = [
        media.character_asset_public(db, row) for row in media.character_assets(db, character.id)
    ]
    return payload


@router.patch("/characters/{character_id}")
def update_character(
    character_id: str,
    payload: CharacterUpdate,
    db: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    character = _load_character(db, character_id)
    owner_project(db, character.project_id, user)
    data = payload.model_dump(exclude_unset=True)
    character_module.update_character(db, character=character, **data)
    db.flush()
    return character_module.public_character(db, character)


@router.post("/characters/{character_id}/generate-images")
async def generate_images(
    character_id: str,
    payload: CharacterImagesRequest,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    character = _load_character(db, character_id)
    project = owner_project(db, character.project_id, user)
    return await run_task(
        db,
        runtime,
        project=project,
        type="character_images",
        payload={"character_id": character.id, "kinds": payload.kinds},
        user_id=user.id,
        wait=wait,
    )


@router.post("/characters/{character_id}/generate-views")
async def generate_views(
    character_id: str,
    runtime: RuntimeDep,
    db: SessionDep,
    user: UserDep,
    wait: bool = Query(default=False),
) -> dict[str, Any]:
    """Regenerate the three-view turnaround sheet used for consistency checks."""
    character = _load_character(db, character_id)
    project = owner_project(db, character.project_id, user)
    return await run_task(
        db,
        runtime,
        project=project,
        type="character_images",
        payload={"character_id": character.id, "kinds": ["turnaround"]},
        user_id=user.id,
        wait=wait,
    )


@router.post("/characters/{character_id}/approve")
def approve_character(character_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    character = _load_character(db, character_id)
    project = owner_project(db, character.project_id, user)
    reviews.approve_character(db, project, character)
    db.flush()
    return character_module.public_character(db, character)


@router.get("/characters/{character_id}/assets")
def character_assets(character_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    character = _load_character(db, character_id)
    project_scope(db, character.project_id, user)
    rows = media.character_assets(db, character.id)
    return {
        "items": [media.character_asset_public(db, row) for row in rows],
        "count": len(rows),
    }


@router.get("/projects/{project_id}/scenes")
def list_scenes(project_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    project = project_scope(db, project_id, user)
    rows = scene_module.list_scenes(db, project.id)
    return {"items": [scene_module.public_scene(db, row) for row in rows], "count": len(rows)}


@router.get("/scenes/{scene_id}")
def get_scene(scene_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    scene = _load_scene(db, scene_id)
    project_scope(db, scene.project_id, user)
    return scene_module.public_scene(db, scene)


@router.patch("/scenes/{scene_id}")
def update_scene(
    scene_id: str,
    payload: SceneUpdate,
    db: SessionDep,
    user: UserDep,
) -> dict[str, Any]:
    scene = _load_scene(db, scene_id)
    owner_project(db, scene.project_id, user)
    data = payload.model_dump(exclude_unset=True)
    scene_module.update_scene(db, scene=scene, **data)
    db.flush()
    return scene_module.public_scene(db, scene)


@router.post("/scenes/{scene_id}/approve")
def approve_scene(scene_id: str, db: SessionDep, user: UserDep) -> dict[str, Any]:
    scene = _load_scene(db, scene_id)
    project = owner_project(db, scene.project_id, user)
    reviews.approve_scene(db, project, scene)
    db.flush()
    return scene_module.public_scene(db, scene)


def _load_character(db, character_id: str) -> Character:
    character = db.get(Character, character_id)
    if character is None:
        raise NotFoundError("人物不存在", details={"character_id": character_id})
    return character


def _load_scene(db, scene_id: str) -> Scene:
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise NotFoundError("场景不存在", details={"scene_id": scene_id})
    return scene
