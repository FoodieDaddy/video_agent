"""分镜来源与第二关审核快照。跨模块只通过production.public调用。"""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy.orm import Session

from app.modules.platform.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.modules.production.contracts import StoryboardApprovalTargets
from app.modules.production.infrastructure.persistence.models import DirectingPlan, Storyboard

from .fingerprints import content_fingerprint, directing_plan_fingerprint, shot_edit_fingerprint
from .queries import directing_source_status, latest_board, latest_plan, list_shots


def get_storyboard(db: Session, board_id: str) -> Storyboard:
    board = db.get(Storyboard, board_id)
    if board is None:
        raise NotFoundError("分镜版本不存在", details={"storyboard_id": board_id})
    return board


def storyboard_source_status(db: Session, board: Storyboard) -> dict:
    """来源来自绑定的不可变导演版本；新导演或新剧本使旧分镜过期。"""
    plan = db.get(DirectingPlan, board.directing_plan_id)
    if plan is None or plan.project_id != board.project_id:
        return {"source_script": None, "source_status": "unknown"}
    source = directing_source_status(db, plan)
    current = latest_plan(db, board.project_id)
    if source["source_status"] == "current" and (current is None or current.id != plan.id):
        source = {**source, "source_status": "stale"}
    return source


def storyboard_fingerprint(db: Session, board: Storyboard) -> str:
    return content_fingerprint(
        {
            "id": board.id,
            "version": board.version,
            "title": board.title,
            "notes": board.notes,
            "directing_plan_id": board.directing_plan_id,
            "shots": [shot_edit_fingerprint(shot) for shot in list_shots(db, board.project_id, board=board)],
        }
    )


def storyboard_review_snapshot(db: Session, project_id: str, board: Storyboard) -> dict:
    current = latest_board(db, project_id)
    if board.project_id != project_id or current is None or current.id != board.id:
        raise ConflictError("只能提审当前项目的最新分镜", details={"storyboard_id": board.id})
    source = storyboard_source_status(db, board)
    if source["source_status"] != "current":
        raise ConflictError("分镜的导演或剧本来源已过期或未记录，请重新生成后提审")
    plan = db.get(DirectingPlan, board.directing_plan_id)
    shots = list_shots(db, project_id, board=board)
    if not shots:
        raise ConflictError("分镜没有可审核镜头")
    return {
        "storyboard_id": board.id,
        "storyboard_version": board.version,
        "directing_plan_id": plan.id,
        "plan_fingerprint": directing_plan_fingerprint(plan),
        "source_script": deepcopy(source["source_script"]),
        "storyboard_fingerprint": storyboard_fingerprint(db, board),
        "shot_fingerprints": {shot.id: shot_edit_fingerprint(shot) for shot in shots},
    }


def assert_storyboard_review_snapshot(db: Session, project_id: str, snapshot: dict | None):
    """批准前核对实际版本与内容；旧记录缺少快照不可补算当前基线冒充原始待审。"""
    if not isinstance(snapshot, dict) or not snapshot.get("storyboard_id"):
        raise ConflictError("旧待审记录缺少分镜快照，请先退回，再重新提审")
    try:
        board = get_storyboard(db, snapshot["storyboard_id"])
    except NotFoundError as exc:
        raise ConflictError("待审分镜已不存在，请退回后重新提审") from exc
    # 只刷新本关产物，不丢弃调用方尚未写入的工作流游标或审核决定。
    db.refresh(board)
    plan = db.get(DirectingPlan, board.directing_plan_id)
    if plan is not None:
        db.refresh(plan)
    for shot in list_shots(db, project_id, board=board):
        db.refresh(shot)
    try:
        current = storyboard_review_snapshot(db, project_id, board)
    except (ConflictError, NotFoundError) as exc:
        raise ConflictError("待审分镜的版本或来源已变化，请先退回，再重新提审") from exc
    if current != snapshot:
        raise ConflictError("待审分镜内容已变化，请先退回，再重新提审", details={"storyboard_id": board.id})
    return board, db.get(DirectingPlan, board.directing_plan_id), list_shots(db, project_id, board=board)


def prepare_storyboard_review_snapshot(db: Session, project_id: str, board_id: str | None = None) -> dict:
    """选择提审分镜并返回快照，不把 ORM 传给审核模块。"""
    board = get_storyboard(db, board_id) if board_id else latest_board(db, project_id)
    if board is None:
        raise ValidationAppError("还没有分镜，无法提交第二轮审核")
    return storyboard_review_snapshot(db, project_id, board)


def assert_storyboard_approval_targets(
    db: Session, project_id: str, snapshot: dict | None
) -> StoryboardApprovalTargets:
    """验证冻结快照，并只返回批准目标 ID；旧 ORM 校验入口继续可用。"""
    board, plan, shots = assert_storyboard_review_snapshot(db, project_id, snapshot)
    return StoryboardApprovalTargets(
        project_id=project_id,
        storyboard_id=board.id,
        directing_plan_id=plan.id,
        shot_ids=tuple(shot.id for shot in shots),
    )
