"""前端依赖缓存一致性：只使用临时静态目录，不启动数据库或模型。"""

from __future__ import annotations

import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.console import ConsoleStaticFiles


@pytest.fixture()
def console(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text(
        '<html><head><link href="/styles.css"></head><body><script type="module" src="/app.js"></script></body></html>'
    )
    (web / "app.js").write_text('import { value } from "./helper.js"; document.title=value;')
    (web / "helper.js").write_text('export const value="first";')
    (web / "styles.css").write_text("body { color: #222; }")
    (web / "image.png").write_bytes(b"image-fixture")
    app = FastAPI()
    app.mount("/", ConsoleStaticFiles(web))
    with TestClient(app) as client:
        yield client, web


def import_map(response):
    return json.loads(re.search(r'<script type="importmap">(.*?)</script>', response.text).group(1))[
        "imports"
    ]


def test_entry_and_relative_dependencies_share_content_revision(console):
    client, _ = console
    response = client.get("/")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    imports = import_map(response)
    assert set(imports) == {"/app.js", "/helper.js"}
    assert f'src="{imports["/app.js"]}"' in response.text
    assert imports["/app.js"].split("?v=")[1] == imports["/helper.js"].split("?v=")[1]
    assert response.text.index('type="importmap"') < response.text.index('type="module"')
    assert client.get(imports["/helper.js"]).text == 'export const value="first";'


def test_dependency_only_change_invalidates_html_even_with_old_conditional_headers(console):
    client, web = console
    first = client.get("/")
    (web / "helper.js").write_text('export const value="second";')
    second = client.get("/", headers={"If-Modified-Since": "Wed, 01 Jan 2100 00:00:00 GMT"})
    assert second.status_code == 200
    assert import_map(first)["/helper.js"] != import_map(second)["/helper.js"]
    assert client.get(import_map(second)["/helper.js"]).text.endswith('"second";')


def test_scripts_revalidate_and_media_keep_normal_static_behavior(console):
    client, _ = console
    assert client.get("/app.js").headers["cache-control"] == "no-cache, must-revalidate"
    assert client.get("/styles.css").headers["cache-control"] == "no-cache, must-revalidate"
    image = client.get("/image.png")
    assert image.content == b"image-fixture" and "etag" in image.headers
    assert client.head("/").content == b""
    assert client.post("/").status_code == 405
    assert client.get("/%2e%2e/secret.txt").status_code == 404
