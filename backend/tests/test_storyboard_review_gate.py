"""第二审核关：批准本身不改变内容指纹，编辑后不能沿用旧批准续跑。"""

from __future__ import annotations

import pytest

from app.models.ops import WorkflowRun
from app.models.project import Project
from app.modules.platform.configuration.config_models import WorkflowNodeConfig
from app.modules.platform.exceptions import ConflictError
from app.modules.platform.persistence.session import session_scope
from app.modules.production import public as production
from app.modules.reviews import public as reviews
from app.modules.workflow.public import WorkflowEngine


def test_workflow_second_gate_rechecks_approved_content_without_starting_media(
    client, headers, project, runtime
):
    pid = project["id"]
    response = client.post(
        f"/api/v1/projects/{pid}/scripts",
        headers=headers,
        json={"title": "审核基线", "script_text": "第一场 书店 夜\n灯仍亮着。"},
    )
    assert response.status_code == 201
    assert (
        client.post(f"/api/v1/projects/{pid}/direct?wait=true", headers=headers).json()["task"]["status"]
        == "succeeded"
    )
    generated = client.post(
        f"/api/v1/projects/{pid}/storyboards?wait=true",
        headers=headers,
        json={"refine_prompts": False},
    )
    assert generated.json()["task"]["status"] == "succeeded", generated.text
    node = WorkflowNodeConfig(id="review_storyboard", type="gate", review_stage="storyboard")
    engine = WorkflowEngine(runtime)
    with session_scope() as db:
        owner = db.get(Project, pid)
        run = WorkflowRun(project_id=pid, definition_id="novel_to_video", state={"outputs": {}})
        db.add(run)
        db.flush()
        review = reviews.create_review(
            db,
            project=owner,
            stage="storyboard",
            workflow_run_id=run.id,
            target_type="workflow_node",
            target_id=node.id,
        )
        assert review.target_type == "workflow_node" and review.target_id == node.id
        assert review.decision["storyboard_snapshot"]["storyboard_id"]
        reviews.decide(db, project=owner, review=review, status="approved")
        # approval/status均排除在内容指纹之外，刚通过的快照可以正常经过当前关卡。
        assert engine._handle_gate(db, run=run, project=owner, node=node) == "approved"
        shot = production.list_shots(db, pid)[0]
        production.update_shot(
            db, shot=shot, description=shot.description, negative_prompt=shot.negative_prompt
        )
        assert production.latest_board(db, pid).approved and shot.approved
        production.update_shot(db, shot=shot, negative_prompt="批准后明确修改的负提示词")
        with pytest.raises(ConflictError):
            engine._handle_gate(db, run=run, project=owner, node=node)
        assert review.status == "approved"  # 历史人工决定保留，不能用它批准新内容。
        assert not production.latest_board(db, pid).approved
