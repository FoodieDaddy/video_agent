"""按稳定标识调用制作能力，实体读取留在制作模块。"""

from sqlalchemy.orm import Session

from app.modules.platform.exceptions import NotFoundError
from app.modules.platform.execution.runtime import AppRuntime
from app.modules.platform.persistence.models import Task
from app.modules.production.infrastructure.persistence.models import Shot
from app.modules.projects.contracts import ProjectContext

from .shot_video import generate_shot_videos


async def generate_shot_video_by_id(
    db: Session,
    runtime: AppRuntime,
    *,
    project: ProjectContext,
    shot_id: str,
    task: Task | None = None,
    user_id: str = "",
    stop=None,
) -> dict:
    """校验镜头项目归属后执行原生成用例；调用方管理事务与取消。"""
    shot = db.get(Shot, shot_id)
    if shot is None or shot.project_id != project.id:
        raise NotFoundError("镜头不存在", details={"shot_id": shot_id})
    return await generate_shot_videos(
        db, runtime, project=project, shots=[shot], task=task, user_id=user_id, stop=stop
    )
