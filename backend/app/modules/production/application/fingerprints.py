"""制作内容的稳定指纹，不包含审批状态与媒体生成后的选择标记。"""

from __future__ import annotations

import hashlib
import json

from app.modules.platform.exceptions import ValidationAppError
from app.modules.production.infrastructure.persistence.models import DirectingPlan, Shot


def content_fingerprint(value: dict) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise ValidationAppError("制作内容包含不能保存的非有限数字或值") from exc
    return hashlib.sha256(encoded).hexdigest()


def shot_edit_fingerprint(shot: Shot) -> str:
    return content_fingerprint(
        {
            "id": shot.id,
            "storyboard_id": shot.storyboard_id,
            "order": shot.order_index,
            "scene_id": shot.scene_id,
            "description": shot.description,
            "action": shot.action,
            "camera": shot.camera or {},
            "characters": shot.characters or [],
            "dialogue": shot.dialogue or [],
            "duration_seconds": shot.duration_seconds,
            "visual_prompt": shot.visual_prompt,
            "negative_prompt": shot.negative_prompt,
            "reference_asset_ids": shot.reference_asset_ids or [],
        }
    )


def directing_plan_fingerprint(plan: DirectingPlan) -> str:
    return content_fingerprint({"id": plan.id, "content": plan.content or {}})
