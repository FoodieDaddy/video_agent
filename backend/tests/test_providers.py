"""Provider adapter contracts that do not need a live server."""

from __future__ import annotations

import asyncio
import json

import httpx

from app.providers.base import VideoRequest
from app.providers.openai_compat import OpenAIVideosProvider, _extract_json


def test_extract_json_ignores_reasoning_trace():
    """A local reasoning model narrates before answering and closes with ``</think>``."""
    text = (
        'The user wants JSON only, specifically {"ok": true} and nothing else.\n'
        '</think>{"ok": true}'
    )
    assert _extract_json(text) == {"ok": True}


def test_extract_json_prefers_outer_object():
    assert _extract_json('Sure!\n```json\n{"a": {"b": 1}}\n```\n') == {"a": {"b": 1}}
    assert _extract_json('{"shots": [{"id": 1}]} trailing prose') == {"shots": [{"id": 1}]}


def _fake_transport(seen: list[httpx.Request], state: dict | None = None) -> httpx.MockTransport:
    status_body = state or {
        "id": "job1",
        "status": "succeeded",
        "output": {"mp4": "/workspace/out.mp4", "width": 256, "height": 448},
        "links": {"content": "/v1/videos/job1/content"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if request.method == "POST" and path == "/v1/videos":
            return httpx.Response(202, json={"id": "job1", "status": "queued"})
        if path == "/v1/videos/job1":
            return httpx.Response(200, json=status_body)
        if path == "/v1/videos/job1/content":
            return httpx.Response(200, content=b"MP4-BYTES")
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


def _provider(monkeypatch, **extra) -> tuple[OpenAIVideosProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    transport = _fake_transport(seen)
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    options = {
        "base_url": "http://127.0.0.1:8090/v1",
        "api_key": "minimax",
        "timeout_seconds": 30,
        "poll_interval_seconds": 0,
        "max_wait_seconds": 5,
        "submit_path": "/videos",
        "status_path": "/videos",
        "content_suffix": "/content",
        "request_defaults": {"steps": 8, "seed": 42},
    }
    options.update(extra)
    return OpenAIVideosProvider("minimax", "minimax-h3", options), seen


def test_openai_videos_submits_polls_and_downloads(monkeypatch):
    provider, seen = _provider(monkeypatch)
    request = VideoRequest(prompt="雪山下的湖泊，晨雾", duration_seconds=5.0, width=256, height=448)

    result = asyncio.run(provider.generate(request))

    assert result.content == b"MP4-BYTES"
    assert result.task_ref == "job1"
    assert result.model_id == "minimax-h3"
    assert result.meta["output"]["mp4"] == "/workspace/out.mp4"

    submit = json.loads(seen[0].content)
    assert seen[0].method == "POST"
    assert str(seen[0].url) == "http://127.0.0.1:8090/v1/videos"
    assert submit["prompt"] == "雪山下的湖泊，晨雾"
    assert submit["duration_seconds"] == 5.0
    assert submit["width"] == 256 and submit["height"] == 448
    assert submit["steps"] == 8 and submit["seed"] == 42
    # Only the declared fields are sent; this service rejects frame inputs.
    assert "image_path" not in submit
    assert seen[0].headers["authorization"] == "Bearer minimax"
    assert str(seen[-1].url) == "http://127.0.0.1:8090/v1/videos/job1/content"


def test_openai_videos_clamps_duration_to_service_limit(monkeypatch):
    provider, seen = _provider(monkeypatch, max_duration_seconds=14)
    request = VideoRequest(prompt="长镜头", duration_seconds=20.0)

    asyncio.run(provider.generate(request))

    submit = json.loads(seen[0].content)
    assert submit["duration_seconds"] == 14.0
    assert provider._job_payload(request)["duration_seconds"] == 14.0


def test_openai_videos_reports_failed_jobs(monkeypatch):
    seen: list[httpx.Request] = []
    transport = _fake_transport(seen, {"id": "job1", "status": "failed", "error": "CUDA OOM"})
    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    provider = OpenAIVideosProvider(
        "minimax",
        "minimax-h3",
        {"base_url": "http://127.0.0.1:8090/v1", "poll_interval_seconds": 0, "max_wait_seconds": 5},
    )

    try:
        asyncio.run(provider.generate(VideoRequest(prompt="x")))
    except Exception as exc:  # noqa: BLE001 - error type is the assertion
        assert "CUDA OOM" in str(exc)
    else:  # pragma: no cover - a failed job must never succeed
        raise AssertionError("a failed video job must raise")


def test_video_protocols_are_registered():
    from app.providers.registry import _PROTOCOL_IMPLS

    assert _PROTOCOL_IMPLS[("video", "openai_videos")] is OpenAIVideosProvider
    assert ("video", "http_task") in _PROTOCOL_IMPLS
