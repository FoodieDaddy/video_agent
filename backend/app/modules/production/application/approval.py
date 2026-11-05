"""制作产物批准写入；reviews 决定通过后经公开入口调用。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.platform.constants import ShotStatus
from app.modules.platform.exceptions import ConflictError, NotFoundError
from app.modules.production.contracts import StoryboardApprovalTargets
from app.modules.production.infrastructure.persistence.models import (
    DirectingPlan,
    EditingProject,
    Shot,
    Storyboard,
)

from .queries import list_shots


def approve_storyboard_targets(db: Session, targets: StoryboardApprovalTargets) -> None:
    """应用本事务已校验的分镜快照目标；不再次选择最新版本，不 flush、不提交。"""
    board = db.get(Storyboard, targets.storyboard_id)
    plan = db.get(DirectingPlan, targets.directing_plan_id)
    if board is None or plan is None:
        raise ConflictError("分镜审核缺少已验证的版本快照")
    board.approved = True
    board.status = "approved"
    plan.approved = True
    plan.status = "approved"
    for shot_id in targets.shot_ids:
        shot = db.get(Shot, shot_id)
        if shot is None:
            raise ConflictError("分镜审核缺少已验证的版本快照")
        shot.approved = True
        if shot.status == ShotStatus.DRAFT.value:
            shot.status = ShotStatus.PROMPT_READY.value


def _approve_video_selection(shot: Shot) -> None:
    shot.approved = True
    if shot.selected_video_id:
        shot.status = ShotStatus.APPROVED.value


def approve_current_shots(db: Session, project_id: str) -> None:
    """批准当前分镜的镜头及已有视频选择；不 flush、不提交。"""
    for shot in list_shots(db, project_id):
        _approve_video_selection(shot)


def approve_shot_selection(db: Session, project_id: str, shot_id: str) -> None:
    """核对项目后批准一个镜头，保留无选中视频时的状态；不 flush、不提交。"""
    shot = db.get(Shot, shot_id)
    if shot is None or shot.project_id != project_id:
        raise NotFoundError("镜头不存在", details={"shot_id": shot_id})
    _approve_video_selection(shot)


def approve_shot_entity(db: Session, project_id: str, shot: Shot) -> Shot:
    """兼容旧审核入口：批准传入的同一镜头并 flush，不提交。"""
    if shot.project_id != project_id:
        raise NotFoundError("镜头不存在", details={"shot_id": shot.id})
    _approve_video_selection(shot)
    db.flush()
    return shot


def approve_latest_render(db: Session, project_id: str) -> None:
    """将最新 rendered 剪辑标为 approved，其他状态不变；不 flush、不提交。"""
    editing = db.scalar(
        select(EditingProject)
        .where(EditingProject.project_id == project_id)
        .order_by(EditingProject.version.desc())
    )
    if editing is not None and editing.status == "rendered":
        editing.status = "approved"
