"""End-to-end smoke run of the offline (mock provider) pipeline.

Usage:
    python scripts/smoke_pipeline.py

It creates an isolated SQLite database and storage directory, ingests the sample
novel, runs the full ``novel_to_video`` workflow, auto-approves every review gate
and prints the resulting artifacts.  Useful as a fast regression check and as
living documentation of the service layer.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from app.core.constants import ReviewStatus  # noqa: E402
from app.core.settings import load_settings  # noqa: E402
from app.db.session import init_engine, init_schema, session_scope  # noqa: E402
from app.models.ops import Review  # noqa: E402
from app.services import documents, media, pipeline, projects, quality, reviews, workflow  # noqa: E402
from app.services.runtime import build_runtime  # noqa: E402


async def main() -> int:
    from studio_api.bootstrap.composition import configure_application

    configure_application()
    data_dir = Path(tempfile.mkdtemp(prefix="studio_smoke_"))
    # This run is offline by definition: never reach a configured real provider.
    os.environ.setdefault("AGENT_MODEL_PROVIDER", "mock")
    settings = load_settings(data_dir=data_dir)
    init_engine(settings)
    init_schema()
    runtime = build_runtime(settings)
    print(f"data dir: {data_dir}")
    print(f"ffmpeg  : {settings.ffmpeg_bin}")

    with session_scope() as db:
        project = projects.create_project(
            db,
            owner_id="user_demo",
            name="雨夜书店",
            description="离线冒烟测试项目",
            genre="悬疑",
        )
        document = documents.ingest_sample(db, runtime, project=project, user_id="user_demo")
        print(f"document: {document.filename} -> {document.meta.get('chapter_count')} chapters")

        engine = workflow.WorkflowEngine(runtime)
        run = await engine.start(db, project=project, task=None, user_id="user_demo")
        gates = 0
        while run.status == "awaiting_review":
            gates += 1
            review = db.get(Review, run.pending_review_id)
            print(f"gate {gates}: {review.stage} -> approve")
            reviews.decide(
                db,
                project=project,
                review=review,
                status=ReviewStatus.APPROVED.value,
                comment="smoke auto approval",
                reviewer_id="user_demo",
            )
            db.commit()
            run = await engine.resume(db, run=run, project=project, user_id="user_demo")

        print(f"workflow status: {run.status} error={run.error or '-'}")

        script = pipeline.latest_script(db, project.id)
        board = pipeline.latest_board(db, project.id)
        shots = pipeline.list_shots(db, project.id)
        editing = media.latest_editing(db, project.id)
        evaluation = quality.latest_evaluation(db, project.id)
        print(f"script    : v{script.version if script else 0} {script.title if script else ''}")
        print(f"characters: {[c.name for c in pipeline.list_characters(db, project.id)]}")
        print(f"scenes    : {[s.name for s in pipeline.list_scenes(db, project.id)]}")
        print(f"storyboard: v{board.version if board else 0} shots={len(shots)}")
        print(f"shot status: {sorted({shot.status for shot in shots})}")
        print(f"videos    : {sum(1 for shot in shots if shot.selected_video_id)}/{len(shots)}")
        print(f"audio     : {len(media.audio_tracks(db, project.id))} tracks")
        print(f"editing   : {editing.status if editing else '-'} dur={editing.duration_seconds if editing else 0}")
        print(f"evaluation: {evaluation.overall_score if evaluation else '-'} {evaluation.recommendation if evaluation else ''}")
        print(f"project   : {project.status} spent=${project.spent_usd:.4f}")
        if evaluation is not None:
            print(f"metrics   : {evaluation.report.get('metrics')}")
        return 0 if run.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
