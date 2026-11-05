"""制作结构指标与评估报告用例。

调用方负责项目权限；查询不提交，评估写入只 flush。
当前指标含规则估值，Evaluation Agent 读取指标与摘要，并未在此直接观看视频或听取音轨。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.character import CharacterAsset, CharacterProfile
from app.models.ops import Task
from app.models.project import Asset, Project
from app.modules.ai_runtime.public import run_agent
from app.modules.characters import public as character_module
from app.modules.platform.constants import AssetKind
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.ids import new_id
from app.modules.production.application import queries as production_queries
from app.modules.production.application.editing import latest_editing, latest_film_asset
from app.modules.production.infrastructure.persistence.models import (
    AudioTrack,
    EvaluationResult,
    EvaluationRun,
    VideoGeneration,
)
from app.schemas.evaluation import EvaluationInput

logger = logging.getLogger(__name__)


def collect_metrics(db: Session, project: Project, *, stage: str = "final") -> dict[str, Any]:
    """收集资产数量、选中引用覆盖、审批数量和时间线等当前结构指标。

    Args:
        db: 当前 Session；调用方已授权 project。
        project: 待汇总项目。
        stage: 写入指标的阶段标签，不改变采集算法。

    Returns:
        指标字典；角色一致性是按档案/图片存在性给出的规则估值，非视觉实测。

    Notes:
        selected 引用和记录数量不等于媒体可解码、实际画面一致或审核完整。
        本查询不写入、不提交，返回的是当前读取结果而非冻结评估快照。
    """
    shots = production_queries.list_shots(db, project.id)
    shot_ids = [shot.id for shot in shots]
    videos = 0
    if shot_ids:
        videos = int(
            db.scalar(
                select(func.count(VideoGeneration.id)).where(
                    VideoGeneration.shot_id.in_(shot_ids), VideoGeneration.asset_id != ""
                )
            )
            or 0
        )
    shots_with_video = sum(1 for shot in shots if shot.selected_video_id)
    audio_tracks = int(
        db.scalar(select(func.count(AudioTrack.id)).where(AudioTrack.project_id == project.id)) or 0
    )
    subtitle = db.scalar(
        select(Asset)
        .where(Asset.project_id == project.id, Asset.kind == AssetKind.SUBTITLE.value)
        .order_by(Asset.created_at.desc())
    )
    film = latest_film_asset(db, project.id)
    characters = character_module.list_characters(db, project.id)
    profiles = int(
        db.scalar(select(func.count(CharacterProfile.id)).where(CharacterProfile.project_id == project.id))
        or 0
    )
    character_images = int(
        db.scalar(select(func.count(CharacterAsset.id)).where(CharacterAsset.project_id == project.id)) or 0
    )
    approved_shots = sum(1 for shot in shots if shot.approved)
    editing = latest_editing(db, project.id)

    dialogue_lines = sum(len(shot.dialogue or []) for shot in shots)
    coverage = round(shots_with_video / len(shots), 3) if shots else 0.0
    character_consistency = 0.85 if character_images and profiles else 0.55
    if characters and character_images >= len(characters):
        character_consistency = 0.9

    return {
        "stage": stage,
        "shots": len(shots),
        "shots_with_video": shots_with_video,
        "video_candidates": videos,
        "video_coverage": coverage,
        "approved_shots": approved_shots,
        "audio_tracks": audio_tracks,
        "dialogue_lines": dialogue_lines,
        "subtitles": bool(subtitle),
        "character_count": len(characters),
        "character_profiles": profiles,
        "character_assets": character_images,
        "character_consistency": character_consistency,
        "total_duration_seconds": round(sum(float(shot.duration_seconds or 0) for shot in shots), 2),
        "render_status": (editing.status if editing else ""),
        "rendered": bool(film),
        "final_video": bool(film),
        "budget_usd": round(float(project.spent_usd or 0.0), 4),
    }


async def evaluate_project(
    db: Session,
    runtime: AppRuntime,
    *,
    project: Project,
    stage: str = "final",
    metrics: dict[str, Any] | None = None,
    task: Task | None = None,
    workflow_run_id: str = "",
    user_id: str = "",
) -> EvaluationRun:
    """基于给定或当前采集指标调用评估 Agent，并保存报告及维度明细。

    Args:
        db: 外层事务 Session，仅 flush、不提交。
        runtime: 评估 Agent 的模型和配置能力。
        project: 已授权项目。
        metrics: None 或空字典时重新采集结构指标。

    Returns:
        completed 的 EvaluationRun，表示报告已生成，不表示影片已通过业务终审。

    Raises:
        Exception: 模型、Schema 和持久化错误传播。

    Notes:
        输入是指标与项目摘要，不是完整视听检查；规则估值不能当作准确率。
        记录模型/提示词/配置版本；重复执行会追加报告并可能再次产生模型费用。
    """
    metrics = metrics or collect_metrics(db, project, stage=stage)
    summary = production_queries.project_summary(db, project)
    result = await run_agent(
        db,
        runtime,
        project=project,
        agent_id="evaluation",
        payload=EvaluationInput(
            stage=stage,
            metrics=metrics,
            project_summary=summary,
            thresholds=runtime.config_store.agent("evaluation").evaluation.thresholds,
        ),
        task=task,
        workflow_run_id=workflow_run_id,
        user_id=user_id,
    )
    report = result.output
    run = EvaluationRun(
        id=new_id("eval"),
        project_id=project.id,
        stage=stage,
        status="completed",
        overall_score=float(report.overall_score),
        recommendation=report.recommendation,
        report={"metrics": metrics, "summary": report.summary, "scores": report.scores},
        agent_id="evaluation",
        model_id=result.model_id,
        config_version=result.config_version,
        prompt_version=result.prompt_version,
    )
    db.add(run)
    db.flush()

    for dimension, score in report.scores.items():
        db.add(
            EvaluationResult(
                id=new_id("evalres"),
                project_id=project.id,
                evaluation_run_id=run.id,
                dimension=dimension,
                score=float(score or 0.0),
            )
        )
    for issue in report.issues:
        db.add(
            EvaluationResult(
                id=new_id("evalres"),
                project_id=project.id,
                evaluation_run_id=run.id,
                dimension=issue.type,
                score=0.0,
                issue_type=issue.type,
                severity=issue.severity,
                description=issue.description,
            )
        )
    db.flush()
    logger.info("evaluation for project %s: %.2f (%s)", project.id, run.overall_score, run.recommendation)
    return run


def latest_evaluation(db: Session, project_id: str) -> EvaluationRun | None:
    """按创建时间降序读取项目最新评估，无记录返回 None；只读，不代表已人工接受报告。"""
    return db.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.project_id == project_id)
        .order_by(EvaluationRun.created_at.desc())
    )


def evaluation_public(db: Session, run: EvaluationRun) -> dict:
    """读取维度结果并投影评估 API 字典；不执行模型或写入，不额外验证评分事实依据。"""
    results = list(db.scalars(select(EvaluationResult).where(EvaluationResult.evaluation_run_id == run.id)))
    return {
        "id": run.id,
        "stage": run.stage,
        "status": run.status,
        "overall_score": run.overall_score,
        "recommendation": run.recommendation,
        "summary": (run.report or {}).get("summary", ""),
        "report": run.report or {},
        "scores": {row.dimension: row.score for row in results if row.dimension and not row.issue_type},
        "issues": [
            {
                "type": row.issue_type or row.dimension,
                "severity": row.severity,
                "description": row.description,
            }
            for row in results
            if row.issue_type
        ],
        "model_id": run.model_id,
        "config_version": run.config_version,
        "prompt_version": run.prompt_version,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
