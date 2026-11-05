"""场景当前档案批准标记；调用方负责审核和统一 flush。"""

from sqlalchemy.orm import Session

from app.modules.platform.exceptions import NotFoundError
from app.modules.scenes.infrastructure.persistence.models import Scene

from .queries import list_scenes, scene_profile_of


def _approve_profile(db: Session, scene: Scene) -> None:
    profile = scene_profile_of(db, scene)
    if profile is not None:
        profile.approved = True
        scene.approved_version = profile.version
    scene.status = "approved"


def approve_current_scenes(db: Session, project_id: str) -> None:
    """批准项目当前 canonical 场景档案；保留缺档案行为，不 flush、不提交。"""
    for scene in list_scenes(db, project_id):
        _approve_profile(db, scene)


def approve_scene_profile(db: Session, project_id: str, scene_id: str) -> None:
    """核对项目后批准指定场景当前档案；不 flush、不提交。"""
    scene = db.get(Scene, scene_id)
    if scene is None or scene.project_id != project_id:
        raise NotFoundError("场景不存在", details={"scene_id": scene_id})
    _approve_profile(db, scene)


def approve_scene_entity(db: Session, project_id: str, scene: Scene) -> Scene:
    """兼容旧审核入口：批准传入的同一实体并 flush，不提交。"""
    if scene.project_id != project_id:
        raise NotFoundError("场景不存在", details={"scene_id": scene.id})
    _approve_profile(db, scene)
    db.flush()
    return scene
