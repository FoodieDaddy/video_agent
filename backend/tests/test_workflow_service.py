"""Workflow engine semantics that are easy to regress.

The engine persists a run cursor, so a review gate must be resumable and a
rejected review must re-open the gate instead of failing the whole run.
"""

from __future__ import annotations

import asyncio

from app.core.constants import ReviewStatus
from app.db.session import session_scope
from app.models.ops import Review
from app.models.project import Project
from app.services import documents, projects, reviews
from app.services import workflow as workflow_service


def run_to_first_gate(runtime, project_id: str):
    """Blocking helper: ingest the sample novel and run until the first gate."""

    async def scenario() -> tuple:
        with session_scope() as db:
            project = db.get(Project, project_id)
            documents.ingest_sample(db, runtime, project=project, user_id="tester")
            engine = workflow_service.WorkflowEngine(runtime)
            run = await engine.start(db, project=project, task=None, user_id="tester")
            return run.id, run.pending_review_id, run.status

    return asyncio.run(scenario())


def test_rejected_gate_reopens_a_fresh_review(client, runtime, headers, project):
    project_id = project["id"]
    run_id, first_review_id, status = run_to_first_gate(runtime, project_id)
    assert status == "awaiting_review"
    assert first_review_id

    async def scenario() -> tuple[str, str, str]:
        with session_scope() as db:
            project_row = db.get(Project, project_id)
            run = workflow_service.get_run(db, project_id, run_id)
            review = db.get(Review, first_review_id)
            reviews.decide(
                db,
                project=project_row,
                review=review,
                status=ReviewStatus.REJECTED.value,
                comment="人物设定需要重写",
                reviewer_id="tester",
            )
            db.commit()

            engine = workflow_service.WorkflowEngine(runtime)
            resumed = await engine.resume(db, run=run, project=project_row, user_id="tester")
            return resumed.id, resumed.pending_review_id, resumed.status

    _, reopened_id, resumed_status = asyncio.run(scenario())
    assert resumed_status == "awaiting_review"
    # A rejection parks a *new* review so the same gate can be re-reviewed.
    assert reopened_id and reopened_id != first_review_id


def test_workflow_run_public_exposes_checkpoints(client, runtime, headers, project):
    project_id = project["id"]
    run_id, _, _ = run_to_first_gate(runtime, project_id)

    response = client.get(f"/api/v1/projects/{project_id}/workflows/{run_id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["run"]["status"] == "awaiting_review"
    assert body["checkpoints"]
    assert all(checkpoint["node_id"] for checkpoint in body["checkpoints"])


def test_project_summary_tracks_versions(client, runtime, headers, project):
    project_id = project["id"]
    run_to_first_gate(runtime, project_id)

    summary = client.get(f"/api/v1/projects/{project_id}/summary", headers=headers).json()
    assert summary["script_version"] >= 1
    assert summary["characters"]
    assert summary["scenes"]

    with session_scope() as db:
        row = db.get(Project, project_id)
        assert projects.get_project(db, row.id, "tester").id == project_id
