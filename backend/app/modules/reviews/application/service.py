"""人工审核记录、决定与批准标记的应用用例。

调用方负责操作者权限，以及 project、review 或目标实体的关联校验；各入口额外校验以函数契约为准。
纯状态规则在 domain 中，应用层映射为兼容异常并执行原有写入；本文件只 flush、不 commit。
审核决定不会自动启动工作流；分镜第二关冻结版本/内容，其余关卡沿用原审批语义。
"""

from __future__ import annotations

import logging
from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.character import Character, CharacterAsset
from app.models.ops import Review, ReviewComment, WorkflowRun
from app.models.production import EditingProject, Shot
from app.models.project import Project
from app.models.scene import Scene
from app.modules.characters import public as character_module
from app.modules.platform.constants import ProjectStatus, ReviewStatus, ShotStatus
from app.modules.platform.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.modules.platform.ids import new_id, utcnow
from app.modules.production import public as production_module
from app.modules.projects.public import touch_status
from app.modules.reviews.domain.decisions import DecisionViolation, review_decision_violation
from app.modules.scenes import public as scene_module
from app.modules.story import public as story_module

logger = logging.getLogger(__name__)

VALID_STAGES = {"characters_scenes", "storyboard", "shots", "final"}


def create_review(
    db: Session,
    *,
    project: Project,
    stage: str,
    target_type: str = "project",
    target_id: str = "",
    workflow_run_id: str = "",
) -> Review:
    """为合法阶段创建 pending 审核，或复用同范围待审记录。

    Args:
        project: 调用方已授权的项目。
        stage: VALID_STAGES 中的阶段标识。
        workflow_run_id: 非空时限定运行实例，空值表示不限定。

    Returns:
        Review；分镜关只复用同一实际内容快照，其余关沿用项目/阶段/可选run范围。

    Raises:
        ValidationAppError: 未知审核阶段。

    Notes:
        分镜关在创建时冻结实际版本、来源与镜头指纹；其余关不增加快照。
        仅新建时 flush、不提交。
    """
    if stage not in VALID_STAGES:
        raise ValidationAppError(f"未知审核阶段 '{stage}'")
    snapshot = None
    if stage == "storyboard":
        board = (
            production_module.get_storyboard(db, target_id)
            if target_type == "storyboard" and target_id
            else production_module.latest_board(db, project.id)
        )
        if board is None:
            raise ValidationAppError("还没有分镜，无法提交第二轮审核")
        snapshot = production_module.storyboard_review_snapshot(db, project.id, board)
        # 工作流保留节点target便于追踪；独立审核的target直接指向实际分镜。
        if target_type != "workflow_node":
            target_type, target_id = "storyboard", board.id
    existing = pending_review(db, project.id, stage, workflow_run_id=workflow_run_id or None)
    if existing is not None:
        if snapshot is not None and (existing.decision or {}).get("storyboard_snapshot") != snapshot:
            raise ConflictError(
                "已有待审分镜发生变化，请先退回旧待审记录，再重新提审", details={"review_id": existing.id}
            )
        return existing
    review = Review(
        id=new_id("review"),
        project_id=project.id,
        workflow_run_id=workflow_run_id,
        stage=stage,
        target_type=target_type,
        target_id=target_id,
        status=ReviewStatus.PENDING.value,
        decision={"storyboard_snapshot": snapshot} if snapshot is not None else {},
    )
    db.add(review)
    db.flush()
    return review


def pending_review(
    db: Session, project_id: str, stage: str, *, workflow_run_id: str | None = None
) -> Review | None:
    """读取项目、阶段及可选工作流范围内最新 pending 审核，无记录返回 None。

    workflow_run_id 为空时不限定运行实例；只读、不提交，调用方应明确所需范围。
    """
    statement = select(Review).where(
        Review.project_id == project_id,
        Review.stage == stage,
        Review.status == ReviewStatus.PENDING.value,
    )
    if workflow_run_id:
        statement = statement.where(Review.workflow_run_id == workflow_run_id)
    return db.scalars(statement.order_by(Review.created_at.desc())).first()


def approved_review(
    db: Session, project_id: str, stage: str, *, workflow_run_id: str | None = None
) -> Review | None:
    """读取同项目阶段及可选运行范围最新已批准审核，无记录返回 None。

    为空的 run 不构成运行隔离条件；只读，不能代替调用方核对被批准的资产版本。
    """
    statement = select(Review).where(
        Review.project_id == project_id,
        Review.stage == stage,
        Review.status == ReviewStatus.APPROVED.value,
    )
    if workflow_run_id:
        statement = statement.where(Review.workflow_run_id == workflow_run_id)
    return db.scalars(statement.order_by(Review.reviewed_at.desc())).first()


def latest_stage_review(
    db: Session, project_id: str, stage: str, *, workflow_run_id: str | None = None
) -> Review | None:
    """按创建时间读取阶段最新审核，不限制决定状态；可选 run 为空时跨该项目所有运行。

    无记录返回 None；只读、不提交。
    """
    statement = select(Review).where(Review.project_id == project_id, Review.stage == stage)
    if workflow_run_id:
        statement = statement.where(Review.workflow_run_id == workflow_run_id)
    return db.scalars(statement.order_by(Review.created_at.desc())).first()


def list_reviews(db: Session, project_id: str, *, status: str | None = None) -> list[Review]:
    """按创建时间降序读取项目审核，可用 status 过滤；无匹配返回空列表。

    只读，不替调用方检查操作者访问权限。
    """
    statement = select(Review).where(Review.project_id == project_id)
    if status:
        statement = statement.where(Review.status == status)
    return list(db.scalars(statement.order_by(Review.created_at.desc())))


def get_review(db: Session, project_id: str, review_id: str) -> Review:
    """按 ID 读取审核并核对 project_id，不属于项目或不存在时抛 NotFoundError。

    只读、不提交；操作者对项目的访问资格仍由调用方保证。
    """
    review = db.get(Review, review_id)
    if review is None or review.project_id != project_id:
        raise NotFoundError("审核记录不存在", details={"review_id": review_id})
    return review


def add_comment(db: Session, review: Review, *, user_id: str, body: str) -> ReviewComment:
    """为审核追加非空意见，返回 ReviewComment。

    空白正文抛 ValidationAppError；前置是用户已授权且 review 归属已核对。
    去除正文首尾空白后写入并 flush，不提交；重复请求会新增评论。
    """
    if not body.strip():
        raise ValidationAppError("评论内容不能为空")
    comment = ReviewComment(
        id=new_id("rcomment"),
        review_id=review.id,
        project_id=review.project_id,
        user_id=user_id,
        body=body.strip(),
    )
    db.add(comment)
    db.flush()
    return comment


def comments(db: Session, review_id: str) -> list[ReviewComment]:
    """按创建时间读取审核的全部评论，未匹配时返回空列表；权限由调用方保证。"""
    return list(
        db.scalars(
            select(ReviewComment)
            .where(ReviewComment.review_id == review_id)
            .order_by(ReviewComment.created_at)
        )
    )


def decide(
    db: Session,
    *,
    project: Project,
    review: Review,
    status: str,
    comment: str = "",
    decision: dict | None = None,
    reviewer_id: str = "",
) -> Review:
    """对 pending 审核应用通过或驳回决定。

    Args:
        project: 已授权项目；调用方核对 review 归属和操作者权限。
        review: 当前待处理审核 ORM 实体。
        status: approved 或 rejected，按纯领域规则验证。
        decision: 附加决定数据；分镜的服务器快照保留，不接受客户端覆盖。

    Returns:
        同一 Review，更新决定、意见、操作者和时间。

    Raises:
        ValidationAppError: 请求结论非法，优先于已处理状态检查。
        ConflictError: 结论合法但审核已处理，或批准所关联工作流的剧本基线已失效。

    Notes:
        分镜批准只更新冻结快照中的产物，其余关更新当前产物；驳回不撤销历史批准。
        flush、不提交，不自动恢复工作流。
        关联工作流的批准先检查剧本基线，再写结论和产物标记，与是否续跑无关。
        分镜缺少快照的旧待审单要求先退回重提；其它独立关卡保留兼容。
        再次决定会冲突，不是幂等响应，也不提供分布式审批锁。
    """
    violation = review_decision_violation(review.status, status)
    if violation is DecisionViolation.INVALID_DECISION:
        raise ValidationAppError("审核结论只能是 approved 或 rejected")
    if violation is DecisionViolation.ALREADY_DECIDED:
        raise ConflictError("该审核已经处理", details={"review_id": review.id, "status": review.status})

    frozen = None
    if status == ReviewStatus.APPROVED.value and review.stage == "storyboard":
        frozen = assert_review_snapshot(db, project=project, review=review)
    if status == ReviewStatus.APPROVED.value and review.workflow_run_id:
        run = db.get(WorkflowRun, review.workflow_run_id)
        if run is None or run.project_id != project.id:
            raise ConflictError("审核关联的工作流不存在或归属不匹配，请重新开始流程")
        # 直接依赖 story 的公开校验，不通过 workflow 引擎形成模块反向依赖。
        for output in ((run.state or {}).get("outputs") or {}).values():
            if isinstance(output, dict) and output.get("script_id"):
                story_module.assert_script_baseline(
                    db, project.id, output["script_id"], output.get("script_fingerprint")
                )

    review.status = status
    review.comment = comment
    if review.stage == "storyboard":
        stored = deepcopy((review.decision or {}).get("storyboard_snapshot"))
        # 客户端附加说明不能覆盖服务器冻结的待审版本与内容指纹。
        extra = {key: value for key, value in (decision or {}).items() if key != "storyboard_snapshot"}
        review.decision = {**extra, "storyboard_snapshot": stored}
    else:
        review.decision = decision or {}
    review.reviewer_id = reviewer_id
    review.reviewed_at = utcnow()
    db.flush()

    # 本函数写审核结论及产物通过标记；工作流继续执行由恢复入口负责。
    # rejected 不应用通过标记。驳回后恢复到原 gate 时，WorkflowEngine 会新建待审
    # 记录，不会仅因一次驳回就在这里自动重跑提取/描述模型。
    if status == ReviewStatus.APPROVED.value:
        _apply_approval(db, project=project, stage=review.stage, storyboard_targets=frozen)

    logger.info("review %s (%s) -> %s by %s", review.id, review.stage, status, reviewer_id)
    return review


def assert_review_snapshot(db: Session, *, project: Project, review: Review):
    """第二关批准/工作流续跑共用核验；拒绝无需通过旧快照，便于显式退回后重提。"""
    if review.project_id != project.id:
        raise ConflictError("审核记录不属于当前项目")
    if review.stage != "storyboard":
        return None
    return production_module.assert_storyboard_review_snapshot(
        db, project.id, (review.decision or {}).get("storyboard_snapshot")
    )


def _apply_approval(db: Session, *, project: Project, stage: str, storyboard_targets=None) -> None:
    """按审核阶段更新现有产物批准标记；仅供已验证的 decide 调用。

    人物场景阶段读取当前 canonical 档案，并标记人物全部形象资产；不绑定创建待审时版本。
    分镜关使用已验证快照，其它阶段沿用原当前产物语义；最后 flush、不提交。
    本操作不创建审核、生成资产或启动工作流，也不独立证明媒体和内容质量合格。
    """
    if stage == "characters_scenes":
        # 第一关按审核时项目中可解析的当前档案更新 approved/approved_version，
        # 并标记人物、场景为 approved；这不是创建审核记录时冻结的档案快照。
        for character in character_module.list_characters(db, project.id):
            profile = character_module.profile_of(db, character)
            if profile is not None:
                profile.approved = True
                character.approved_version = profile.version
            character.status = "approved"
            for asset in db.scalars(
                select(CharacterAsset).where(CharacterAsset.character_id == character.id)
            ):
                asset.approved = True
        for scene in scene_module.list_scenes(db, project.id):
            profile = scene_module.scene_profile_of(db, scene)
            if profile is not None:
                profile.approved = True
                scene.approved_version = profile.version
            scene.status = "approved"
        touch_status(db, project, ProjectStatus.CHARACTERS_READY)

    elif stage == "storyboard":
        if storyboard_targets is None:
            raise ConflictError("分镜审核缺少已验证的版本快照")
        board, plan, shots = storyboard_targets
        board.approved = True
        board.status = "approved"
        plan.approved = True
        plan.status = "approved"
        for shot in shots:
            shot.approved = True
            if shot.status == ShotStatus.DRAFT.value:
                shot.status = ShotStatus.PROMPT_READY.value
        touch_status(db, project, ProjectStatus.STORYBOARD_READY)

    elif stage == "shots":
        for shot in production_module.list_shots(db, project.id):
            shot.approved = True
            if shot.selected_video_id:
                shot.status = ShotStatus.APPROVED.value
        touch_status(db, project, ProjectStatus.VIDEO_READY)

    elif stage == "final":
        editing = db.scalar(
            select(EditingProject)
            .where(EditingProject.project_id == project.id)
            .order_by(EditingProject.version.desc())
        )
        if editing is not None and editing.status == "rendered":
            editing.status = "approved"
        touch_status(db, project, ProjectStatus.EDITED)
    db.flush()


def review_public(db: Session, review: Review) -> dict:
    """读取评论并把审核投影为 API 字典，不写入或提交。

    decision 等嵌套值沿用记录内容，调用方应按只读使用并在进入此处前完成授权。
    """
    snapshot = (review.decision or {}).get("storyboard_snapshot") if review.stage == "storyboard" else None
    target_status = "unknown"
    if snapshot is not None:
        try:
            production_module.assert_storyboard_review_snapshot(db, review.project_id, snapshot)
            target_status = "current"
        except (ConflictError, NotFoundError):
            target_status = "stale"
    return {
        "id": review.id,
        "project_id": review.project_id,
        "workflow_run_id": review.workflow_run_id,
        "stage": review.stage,
        "target_type": review.target_type,
        "target_id": review.target_id,
        "target_snapshot": snapshot,
        "target_status": target_status,
        "status": review.status,
        "comment": review.comment,
        "decision": review.decision or {},
        "reviewer_id": review.reviewer_id,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "comments": [
            {
                "id": comment.id,
                "user_id": comment.user_id,
                "body": comment.body,
                "created_at": comment.created_at.isoformat() if comment.created_at else None,
            }
            for comment in comments(db, review.id)
        ],
    }


def approve_shot(db: Session, project: Project, shot: Shot) -> Shot:
    """核对项目归属后仅批准给定镜头，返回原 Shot。

    不属于项目抛 NotFoundError；存在选中视频引用时设置 approved 状态，不验证媒体字节。
    仅 flush、不提交，不等同于处理工作流的 Review 记录。
    """
    if shot.project_id != project.id:
        raise NotFoundError("镜头不存在", details={"shot_id": shot.id})
    shot.approved = True
    if shot.selected_video_id:
        shot.status = ShotStatus.APPROVED.value
    db.flush()
    return shot


def approve_character(db: Session, project: Project, character: Character) -> Character:
    """核对项目归属并批准人物当前可解析档案，返回原 Character。

    外项目实体抛 NotFoundError；缺档案时仍沿用设置人物 approved 的行为。
    仅 flush、不提交；不创建审核决定，也不恢复工作流。
    """
    if character.project_id != project.id:
        raise NotFoundError("人物不存在", details={"character_id": character.id})
    profile = character_module.profile_of(db, character)
    if profile is not None:
        profile.approved = True
        character.approved_version = profile.version
    character.status = "approved"
    db.flush()
    return character


def approve_scene(db: Session, project: Project, scene: Scene) -> Scene:
    """核对项目归属并批准场景当前可解析档案，返回原 Scene。

    外项目实体抛 NotFoundError；缺档案时仍可设置场景 approved 状态。
    仅 flush、不提交；此操作不替代工作流审核记录或其恢复步骤。
    """
    if scene.project_id != project.id:
        raise NotFoundError("场景不存在", details={"scene_id": scene.id})
    profile = scene_module.scene_profile_of(db, scene)
    if profile is not None:
        profile.approved = True
        scene.approved_version = profile.version
    scene.status = "approved"
    db.flush()
    return scene
