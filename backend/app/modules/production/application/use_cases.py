"""镜头编辑、导演与分镜生成用例。

调用方负责项目权限和输入实体归属；本文件 flush 而不提交。
模型请求与调用记录沿用执行协调层，数据库回滚不会撤销外部模型用量。
"""

from __future__ import annotations

import logging
from copy import deepcopy
from math import isfinite

from pydantic import ValidationError
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models.character import CharacterCostume, CharacterState
from app.models.ops import Task
from app.models.project import Asset, Project
from app.modules.ai_runtime.public import run_agent
from app.modules.characters.public import character_payload, list_characters
from app.modules.platform.constants import ProjectStatus, ShotStatus
from app.modules.platform.exceptions import (
    AgentSchemaError,
    AppError,
    ConflictError,
    ValidationAppError,
    WorkflowError,
)
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id
from app.modules.platform.persistence.versions import next_version as _next_version
from app.modules.production.infrastructure.persistence.models import (
    DirectingPlan,
    Shot,
    ShotCharacter,
    Storyboard,
)
from app.modules.projects.public import touch_status
from app.modules.scenes.public import list_scenes, scene_payload
from app.modules.story.public import assert_script_baseline, latest_script, script_fingerprint
from app.schemas.director import DirectingPlanInput
from app.schemas.prompt import PromptInput
from app.schemas.storyboard import StoryboardInput

from .fingerprints import directing_plan_fingerprint, shot_edit_fingerprint
from .queries import directing_source_status, latest_board, latest_plan, shot_payload

logger = logging.getLogger(__name__)


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
    base_storyboard_id: str | None = None,
    base_shot_fingerprint: str | None = None,
) -> Shot:
    """原地修改镜头卡并按现有规则清除批准标记。

    Args:
        shot: 已授权且归属已核对的镜头。
        duration_seconds: 提供时必须大于0且不超过60秒，按实际数值保存。
        base_shot_fingerprint: 可选的旧内容指纹，过期时不修改镜头。

    Returns:
        同一 Shot，不新增镜头版本。

    Notes:
        实际内容变化（包含负提示词）才清除镜头及所属分镜批准，同值保存保持原批准。
        历史分镜只读，场景引用限制在当前项目；仅 flush、不提交。
    """
    board = db.get(Storyboard, shot.storyboard_id)
    current = latest_board(db, shot.project_id)
    if board is None or current is None or current.id != board.id:
        raise ConflictError("历史分镜只读，请编辑最新分镜", details={"storyboard_id": shot.storyboard_id})
    if base_storyboard_id is not None and base_storyboard_id != board.id:
        raise ConflictError("分镜版本已变化，请重新打开镜头")
    if base_shot_fingerprint is not None and base_shot_fingerprint != shot_edit_fingerprint(shot):
        raise ConflictError("镜头已被修改，请刷新后重新编辑", details={"shot_id": shot.id})
    if scene_id and scene_id not in {scene.id for scene in list_scenes(db, shot.project_id)}:
        raise ValidationAppError("镜头场景不属于当前项目")
    if description is not None and not description.strip():
        raise ValidationAppError("镜头描述不能为空")
    if duration_seconds is not None:
        try:
            seconds = float(duration_seconds)
        except (TypeError, ValueError) as exc:
            raise ValidationAppError("镜头时长必须为有效数字") from exc
        if not isfinite(seconds) or not 0 < seconds <= 60:
            raise ValidationAppError("镜头时长必须大于0且不超过60秒")
    before = shot_edit_fingerprint(shot)
    if description is not None:
        shot.description = description
    if action is not None:
        shot.action = action
    if camera is not None:
        shot.camera = camera
    if dialogue is not None:
        shot.dialogue = dialogue
    if duration_seconds is not None:
        shot.duration_seconds = seconds
    if visual_prompt is not None:
        shot.visual_prompt = visual_prompt
    if negative_prompt is not None:
        shot.negative_prompt = negative_prompt
    if scene_id is not None:
        shot.scene_id = scene_id
    changed = before != shot_edit_fingerprint(shot)
    if changed:
        shot.approved = False
        board.approved = False
        board.status = "draft"
        if shot.visual_prompt:
            shot.status = ShotStatus.PROMPT_READY.value
    db.flush()
    return shot


def validate_directing_request(
    db: Session,
    *,
    project: Project,
    base_script_id: str | None = None,
    base_script_fingerprint: str | None = None,
    instruction: str = "",
    shots_target: int | None = None,
) -> dict:
    """模型调用前统一校验基线和参数，供HTTP预检与任务再次执行时复用。

    显式旧基线直接拒绝；旧无请求体入口继续使用最新已保存稿和项目镜头设置。
    这里不强制独立审核人物／场景；完整工作流仍由已有第一审核关卡控制。
    """
    script = latest_script(db, project.id)
    if script is None:
        raise WorkflowError("还没有剧本，无法生成导演规划")
    if base_script_id is not None and base_script_id != script.id:
        raise ConflictError(
            "剧本版本已更新，请刷新后基于最新稿生成导演规划",
            details={"base_script_id": base_script_id, "current_script_id": script.id},
        )
    if base_script_fingerprint is not None:
        assert_script_baseline(db, project.id, script.id, base_script_fingerprint)
    target = shots_target if shots_target is not None else (project.settings or {}).get("shots_target") or 6
    try:
        validated = DirectingPlanInput(shots_target=target, instruction=instruction)
    except ValidationError as exc:
        raise ValidationAppError(
            "导演创作要求或目标镜头数不合法",
            details={"errors": exc.errors(include_input=False, include_url=False)},
        ) from exc
    return {
        "base_script_id": script.id,
        "base_script_fingerprint": script_fingerprint(script),
        "instruction": validated.instruction,
        "shots_target": validated.shots_target,
    }


async def build_directing_plan(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
    base_script_id: str | None = None,
    base_script_fingerprint: str | None = None,
    instruction: str = "",
    shots_target: int | None = None,
) -> DirectingPlan:
    """基于最新剧本和人物场景投影追加导演计划。

    Args:
        project: 已授权且存在剧本的项目；上游负责人工审核前置。
        runtime: 导演模型和执行配置。

    Returns:
        新 draft DirectingPlan，包含模型及版本出处。

    Raises:
        WorkflowError: 项目没有剧本。
        Exception: 模型、Schema 与数据库错误传播。

    Notes:
        不额外强制人物/场景已批准；仅 flush、不提交，成功重放新增版本和模型用量。
    """
    request = validate_directing_request(
        db,
        project=project,
        base_script_id=base_script_id,
        base_script_fingerprint=base_script_fingerprint,
        instruction=instruction,
        shots_target=shots_target,
    )
    script = assert_script_baseline(
        db, project.id, request["base_script_id"], request["base_script_fingerprint"]
    )
    project_id = project.id
    source = {
        "id": script.id,
        "version": script.version,
        "title": script.title,
        "fingerprint": script_fingerprint(script),
    }
    # 正文只传一次，保留全文与结构；工作区状态元信息不作为导演创作事实。
    script_input = deepcopy(script.content or {})
    script_input.pop("workspace_meta", None)
    script_input.update(
        title=script.title,
        logline=script.logline,
        synopsis=script.synopsis,
        genre=script.genre,
        tone=script.tone,
    )
    characters = [character_payload(db, item) for item in list_characters(db, project.id)]
    scenes = [scene_payload(db, item) for item in list_scenes(db, project.id)]

    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="director",
        payload=DirectingPlanInput(
            script=script_input,
            characters=characters,
            scenes=scenes,
            genre=project.genre or script.genre,
            shots_target=request["shots_target"],
            instruction=request["instruction"],
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    # 与剧本编辑共用内容指纹校验；旧PATCH原位改文同样使本次生成失效。
    db.expire_all()
    try:
        assert_script_baseline(db, project_id, source["id"], source["fingerprint"])
    except ConflictError as exc:
        raise ConflictError(
            "剧本在导演规划期间发生变化，请刷新后重新生成",
            details={**exc.details, "generation_completed": True},
        ) from exc
    content = result.output.model_dump(mode="json")
    # 来源与要求均由服务端保存，模型不能伪造身份、版本或基线出处。
    content["source_script"] = source
    content["generation_request"] = {
        "instruction": request["instruction"],
        "shots_target": request["shots_target"],
    }
    version = _next_version(db, DirectingPlan.version, DirectingPlan, project_id)
    plan = DirectingPlan(
        id=new_id("plan"),
        project_id=project_id,
        version=version,
        status="draft",
        content=content,
        agent_id="director",
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        config_version=result.config_version,
    )
    db.add(plan)
    db.flush()
    return plan


def validate_storyboard_request(
    db: Session,
    *,
    project: Project,
    base_script_id: str | None = None,
    base_plan_id: str | None = None,
    refine_prompts: bool = True,
    base_script_fingerprint: str | None = None,
    base_plan_fingerprint: str | None = None,
) -> dict:
    """入队及模型执行前共用来源校验，内部指纹只由服务器冻结。"""
    script = latest_script(db, project.id)
    plan = latest_plan(db, project.id)
    if script is None or plan is None:
        raise WorkflowError("生成分镜前需要先完成剧本与导演规划")
    if base_script_id is not None and script.id != base_script_id:
        raise ConflictError("剧本版本已更新，请刷新后重新生成分镜")
    if base_plan_id is not None and plan.id != base_plan_id:
        raise ConflictError("导演规划版本已更新，请刷新后重新生成分镜")
    db.refresh(script)
    db.refresh(plan)
    if directing_source_status(db, plan)["source_status"] != "current":
        raise ConflictError("导演规划的剧本来源已过期或未记录，请重新生成导演规划")
    script_hash = script_fingerprint(script)
    plan_hash = directing_plan_fingerprint(plan)
    if base_script_fingerprint is not None and base_script_fingerprint != script_hash:
        raise ConflictError("剧本内容在排队期间发生变化，请刷新后重新生成")
    if base_plan_fingerprint is not None and base_plan_fingerprint != plan_hash:
        raise ConflictError("导演规划内容在排队期间发生变化，请刷新后重新生成")
    if not isinstance(refine_prompts, bool):
        raise ValidationAppError("提示词深化选项必须为布尔值")
    return {
        "base_script_id": script.id,
        "base_plan_id": plan.id,
        "base_script_fingerprint": script_hash,
        "base_plan_fingerprint": plan_hash,
        "refine_prompts": refine_prompts,
    }


def _validate_storyboard_references(db: Session, project_id: str, output, characters, scenes) -> None:
    """语义校验先于任何分镜/镜头写入，不静默跳过跨项目或不存在的引用。"""
    character_ids = {item.id for item in characters}
    scene_names = {item.name for item in scenes}
    for shot in output.shots:
        if shot.scene_name and shot.scene_name not in scene_names:
            raise AgentSchemaError("分镜引用了当前项目不存在的场景", details={"generation_completed": True})
        for ref in shot.characters:
            if not ref.character_id or ref.character_id not in character_ids:
                raise AgentSchemaError("分镜人物引用无效", details={"generation_completed": True})
            for field, model in [("costume_id", CharacterCostume), ("state_id", CharacterState)]:
                if value := getattr(ref, field):
                    related = db.get(model, value)
                    if (
                        related is None
                        or related.project_id != project_id
                        or related.character_id != ref.character_id
                    ):
                        raise AgentSchemaError(
                            "分镜人物服装或状态引用无效", details={"generation_completed": True}
                        )
        for line in shot.dialogue:
            if line.character_id and line.character_id not in character_ids:
                raise AgentSchemaError(
                    "分镜对白引用了当前项目不存在的人物", details={"generation_completed": True}
                )
        for asset_id in shot.reference_asset_ids:
            asset = db.get(Asset, asset_id)
            if asset is None or asset.project_id != project_id:
                raise AgentSchemaError("分镜参考资产不属于当前项目", details={"generation_completed": True})


async def _run_storyboard_refinement(db: Session, runtime: AppRuntime, **kwargs) -> None:
    # 保留原公开refine_prompts入口及可替换性，避免与请求中的布尔选项同名。
    await refine_prompts(db, runtime, **kwargs)


async def build_storyboard(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
    base_script_id: str | None = None,
    base_plan_id: str | None = None,
    refine_prompts: bool = True,
    base_script_fingerprint: str | None = None,
    base_plan_fingerprint: str | None = None,
) -> Storyboard:
    """基于同一剧本/导演快照生成非空分镜，来源变化时不保存陈旧产物。

    可选提示词深化仍是增强步骤。当前乐观校验不是分布式锁；外部模型费用不能回滚。
    """
    request = validate_storyboard_request(
        db,
        project=project,
        base_script_id=base_script_id,
        base_plan_id=base_plan_id,
        refine_prompts=refine_prompts,
        base_script_fingerprint=base_script_fingerprint,
        base_plan_fingerprint=base_plan_fingerprint,
    )
    project_id = project.id
    script = latest_script(db, project_id)
    plan = latest_plan(db, project_id)
    characters = list_characters(db, project_id)
    scenes = list_scenes(db, project_id)
    script_input = deepcopy(script.content or {})
    script_input.pop("workspace_meta", None)
    script_input.update(
        title=script.title,
        logline=script.logline,
        synopsis=script.synopsis,
        genre=script.genre,
        tone=script.tone,
    )
    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="storyboard",
        payload=StoryboardInput(
            script=script_input,
            characters=[character_payload(db, item) for item in characters],
            scenes=[scene_payload(db, item) for item in scenes],
            plan=deepcopy(plan.content or {}),
            shots_target=(plan.content or {}).get("shot_strategy", {}).get("total_shots") or 6,
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    try:
        validate_storyboard_request(db, project=project, **request)
    except AppError as exc:
        raise ConflictError("生成期间的剧本或导演来源已变化", details={"generation_completed": True}) from exc
    output = result.output
    characters = list_characters(db, project_id)
    scenes = list_scenes(db, project_id)
    _validate_storyboard_references(db, project_id, output, characters, scenes)
    version = _next_version(db, Storyboard.version, Storyboard, project_id)
    board = Storyboard(
        id=new_id("board"),
        project_id=project_id,
        version=version,
        status="draft",
        directing_plan_id=request["base_plan_id"],
        title=output.title or script.title,
        notes=output.notes,
        agent_id="storyboard",
        model_id=result.model_id,
        prompt_version=result.prompt_version,
        config_version=result.config_version,
    )
    db.add(board)
    db.flush()
    scene_by_name = {scene.name: scene.id for scene in scenes}
    shots = []
    for index, draft in enumerate(output.shots, start=1):
        shot = Shot(
            id=new_id("shot"),
            project_id=project_id,
            storyboard_id=board.id,
            scene_id=scene_by_name.get(draft.scene_name, ""),
            order_index=index,
            status=ShotStatus.DRAFT.value,
            description=draft.description,
            action=draft.action,
            camera=draft.camera.model_dump(mode="json"),
            characters=[ref.model_dump(mode="json") for ref in draft.characters],
            dialogue=[line.model_dump(mode="json") for line in draft.dialogue],
            duration_seconds=draft.duration_seconds,
            visual_prompt=draft.visual_prompt,
            negative_prompt=draft.negative_prompt,
            reference_asset_ids=list(draft.reference_asset_ids),
            config_version=result.config_version,
        )
        db.add(shot)
        db.flush()
        for ref in draft.characters:
            db.add(
                ShotCharacter(
                    id=new_id("shotchar"),
                    project_id=project_id,
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
    if refine_prompts:
        await _run_storyboard_refinement(
            db,
            runtime,
            project=project,
            shots=shots,
            plan=plan,
            task=task,
            workflow_run_id=workflow_run_id,
            user_id=user_id,
        )
    try:
        validate_storyboard_request(db, project=project, **request)
    except AppError as exc:
        # 深化可能已产生真实用量，删除候选业务行再让独立任务保留审计，不能提交陈旧分镜。
        shot_ids = [shot.id for shot in shots]
        db.execute(delete(ShotCharacter).where(ShotCharacter.shot_id.in_(shot_ids)))
        db.execute(delete(Shot).where(Shot.id.in_(shot_ids)))
        db.delete(board)
        db.flush()
        raise ConflictError("提示词深化期间来源已变化", details={"generation_completed": True}) from exc
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
    """逐镜头尝试更新提示词与生成出处。

    Args:
        shots: 调用方已授权且属于 project 的镜头。
        plan: None 时读取项目最新计划。

    Returns:
        None；不是所有镜头均成功精化的保证。

    Notes:
        单项调用异常记录后继续，失败镜头保留原值；成功项置 prompt_ready。
        只 flush、不提交；重复调用可再次产生模型用量并覆盖提示词。
    """
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
