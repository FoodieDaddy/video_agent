"""原生前端的资源一致性：HTML与ES模块始终使用同一内容修订号。

浏览器曾将新app.js和旧script-editor.js混用，导致缺少导出而无法启动。
这里不引入构建器：HTML注入原生import map，入口和依赖均带内容版本；
JS/CSS要求重验证，图片和字体仍由StaticFiles正常缓存。不是原子发布系统。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class ConsoleStaticFiles(StaticFiles):
    """给主控制台提供版本化HTML，保留StaticFiles的路径与请求方法校验。"""

    def __init__(self, directory: str | Path) -> None:
        super().__init__(directory=str(directory), html=True)
        self.web_root = Path(directory).resolve()

    def render_index(self) -> str:
        """按实际文件内容计算版本；依赖单独变化时也让HTML入口使用新修订号。"""
        index = self.web_root / "index.html"
        assets = sorted([*self.web_root.glob("*.js"), *self.web_root.glob("*.css")])
        digest = hashlib.sha256(index.read_bytes())
        for asset in assets:
            digest.update(asset.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(asset.read_bytes())
        revision = digest.hexdigest()[:20]
        urls = {f"/{quote(asset.name)}": f"/{quote(asset.name)}?v={revision}" for asset in assets}
        source = index.read_text(encoding="utf-8")
        for original, versioned in urls.items():
            for attribute in ("src", "href"):
                for delimiter in ('"', "'"):
                    source = source.replace(
                        f"{attribute}={delimiter}{original}{delimiter}",
                        f"{attribute}={delimiter}{versioned}{delimiter}",
                    )
        imports = {original: target for original, target in urls.items() if original.endswith(".js")}
        data = json.dumps({"imports": imports}, ensure_ascii=True, separators=(",", ":")).replace(
            "<", "\\u003c"
        )
        # import map必须位于任何module脚本之前；相对模块会由浏览器规范化后匹配绝对键。
        return source.replace("<head>", f'<head>\n<script type="importmap">{data}</script>', 1)

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if path in {".", "", "index.html"} and response.status_code in {200, 304}:
            # index文件未变但依赖变了时，也不能沿用StaticFiles的旧HTML 304。
            content = await run_in_threadpool(self.render_index)
            rendered = HTMLResponse(content, headers={"Cache-Control": "no-store"})
            if scope["method"] == "HEAD":
                rendered.body = b""
            return rendered
        if path.endswith((".js", ".css", ".html")):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response
