"""项目值快照与所属模块写操作的事务合约。"""

from dataclasses import FrozenInstanceError

import pytest
from sqlalchemy.orm import Session

from app.modules.projects.public import (
    create_project,
    find_project_context,
    record_project_cost,
    touch_status,
)


def test_task_context_is_detached_while_project_writes_follow_outer_transaction(app, client):
    from app.modules.platform.persistence.session import get_engine

    engine = get_engine()
    with Session(engine, expire_on_commit=False) as db:
        project = create_project(db, owner_id="context-owner", name="快照", settings={"shots_target": 6})
        db.commit()
        project_id = project.id
        context = find_project_context(db, project_id)
        assert context is not None
        context.settings["shots_target"] = 12
        assert project.settings["shots_target"] == 6
        with pytest.raises(FrozenInstanceError):
            context.id = "another"

        record_project_cost(db, project_id, 0.1234567)
        touch_status(db, context, "script_ready")
        assert project.spent_usd == 0.123457
        assert project.status == "script_ready"
        assert context.spent_usd == 0.0
        db.rollback()
        assert project.spent_usd == 0.0
        assert project.status == "draft"

    assert context.name == "快照"
