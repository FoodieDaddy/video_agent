"""发布验收工具的归档完整性与拒绝误停保护；不启动应用服务。"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import socket
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def checker():
    spec = importlib.util.spec_from_file_location(
        "posix_release_smoke_regression", ROOT / "scripts/checks/posix_release_smoke.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_archive(tmp_path, checker, *, tamper=False, extra=False, target=None):
    files = {
        "install.sh": b"#!/bin/sh\nexit 0\n",
        "uninstall.sh": b"#!/bin/sh\nexit 0\n",
        "installer/posix.py": b"# test installer fixture\n",
        "payload/uv.lock": b"locked fixture\n",
    }
    manifest = {
        "schema_version": 1,
        "name": "ai-film-studio",
        "version": "1.0.0",
        "platform": target or ("macos" if sys.platform == "darwin" else "linux"),
        "artifact_kind": "source-bootstrap",
        "workspace_member_count": 13,
        "workspace_members": [{"name": name} for name in sorted(checker.EXPECTED_MEMBERS)],
        "uv_lock_sha256": hashlib.sha256(files["payload/uv.lock"]).hexdigest(),
        "content_sha256": {name: hashlib.sha256(body).hexdigest() for name, body in files.items()},
    }
    files["release.json"] = json.dumps(manifest).encode()
    if tamper:
        files["payload/uv.lock"] += b"changed"
    if extra:
        files["unexpected.py"] = b"# not covered by manifest\n"
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        for name, body in files.items():
            info = tarfile.TarInfo("studio-release/" + name)
            info.size = len(body)
            info.mode = 0o755 if name.endswith(".sh") else 0o644
            package.addfile(info, io.BytesIO(body))
    return archive


@pytest.mark.skipif(os.name != "posix", reason="仅 POSIX 发布格式验收")
def test_valid_release_extracts_with_complete_hash_coverage(tmp_path, checker):
    archive = make_archive(tmp_path, checker)
    release, manifest = checker.unpack_and_verify(archive, tmp_path / "unpacked")
    assert manifest["workspace_member_count"] == 13
    assert (release / "install.sh").read_bytes().startswith(b"#!/bin/sh")
    assert os.access(release / "install.sh", os.X_OK)


@pytest.mark.skipif(os.name != "posix", reason="仅 POSIX 发布格式验收")
@pytest.mark.parametrize("option,error", [("tamper", "哈希不符"), ("extra", "集合与哈希清单不一致")])
def test_changed_or_uncovered_content_is_rejected(tmp_path, checker, option, error):
    archive = make_archive(tmp_path, checker, **{option: True})
    with pytest.raises(checker.CheckFailure, match=error):
        checker.unpack_and_verify(archive, tmp_path / "unpacked")


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escaped.txt", "file"),
        ("/escaped.txt", "file"),
        ("release/a/../../escaped.txt", "file"),
        ("release/symlink", "symlink"),
        ("release/hardlink", "hardlink"),
        ("release/directory", "directory"),
    ],
)
def test_non_regular_or_escaping_tar_entries_never_extract(tmp_path, checker, name, kind):
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        info = tarfile.TarInfo(name)
        if kind == "symlink":
            info.type, info.linkname = tarfile.SYMTYPE, "../../outside"
        elif kind == "hardlink":
            info.type, info.linkname = tarfile.LNKTYPE, "../../outside"
        elif kind == "directory":
            info.type = tarfile.DIRTYPE
        package.addfile(info, io.BytesIO(b""))
    destination = tmp_path / "unpacked"
    with pytest.raises(checker.CheckFailure):
        checker.unpack_and_verify(archive, destination)
    assert not destination.exists()
    assert not (tmp_path / "escaped.txt").exists()


def test_duplicate_tar_names_are_rejected_before_extraction(tmp_path, checker):
    archive = tmp_path / "duplicate.tar.gz"
    with tarfile.open(archive, "w:gz") as package:
        for _ in range(2):
            package.addfile(tarfile.TarInfo("release/file"), io.BytesIO())
    destination = tmp_path / "unpacked"
    with pytest.raises(checker.CheckFailure, match="重复文件"):
        checker.unpack_and_verify(archive, destination)
    assert not destination.exists()


@pytest.mark.skipif(os.name != "posix", reason="socket 复用约定仅在 POSIX 验证")
def test_busy_port_refuses_before_unpack_or_install(tmp_path, checker, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("端口已有服务时不能创建测试安装或运行停止命令")

    monkeypatch.setattr(checker.tempfile, "TemporaryDirectory", forbidden)
    monkeypatch.setattr(checker, "run_command", forbidden)
    report = tmp_path / "report.json"
    with socket.socket() as existing:
        existing.bind(("127.0.0.1", 0))
        existing.listen(1)
        assert checker.run(tmp_path / "missing.tar.gz", existing.getsockname()[1], report) == 1
    result = json.loads(report.read_text())
    assert result["result"] == "blocked"
    assert "已被占用" in result["error"]
    assert result["test_process_removed"] is True


def test_temporary_environment_does_not_inherit_model_credentials(tmp_path, checker, monkeypatch):
    monkeypatch.setenv("FAST_GATEWAY_API_KEY", "parent-fake-secret-only")
    monkeypatch.setenv("OTHER_ACCESS_TOKEN", "another-fake-secret-only")
    monkeypatch.setenv("APP_CONFIG_DIR", "/formal/config")
    monkeypatch.setenv("PYTHONPATH", "/formal/python")
    before = dict(os.environ)
    env = checker.isolated_environment(tmp_path)
    assert env["FAST_GATEWAY_API_KEY"] == ""
    assert "OTHER_ACCESS_TOKEN" not in env
    assert "APP_CONFIG_DIR" not in env
    assert "PYTHONPATH" not in env
    assert env["AGENT_MODEL_PROVIDER"] == "mock"
    assert Path(env["APP_ENV_FILE"]).is_file()
    assert Path(env["STUDIO_INSTANCE_LOCK_FILE"]).is_relative_to(tmp_path)
    assert dict(os.environ) == before
    tail = checker.redacted_tail(
        "parent-fake-secret-only https://name:password@example.invalid/path Bearer fake-bearer", tmp_path
    )
    assert "parent-fake-secret-only" not in tail
    assert "password" not in tail
    assert "fake-bearer" not in tail
