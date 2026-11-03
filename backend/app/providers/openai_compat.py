"""HTTP providers.

* ``OpenAICompatibleProvider`` - chat/vision/image/speech over the OpenAI HTTP
  contract.  Any compatible gateway (Azure-style proxies, self-hosted vLLM,
  Together, DashScope compatible mode ...) works by pointing the provider's
  ``url`` at the gateway (``url: env:OPENAI_COMPAT_BASE_URL`` for instance).
* ``HttpTaskVideoProvider`` - a deliberately small, documented contract for
  commercial video APIs: submit -> poll -> download.

Provider YAML names the environment variable holding a credential
(``api_key: env:OPENAI_API_KEY``) instead of storing the secret itself.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.exceptions import ProviderError, ProviderUnavailableError
from app.providers.base import (
    AudioProvider,
    AudioRequest,
    AudioResult,
    ImageProvider,
    ImageRequest,
    ImageResult,
    LLMProvider,
    LLMRequest,
    LLMResult,
    VideoProvider,
    VideoRequest,
    VideoResult,
    VisionProvider,
    VisionRequest,
)
from app.utils import ffmpeg, narrative

DEFAULT_BASE_URL = "https://api.openai.com/v1"
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a model reply.

    Reasoning models often narrate before answering and close the trace with
    ``<｜end▁of▁thinking｜>``, and some keep prose *after* the object, so a plain
    ``json.loads`` on the whole string is not enough. Candidate sources are
    tried in order and the decoding that covers the most text wins, which
    prefers an outermost object over one nested inside it.
    """
    candidate = text.strip()
    sources: list[str] = []
    fenced = _JSON_FENCE.search(candidate)
    if fenced:
        sources.append(fenced.group(1).strip())
    if "</think" in candidate:
        sources.append(candidate.rsplit("</think", 1)[-1].lstrip(">").strip())
    sources.append(candidate)

    best: tuple[int, int, dict[str, Any]] | None = None
    decoder = json.JSONDecoder()
    for source in sources:
        for index, char in enumerate(source):
            if char != "{":
                continue
            try:
                payload, end = decoder.raw_decode(source, index)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            score = (end, -index)
            if best is None or score > best[:2]:
                best = (end, -index, payload)
        if best is not None:
            break
    if best is None:
        raise ProviderError(f"Provider returned non-JSON output: {text[:400]}")
    return best[2]


def _data_url(content: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


class _HttpProviderMixin:
    options: dict[str, Any]

    def _client(self) -> httpx.AsyncClient:
        timeout = float(self.options.get("timeout_seconds") or 120)
        base_url = (self.options.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        return httpx.AsyncClient(base_url=base_url, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        api_key = self.options.get("api_key") or ""
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        extra = self.options.get("headers") or {}
        headers.update({str(key): str(value) for key, value in extra.items()})
        return headers

    def _cost(self, *, tokens_in: int = 0, tokens_out: int = 0, units: float = 0.0) -> float:
        input_price = float(self.options.get("input_cost_per_1k") or 0.0)
        output_price = float(self.options.get("output_cost_per_1k") or 0.0)
        unit_price = float(self.options.get("unit_cost") or 0.0)
        return round(
            (tokens_in / 1000.0) * input_price
            + (tokens_out / 1000.0) * output_price
            + units * unit_price,
            6,
        )


class OpenAICompatibleLLMProvider(_HttpProviderMixin, LLMProvider):
    capability = "llm"

    def __init__(self, name: str, model_id: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(name=name, model_id=model_id, options=options)

    async def health(self) -> bool:
        if not self.options.get("api_key"):
            return False
        try:
            async with self._client() as client:
                response = await client.get("/models", headers=self._headers())
                return response.status_code < 500
        except httpx.HTTPError:
            return False

    async def generate(self, request: LLMRequest) -> LLMResult:
        if not self.options.get("api_key"):
            raise ProviderUnavailableError(
                f"Provider '{self.name}' has no API key; set the environment variable declared in its config"
            )
        generation = request.generation
        max_tokens_field = self.options.get("max_tokens_field", "max_tokens")
        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
        }
        if generation.temperature is not None:
            payload["temperature"] = generation.temperature
        if generation.top_p is not None:
            payload["top_p"] = generation.top_p
        if generation.seed is not None and self.options.get("supports_seed", True):
            payload["seed"] = generation.seed
        if generation.max_output_tokens:
            payload[max_tokens_field] = generation.max_output_tokens
        if request.response_schema:
            payload["response_format"] = {"type": "json_object"}
        # 模块 1 关键点：供应商 YAML 里的 extra.request_defaults 在最后合并，
        # 所以 reasoning_effort（本机 vLLM 必填）这类网关参数会覆盖上面生成的字段。
        payload.update(self.options.get("request_defaults") or {})

        started = time.perf_counter()
        async with self._client() as client:
            response = await client.post("/chat/completions", headers=self._headers(), json=payload)
        latency_ms = (time.perf_counter() - started) * 1000
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name} chat completions failed ({response.status_code}): {response.text[:400]}"
            )
        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"Unexpected provider response: {body}") from exc

        usage = body.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
        structured = _extract_json(content) if request.response_schema else None
        return LLMResult(
            text=content,
            structured=structured,
            provider=self.name,
            model_id=self.model_id,
            request_id=str(body.get("id") or ""),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self._cost(tokens_in=tokens_in, tokens_out=tokens_out),
            meta={"latency_ms": round(latency_ms, 1)},
        )


class OpenAICompatibleVisionProvider(_HttpProviderMixin, VisionProvider):
    capability = "vision"

    def __init__(self, name: str, model_id: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(name=name, model_id=model_id, options=options)

    async def health(self) -> bool:
        return bool(self.options.get("api_key"))

    async def describe(self, request: VisionRequest) -> LLMResult:
        # Reuse the chat contract with a multimodal user message.
        generation = request.generation
        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": request.system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": request.user},
                        {
                            "type": "image_url",
                            "image_url": {"url": _data_url(request.image_bytes, request.mime)},
                        },
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
        }
        if generation.temperature is not None:
            payload["temperature"] = generation.temperature
        if generation.max_output_tokens:
            payload["max_tokens"] = generation.max_output_tokens
        payload.update(self.options.get("request_defaults") or {})

        async with self._client() as client:
            response = await client.post("/chat/completions", headers=self._headers(), json=payload)
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name} vision request failed ({response.status_code}): {response.text[:400]}"
            )
        body = response.json()
        content = body.get("choices", [{}])[0].get("message", {}).get("content") or ""
        usage = body.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
        structured = _extract_json(content) if request.response_schema else None
        return LLMResult(
            text=content,
            structured=structured,
            provider=self.name,
            model_id=self.model_id,
            request_id=str(body.get("id") or ""),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self._cost(tokens_in=tokens_in, tokens_out=tokens_out),
        )


class OpenAIImageProvider(_HttpProviderMixin, ImageProvider):
    capability = "image"

    def __init__(self, name: str, model_id: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(name=name, model_id=model_id, options=options)

    async def health(self) -> bool:
        return bool(self.options.get("api_key"))

    async def generate(self, request: ImageRequest) -> ImageResult:
        if not self.options.get("api_key"):
            raise ProviderUnavailableError(f"Image provider '{self.name}' has no API key")
        model_id = request.model_id or self.model_id
        size = request.provider_options.get("size") or f"{request.width}x{request.height}"
        prompt = request.prompt
        if request.negative_prompt:
            prompt = f"{prompt}\nAvoid: {request.negative_prompt}"
        async with self._client() as client:
            if request.reference_images:
                files = [
                    ("image[]", (f"reference_{index}.png", content, "image/png"))
                    for index, content in enumerate(request.reference_images)
                ]
                data = {"model": model_id, "prompt": prompt, "n": str(max(1, request.count))}
                response = await client.post(
                    "/images/edits",
                    headers={"Authorization": f"Bearer {self.options.get('api_key')}"},
                    data=data,
                    files=files,
                )
            else:
                payload = {
                    "model": model_id,
                    "prompt": prompt,
                    "n": max(1, request.count),
                    "size": size,
                    "response_format": "b64_json",
                }
                payload.update(self.options.get("request_defaults") or {})
                response = await client.post(
                    "/images/generations", headers=self._headers(), json=payload
                )
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name} image generation failed ({response.status_code}): {response.text[:400]}"
            )
        body = response.json()
        items = body.get("data") or []
        if not items:
            raise ProviderError("Image provider returned no data")
        item = items[0]
        if item.get("b64_json"):
            content = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            async with httpx.AsyncClient(timeout=120) as downloader:
                downloaded = await downloader.get(item["url"])
                downloaded.raise_for_status()
                content = downloaded.content
        else:
            raise ProviderError("Image provider response has neither b64_json nor url")

        width, height = request.width, request.height
        try:
            import io as _io

            from PIL import Image  # local import: optional for API-only deployments

            with Image.open(_io.BytesIO(content)) as probe:
                width, height = probe.size
        except Exception:  # pragma: no cover - metadata is best effort
            pass
        return ImageResult(
            content=content,
            mime="image/png",
            width=width,
            height=height,
            provider=self.name,
            model_id=model_id,
            cost_usd=self._cost(units=request.count),
            meta={"size": size},
        )


class OpenAISpeechProvider(_HttpProviderMixin, AudioProvider):
    capability = "audio"

    def __init__(self, name: str, model_id: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(name=name, model_id=model_id, options=options)

    async def health(self) -> bool:
        return bool(self.options.get("api_key"))

    async def synthesize(self, request: AudioRequest) -> AudioResult:
        if not self.options.get("api_key"):
            raise ProviderUnavailableError(f"Audio provider '{self.name}' has no API key")
        model_id = request.model_id or self.model_id
        audio_format = request.audio_format or "wav"
        payload: dict[str, Any] = {
            "model": model_id,
            "voice": request.voice or "alloy",
            "input": request.text,
            "response_format": audio_format,
            "speed": request.speed,
        }
        if request.style:
            payload["instructions"] = request.style
        payload.update(self.options.get("request_defaults") or {})
        async with self._client() as client:
            response = await client.post("/audio/speech", headers=self._headers(), json=payload)
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name} speech synthesis failed ({response.status_code}): {response.text[:400]}"
            )
        content = response.content
        duration = narrative.estimate_speech_duration(request.text)
        mime = "audio/wav" if audio_format == "wav" else f"audio/{audio_format}"
        if request.meta.get("probe_duration") and ffmpeg.binary_available(
            self.options.get("ffprobe_bin", "ffprobe")
        ):
            with tempfile.TemporaryDirectory() as tmp:
                probe_path = Path(tmp) / f"probe.{audio_format}"
                probe_path.write_bytes(content)
                duration = ffmpeg.probe_duration(probe_path, self.options.get("ffprobe_bin", "ffprobe")) or duration
        return AudioResult(
            content=content,
            mime=mime,
            duration_seconds=duration,
            provider=self.name,
            model_id=model_id,
            cost_usd=self._cost(units=len(request.text) / 1000.0),
            meta={"format": audio_format},
        )


class HttpTaskVideoProvider(_HttpProviderMixin, VideoProvider):
    """Submit/poll video provider.

    Contract (implemented by the commercial API adapter in front of the vendor):

    * ``POST {base_url}{submit_path}`` with the job payload returns ``{"id": ...}``.
    * ``GET {base_url}{status_path}/{id}`` returns
      ``{"status": "queued|running|succeeded|failed", "video_url": "...", "error": "..."}``.
    * ``POST {base_url}{cancel_path}/{id}`` cancels a job (optional).

    Adapters for a specific vendor only need to translate payload/response fields.
    """

    capability = "video"

    def __init__(self, name: str, model_id: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(name=name, model_id=model_id, options=options)
        self.submit_path = self.options.get("submit_path", "/videos")
        self.status_path = self.options.get("status_path", "/videos")
        self.cancel_path = self.options.get("cancel_path", "/videos")
        self.poll_interval = float(self.options.get("poll_interval_seconds") or 5)
        self.max_wait = float(self.options.get("max_wait_seconds") or 900)

    async def health(self) -> bool:
        return bool(self.options.get("base_url"))

    def _job_payload(self, request: VideoRequest) -> dict[str, Any]:
        payload = {
            "model": request.model_id or self.model_id,
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "duration": request.duration_seconds,
            "aspect_ratio": request.aspect_ratio,
            "width": request.width,
            "height": request.height,
        }
        if request.reference_image:
            payload["reference_image"] = _data_url(request.reference_image, "image/png")
        if request.first_frame:
            payload["first_frame"] = _data_url(request.first_frame, "image/png")
        if request.last_frame:
            payload["last_frame"] = _data_url(request.last_frame, "image/png")
        payload.update(self.options.get("request_defaults") or {})
        return payload

    async def generate(self, request: VideoRequest) -> VideoResult:
        base_url = self.options.get("base_url")
        if not base_url:
            raise ProviderUnavailableError(
                f"Video provider '{self.name}' has no endpoint configured (see its provider YAML)"
            )
        api_key = self.options.get("api_key")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=120) as client:
            submit = await client.post(self.submit_path, json=self._job_payload(request), headers=headers)
            if submit.status_code >= 400:
                raise ProviderError(
                    f"{self.name} video submit failed ({submit.status_code}): {submit.text[:400]}"
                )
            body = submit.json()
            job_id = str(body.get("id") or body.get("task_id") or body.get("request_id") or "")
            if not job_id:
                raise ProviderError(f"{self.name} video submit returned no job id: {body}")

            deadline = time.monotonic() + self.max_wait
            video_url = ""
            while time.monotonic() < deadline:
                status_response = await client.get(f"{self.status_path}/{job_id}", headers=headers)
                if status_response.status_code >= 400:
                    raise ProviderError(
                        f"{self.name} status check failed ({status_response.status_code}): "
                        f"{status_response.text[:400]}"
                    )
                status_body = status_response.json()
                status = str(status_body.get("status") or "").lower()
                if status in {"succeeded", "completed", "success", "done"}:
                    video_url = (
                        status_body.get("video_url")
                        or status_body.get("output_url")
                        or (status_body.get("output") or {}).get("video_url")
                        or ""
                    )
                    break
                if status in {"failed", "error", "cancelled", "canceled"}:
                    raise ProviderError(
                        f"{self.name} video job {job_id} failed: {status_body.get('error') or status_body}"
                    )
                await asyncio.sleep(self.poll_interval)
            if not video_url:
                raise ProviderError(f"{self.name} video job {job_id} timed out after {self.max_wait}s")

            async with httpx.AsyncClient(timeout=300) as downloader:
                downloaded = await downloader.get(video_url)
                downloaded.raise_for_status()
                content = downloaded.content

        duration = request.duration_seconds
        return VideoResult(
            content=content,
            mime="video/mp4",
            duration_seconds=duration,
            provider=self.name,
            model_id=request.model_id or self.model_id,
            task_ref=job_id,
            cost_usd=self._cost(units=duration),
            meta={"job_id": job_id, "video_url": video_url},
        )

    async def cancel(self, task_ref: str) -> bool:
        base_url = self.options.get("base_url")
        if not base_url:
            return False
        headers = {"Content-Type": "application/json"}
        if self.options.get("api_key"):
            headers["Authorization"] = f"Bearer {self.options.get('api_key')}"
        async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=60) as client:
            response = await client.post(f"{self.cancel_path}/{task_ref}/cancel", headers=headers)
            return response.status_code < 400


class LocalWorkerVideoProvider(HttpTaskVideoProvider):
    """Video provider that talks to a local GPU worker (Wan + ComfyUI style)."""

    capability = "video"

    def __init__(self, name: str, model_id: str, options: dict[str, Any] | None = None) -> None:
        options = dict(options or {})
        options.setdefault("max_wait_seconds", float(os.getenv("LOCAL_VIDEO_MAX_WAIT", "1800")))
        super().__init__(name, model_id, options)


class OpenAIVideosProvider(_HttpProviderMixin, VideoProvider):
    """Submit/poll/download against an OpenAI-style ``/v1/videos`` service.

    Contract (a local MiniMax / gateway service exposing the OpenAI video shape)::

        POST {base}{submit_path}            -> 202 {"id": "...", "status": "queued"}
        GET  {base}{status_path}/{id}       -> {"status": "queued|running|succeeded|failed",
                                                "output": {...}, "links": {"content": "/v1/videos/<id>/content"}}
        GET  {base}{status_path}/{id}{content_suffix} -> the mp4 bytes

    The difference from :class:`HttpTaskVideoProvider` is where the file comes
    from: these services answer with server-side paths (``/workspace/out.mp4``)
    and serve the bytes from their own ``/content`` route, so a URL found in the
    body is used when present and the content route is the fallback.

    Only the fields the vendor declares are sent: ``extra.request_fields`` picks
    them from the request (default ``prompt, duration_seconds, width, height``)
    and ``extra.request_defaults`` adds vendor-specific keys such as ``steps``.
    """

    capability = "video"

    _SUCCESS = {"succeeded", "completed", "success", "done"}
    _FAILURE = {"failed", "error", "cancelled", "canceled"}

    def __init__(self, name: str, model_id: str, options: dict[str, Any] | None = None) -> None:
        super().__init__(name=name, model_id=model_id, options=options)
        self.submit_path = self.options.get("submit_path", "/videos")
        self.status_path = self.options.get("status_path", "/videos")
        self.cancel_path = self.options.get("cancel_path", "/videos")
        self.content_suffix = self.options.get("content_suffix", "/content")
        self.poll_interval = float(self.options.get("poll_interval_seconds") or 5)
        self.max_wait = float(self.options.get("max_wait_seconds") or 900)
        self.max_duration = float(self.options.get("max_duration_seconds") or 0)

    async def health(self) -> bool:
        return bool(self.options.get("base_url"))

    def _job_payload(self, request: VideoRequest) -> dict[str, Any]:
        duration = request.duration_seconds
        if self.max_duration and duration > self.max_duration:
            duration = self.max_duration
        values = {
            "prompt": request.prompt,
            "negative_prompt": request.negative_prompt,
            "duration_seconds": duration,
            "duration": duration,
            "width": request.width,
            "height": request.height,
            "aspect_ratio": request.aspect_ratio,
            "model": request.model_id or self.model_id,
        }
        fields = self.options.get("request_fields") or (
            "prompt",
            "duration_seconds",
            "width",
            "height",
        )
        payload = {key: values[key] for key in fields if values.get(key) not in (None, "")}
        payload.update(self.options.get("request_defaults") or {})
        return payload

    def _absolute(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        base = str(self.options.get("base_url") or "").rstrip("/")
        base_path = urlsplit(base).path.rstrip("/")
        if path.startswith("/") and base_path and path.startswith(f"{base_path}/"):
            # The service returned a server-absolute path that already includes /v1.
            return urlunsplit(urlsplit(base)[:2] + (path, "", ""))
        return f"{base}/{path.lstrip('/')}"

    async def _fetch_content(
        self, client: httpx.AsyncClient, job_id: str, state: dict[str, Any], headers: dict[str, str]
    ) -> bytes:
        output = state.get("output") or {}
        links = state.get("links") or {}
        candidates = [
            state.get("video_url"),
            state.get("output_url"),
            state.get("url"),
            links.get("content"),
            links.get("video"),
            (output.get("video_url") if isinstance(output, dict) else None),
            f"{self.status_path}/{job_id}{self.content_suffix}",
        ]
        attempts: list[str] = []
        for candidate in candidates:
            if not candidate:
                continue
            url = self._absolute(str(candidate))
            if url in attempts:
                continue
            attempts.append(url)
            response = await client.get(url, headers=headers)
            if response.status_code < 400 and response.content:
                return response.content
        raise ProviderError(
            f"{self.name} video job {job_id} finished but no file could be downloaded; tried {attempts}"
        )

    async def generate(self, request: VideoRequest) -> VideoResult:
        base_url = str(self.options.get("base_url") or "").rstrip("/")
        if not base_url:
            raise ProviderUnavailableError(
                f"Video provider '{self.name}' has no url configured (see its provider YAML)"
            )
        headers = self._headers()
        payload = self._job_payload(request)
        dropped = [
            name
            for name in ("reference_image", "first_frame", "last_frame")
            if getattr(request, name)
        ]
        timeout = float(self.options.get("timeout_seconds") or 300)

        async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
            submit = await client.post(self.submit_path, json=payload, headers=headers)
            if submit.status_code >= 400:
                raise ProviderError(
                    f"{self.name} video submit failed ({submit.status_code}): {submit.text[:400]}"
                )
            state = submit.json() or {}
            job_id = str(
                state.get("id") or state.get("task_id") or state.get("request_id") or ""
            )
            if not job_id:
                raise ProviderError(f"{self.name} video submit returned no job id: {state}")

            deadline = time.monotonic() + self.max_wait
            while True:
                status = str(state.get("status") or "").lower()
                if status in self._SUCCESS:
                    break
                if status in self._FAILURE:
                    raise ProviderError(
                        f"{self.name} video job {job_id} failed: "
                        f"{state.get('error') or state.get('message') or state}"
                    )
                if time.monotonic() >= deadline:
                    raise ProviderError(
                        f"{self.name} video job {job_id} timed out after {self.max_wait}s"
                    )
                await asyncio.sleep(self.poll_interval)
                polled = await client.get(f"{self.status_path}/{job_id}", headers=headers)
                if polled.status_code >= 400:
                    raise ProviderError(
                        f"{self.name} status check failed ({polled.status_code}): {polled.text[:400]}"
                    )
                state = polled.json() or {}

            content = await self._fetch_content(client, job_id, state, headers)

        output = state.get("output") or {}
        duration = float(
            (output.get("duration_seconds") if isinstance(output, dict) else None)
            or request.duration_seconds
        )
        meta: dict[str, Any] = {"job_id": job_id, "request": payload}
        if self.max_duration and request.duration_seconds > self.max_duration:
            meta["duration_clamped_from"] = request.duration_seconds
        if isinstance(output, dict):
            meta["output"] = {key: output.get(key) for key in ("mp4", "wav", "width", "height", "fps")}
        if dropped:
            # The service is text-to-video: reference frames are not sent.
            meta["dropped_inputs"] = dropped
        return VideoResult(
            content=content,
            mime="video/mp4",
            duration_seconds=duration,
            provider=self.name,
            model_id=request.model_id or self.model_id,
            task_ref=job_id,
            cost_usd=self._cost(units=duration),
            meta=meta,
        )

    async def cancel(self, task_ref: str) -> bool:
        base_url = str(self.options.get("base_url") or "").rstrip("/")
        if not base_url:
            return False
        async with httpx.AsyncClient(base_url=base_url, timeout=60) as client:
            response = await client.post(f"{self.cancel_path}/{task_ref}/cancel", headers=self._headers())
            return response.status_code < 400
