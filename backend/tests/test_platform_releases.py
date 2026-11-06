"""分平台归档的来源、路径安全、启动参数与清单完整性。"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import build_releases as releases


@pytest.fixture()
def release_source(tmp_path: Path) -> Path:
    root = tmp_path / "source with spaces"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        '[project]\nname="ai-film-studio"\nversion="1.0.0"\n'
        '[tool.uv.workspace]\nmembers=["apps/studio_api", "packages/*"]\n'
    )
    (root / "uv.lock").write_text("version = 1\n")
    for name in sorted(releases.REQUIRED_MEMBERS):
        module = name.replace("-", "_")
        member = root / ("apps" if name == "studio-api" else "packages") / module
        (member / "src" / module).mkdir(parents=True)
        (member / "pyproject.toml").write_text(f'[project]\nname="{name}"\n')
        (member / "src" / module / "__init__.py").write_text("")
    files = {
        "apps/studio_api/src/studio_api/main.py": "",
        "config/app.yaml": "app: {}\n",
        "config/prompts/script/system.md": "prompt fixture\n",
        "web/index.html": "committed frontend\n",
        "web/assets/cover.png": "image fixture",
        "samples/novel_sample.txt": "sample fixture",
        "scripts/sync_studio_resources.py": "# payload fixture\n",
        "scripts/build_installers.py": "# Windows native build fixture\n",
        "scripts/build_releases.py": "# platform release build fixture\n",
        "installer/common.py": "# source fixture\n",
        "installer/workspace.py": "# source fixture\n",
        "installer/install.py": "# source fixture\n",
        "installer/uninstall.py": "# source fixture\n",
        "installer/posix.py": (
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['RELEASE_TEST_ARGV']).write_text(json.dumps(sys.argv[1:]))\n"
        ),
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def unpack_tar(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        assert names == sorted(names)
        assert not any(name.startswith("/") or ".." in Path(name).parts for name in names)
        tar.extractall(destination, filter="data")
    return destination / names[0].split("/")[0]


def test_platform_archives_exclude_secrets_have_complete_hashes_and_reproduce(release_source, tmp_path):
    (release_source / ".env").write_text("private fixture")
    (release_source / "config/.env.local").write_text("private fixture")
    (release_source / "private-notes.txt").write_text("private fixture")
    (release_source / "data").mkdir()
    (release_source / "data/studio.db").write_text("private fixture")
    results = releases.build_releases(
        source_root=release_source,
        output_dir=tmp_path / "out",
        platform_name="all",
        source_only=True,
    )
    assert [item["platform"] for item in results] == ["macos", "linux", "windows"]
    for result in results:
        archive = Path(result["path"])
        extraction = tmp_path / f"unpacked-{result['platform']}"
        if result["platform"] == "windows":
            with zipfile.ZipFile(archive) as zipped:
                assert zipped.namelist() == sorted(zipped.namelist())
                zipped.extractall(extraction)
            directory = next(extraction.iterdir())
        else:
            directory = unpack_tar(archive, extraction)
        manifest = json.loads((directory / "release.json").read_text())
        assert manifest["platform"] == result["platform"]
        assert manifest["artifact_kind"] == "source-bootstrap"
        assert manifest["workspace_member_count"] == 13
        assert manifest["uv_lock_sha256"] == hashlib.sha256(b"version = 1\n").hexdigest()
        assert not list(directory.rglob(".env*"))
        assert not (directory / "payload/private-notes.txt").exists()
        assert not (directory / "payload/data").exists()
        actual_files = {
            path.relative_to(directory).as_posix()
            for path in directory.rglob("*")
            if path.is_file() and path.name != "release.json"
        }
        assert set(manifest["content_sha256"]) == actual_files
        for name, expected in manifest["content_sha256"].items():
            assert releases.sha256(directory / name) == expected
        assert (
            directory / "payload/apps/studio_api/src/studio_api/resources/config/prompts/script/system.md"
        ).read_text() == "prompt fixture\n"
    repeated = releases.build_releases(
        source_root=release_source,
        output_dir=tmp_path / "repeat",
        platform_name="all",
        source_only=True,
    )
    assert [item["sha256"] for item in results] == [item["sha256"] for item in repeated]
    assert not (release_source / "apps/studio_api/src/studio_api/resources").exists()


@pytest.mark.parametrize("platform_name", ["macos", "linux"])
def test_posix_wrappers_execute_from_space_path_and_preserve_argument_boundaries(
    release_source,
    tmp_path,
    platform_name,
):
    result = releases.build_releases(
        source_root=release_source,
        output_dir=tmp_path / "out",
        platform_name=platform_name,
    )[0]
    directory = unpack_tar(Path(result["path"]), tmp_path / "extract with spaces")
    entry = directory / ("Install.command" if platform_name == "macos" else "install.sh")
    for script in directory.glob("*.sh"):
        subprocess.run(["sh", "-n", str(script)], check=True)
    assert entry.stat().st_mode & 0o111
    argv_file = tmp_path / "captured.json"
    env = os.environ.copy()
    env.update(STUDIO_PYTHON=sys.executable, RELEASE_TEST_ARGV=str(argv_file))
    subprocess.run(
        [str(entry), "--dir", str(tmp_path / "install with spaces"), "--extras", "s3,pdf"],
        env=env,
        check=True,
    )
    assert json.loads(argv_file.read_text()) == [
        "install",
        "--platform",
        platform_name,
        "--from",
        str(directory / "payload"),
        "--dir",
        str(tmp_path / "install with spaces"),
        "--extras",
        "s3,pdf",
    ]


def test_default_git_source_uses_committed_frontend_not_dirty_worktree(release_source, tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(release_source)], check=True)
    subprocess.run(["git", "add", "."], cwd=release_source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=release_source,
        check=True,
    )
    (release_source / "web/index.html").write_text("dirty frontend must not ship")
    (release_source / "config/local-secret.txt").write_text("untracked must not ship")
    monkeypatch.setattr(releases, "REPO_ROOT", release_source)
    result = releases.build_releases(output_dir=tmp_path / "out", platform_name="macos")[0]
    directory = unpack_tar(Path(result["path"]), tmp_path / "extracted")
    assert (directory / "payload/web/index.html").read_text() == "committed frontend\n"
    assert not (directory / "payload/config/local-secret.txt").exists()
    manifest = json.loads((directory / "release.json").read_text())
    assert manifest["source"]["kind"] == "git-archive"
    assert len(manifest["source"]["commit"]) == 40


def test_release_rejects_links_before_reading_external_content(release_source, tmp_path):
    private = tmp_path / "private.txt"
    private.write_text("must not copy")
    (release_source / "config/linked.txt").symlink_to(private)
    with pytest.raises(releases.common.InstallerError, match="链接"):
        releases.build_releases(
            source_root=release_source, output_dir=tmp_path / "out", platform_name="macos"
        )
    assert not list((tmp_path / "out").glob("*"))


def write_pe_fixture(path: Path, machine: int = 0x8664) -> None:
    """仅用于头部解析测试，不是可运行 Windows 程序。"""
    content = bytearray(256)
    content[:2] = b"MZ"
    struct.pack_into("<I", content, 0x3C, 128)
    content[128:132] = b"PE\0\0"
    struct.pack_into("<H", content, 132, machine)
    path.write_bytes(content)


def fixture_payload_source(source: Path) -> dict:
    explicit = None if (source / ".git").exists() else source
    with tempfile.TemporaryDirectory(prefix="release-payload-fixture-") as temp:
        payload = Path(temp) / "payload"
        with releases.source_snapshot(explicit, git_root=source) as (snapshot, provenance):
            releases.stage_payload(snapshot, payload)
            return releases.payload_source_manifest(payload, provenance)


def write_windows_fixture_manifest(source: Path, exes: Path) -> Path:
    return releases.write_windows_installers_manifest(
        source, exes, payload_source=fixture_payload_source(source)
    )


def test_windows_requires_supplied_native_files_unless_source_only(release_source, tmp_path):
    with pytest.raises(releases.common.InstallerError, match="windows-exe-dir"):
        releases.build_releases(source_root=release_source, output_dir=tmp_path / "out", platform_name="all")
    assert not (tmp_path / "out").exists()
    exes = tmp_path / "native-artifacts"
    exes.mkdir()
    (exes / "install.exe").write_bytes(b"MZ")
    write_pe_fixture(exes / "uninstall.exe")
    with pytest.raises(releases.common.InstallerError, match="无效"):
        releases.build_releases(
            source_root=release_source,
            output_dir=tmp_path / "out",
            platform_name="windows",
            windows_exe_dir=exes,
        )
    write_pe_fixture(exes / "install.exe", 0xAA64)
    with pytest.raises(releases.common.InstallerError, match="架构不一致"):
        releases.build_releases(
            source_root=release_source,
            output_dir=tmp_path / "out",
            platform_name="windows",
            windows_exe_dir=exes,
        )
    write_pe_fixture(exes / "install.exe")
    with pytest.raises(releases.common.InstallerError, match="windows-installers.json"):
        releases.build_releases(
            source_root=release_source,
            output_dir=tmp_path / "out",
            platform_name="windows",
            windows_exe_dir=exes,
        )
    write_windows_fixture_manifest(release_source, exes)
    result = releases.build_releases(
        source_root=release_source, output_dir=tmp_path / "out", platform_name="windows", windows_exe_dir=exes
    )[0]
    with zipfile.ZipFile(result["path"]) as archive:
        manifest_name = next(name for name in archive.namelist() if name.endswith("/release.json"))
        manifest = json.loads(archive.read(manifest_name))
        assert manifest["artifact_kind"] == "native-bootstrap"
        assert manifest["architecture"] == "x86_64"
        assert manifest["native_executables_executed"] is False
        assert manifest["native_installer_manifest"] == "windows-installers.json"
        sidecar = json.loads(archive.read(manifest_name.replace("release.json", "windows-installers.json")))
        assert sidecar["executables"]["install.exe"]["sha256"] == releases.sha256(exes / "install.exe")
        command = archive.read(manifest_name.replace("release.json", "install.cmd")).decode()
        assert '"%~dp0install.exe" --from "%~dp0payload" %*' in command


@pytest.mark.parametrize("changed", ["installer", "lock", "version", "exe", "schema", "frontend"])
def test_windows_release_rejects_source_or_artifact_mismatch(release_source, tmp_path, changed):
    exes = tmp_path / "native-artifacts"
    exes.mkdir()
    for action in ("install", "uninstall"):
        write_pe_fixture(exes / f"{action}.exe")
    sidecar = write_windows_fixture_manifest(release_source, exes)
    if changed == "installer":
        (release_source / "installer/install.py").write_text("changed installer implementation")
    elif changed == "lock":
        (release_source / "uv.lock").write_text("version = 2\n")
    elif changed == "version":
        project = release_source / "pyproject.toml"
        project.write_text(project.read_text().replace('version="1.0.0"', 'version="2.0.0"'))
    elif changed == "exe":
        exe = exes / "install.exe"
        data = bytearray(exe.read_bytes())
        data[200] = 1  # PE 头和架构仍有效，但执行文件内容已经变化。
        exe.write_bytes(data)
    elif changed == "frontend":
        (release_source / "web/index.html").write_text("different embedded frontend")
    else:
        data = json.loads(sidecar.read_text())
        data["schema_version"] = 2
        sidecar.write_text(json.dumps(data))
    with pytest.raises(releases.common.InstallerError, match="来源不一致|哈希|版本不受支持|内嵌载荷"):
        releases.build_releases(
            source_root=release_source,
            output_dir=tmp_path / "out",
            platform_name="windows",
            windows_exe_dir=exes,
        )
    assert not (tmp_path / "out").exists()


def test_git_windows_release_requires_exact_source_commit(release_source, tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(release_source)], check=True)
    subprocess.run(["git", "add", "."], cwd=release_source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=release_source,
        check=True,
    )
    exes = tmp_path / "native-artifacts"
    exes.mkdir()
    for action in ("install", "uninstall"):
        write_pe_fixture(exes / f"{action}.exe")
    sidecar = write_windows_fixture_manifest(release_source, exes)
    monkeypatch.setattr(releases, "REPO_ROOT", release_source)
    assert releases.build_releases(
        output_dir=tmp_path / "valid", platform_name="windows", windows_exe_dir=exes
    )
    data = json.loads(sidecar.read_text())
    data["source_commit"] = "0" * 40
    sidecar.write_text(json.dumps(data))
    with pytest.raises(releases.common.InstallerError, match="来源提交"):
        releases.build_releases(
            output_dir=tmp_path / "invalid", platform_name="windows", windows_exe_dir=exes
        )
    assert not (tmp_path / "invalid").exists()


def test_windows_manifest_rejects_source_mutation_during_build(release_source, tmp_path):
    before = releases.windows_source_fingerprint(release_source)
    exes = tmp_path / "native-artifacts"
    exes.mkdir()
    for action in ("install", "uninstall"):
        write_pe_fixture(exes / f"{action}.exe")
    (release_source / "installer/common.py").write_text("changed while compiling")
    with pytest.raises(releases.common.InstallerError, match="构建期间"):
        releases.write_windows_installers_manifest(
            release_source,
            exes,
            payload_source=fixture_payload_source(release_source),
            expected_source=before,
        )
    assert not (exes / "windows-installers.json").exists()


@pytest.mark.parametrize(
    "changed", ["installer/common.py", "uv.lock", "scripts/build_releases.py", "pyproject.toml"]
)
def test_native_windows_compilation_requires_committed_inputs_but_allows_dirty_frontend(
    release_source,
    changed,
):
    subprocess.run(["git", "init", "-q", str(release_source)], check=True)
    subprocess.run(["git", "add", "."], cwd=release_source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=release_source,
        check=True,
    )
    (release_source / "web/index.html").write_text("uncommitted frontend")
    (release_source / "README.md").write_text("untracked or dirty documentation")
    before = releases.committed_windows_source_fingerprint(release_source)
    assert len(before["source_commit"]) == 40
    path = release_source / changed
    path.write_text(path.read_text() + "\n# dirty Windows build input\n")
    with pytest.raises(releases.common.InstallerError, match="HEAD 字节不一致"):
        releases.committed_windows_source_fingerprint(release_source)


def test_windows_embedded_payload_defaults_to_head_and_explicit_source_is_labelled(
    release_source,
    tmp_path,
    monkeypatch,
):
    from scripts import build_installers as native

    subprocess.run(["git", "init", "-q", str(release_source)], check=True)
    subprocess.run(["git", "add", "."], cwd=release_source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=release_source,
        check=True,
    )
    (release_source / "web/index.html").write_text("dirty frontend must stay outside EXE")
    (release_source / "config/private.txt").write_text("untracked configuration")
    monkeypatch.setattr(native, "REPO_ROOT", release_source)
    monkeypatch.setattr(native, "BUILD_DIR", tmp_path / "build")
    monkeypatch.setattr(native, "PAYLOAD_DIR", tmp_path / "build/payload")

    payload = native.stage_payload()

    assert (payload / "web/index.html").read_text() == "committed frontend\n"
    assert not (payload / "config/private.txt").exists()
    assert (
        payload / "apps/studio_api/src/studio_api/resources/web/index.html"
    ).read_text() == "committed frontend\n"
    metadata_path = tmp_path / "build/windows-payload-source.json"
    metadata = json.loads(metadata_path.read_text())
    assert metadata["kind"] == "git-archive"
    assert len(metadata["commit"]) == 40
    assert metadata == releases.payload_source_manifest(payload, metadata)
    assert not (release_source / "apps/studio_api/src/studio_api/resources").exists()

    native.stage_payload(release_source)
    explicit = json.loads(metadata_path.read_text())
    assert explicit["kind"] == "explicit-source-tree"
    assert explicit["commit"] is None
    assert (payload / "web/index.html").read_text() == "dirty frontend must stay outside EXE"


@pytest.mark.parametrize("failure", [None, "selftest", "payload_changed"])
def test_native_build_emits_sidecar_only_after_both_selftests(
    release_source,
    tmp_path,
    monkeypatch,
    failure,
):
    """只模拟 Windows 构建流程顺序，不执行 PE fixture 或下载构建解释器。"""
    from scripts import build_installers as native

    exes = tmp_path / "native-artifacts"
    exes.mkdir()
    for action in ("install", "uninstall"):
        write_pe_fixture(exes / f"{action}.exe")
    sidecar = exes / "windows-installers.json"
    sidecar.write_text("stale previous build")
    monkeypatch.setattr(native, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(native, "REPO_ROOT", release_source)
    monkeypatch.setattr(native, "INSTALLER_DIR", release_source / "installer")
    monkeypatch.setattr(native, "BUILD_DIR", tmp_path / "build")
    monkeypatch.setattr(native, "DIST_DIR", exes)
    monkeypatch.setattr(native, "ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(native, "is_conda_python", lambda: False)
    monkeypatch.setattr(native, "bootstrap_build_python", lambda **kwargs: Path(sys.executable))
    monkeypatch.setattr(native, "paint_icon", lambda path: None)
    monkeypatch.setattr(native, "committed_windows_source_fingerprint", releases.windows_source_fingerprint)
    monkeypatch.setattr(native, "PAYLOAD_DIR", tmp_path / "build" / "payload")
    stage = native.stage_payload
    monkeypatch.setattr(native, "stage_payload", lambda source_root=None: stage(release_source))
    monkeypatch.setattr(native, "run_pyinstaller", lambda name, *args, **kwargs: exes / f"{name}.exe")
    verified = []

    def verify(path):
        assert not sidecar.exists(), "不能在两份 EXE 均通过自检前生成来源清单"
        verified.append(path.name)
        if failure == "selftest" and path.name == "uninstall.exe":
            raise SystemExit("selftest fixture failed")
        if failure == "payload_changed" and path.name == "uninstall.exe":
            (native.PAYLOAD_DIR / "web/index.html").write_text("changed during EXE compilation")

    monkeypatch.setattr(native, "verify", verify)
    if failure:
        expected_error = "selftest fixture failed" if failure == "selftest" else "内嵌载荷发生变化"
        with pytest.raises(SystemExit, match=expected_error):
            native.main([])
        assert not sidecar.exists()
    else:
        assert native.main([]) == 0
        assert json.loads(sidecar.read_text())["schema_version"] == 1
    assert verified == ["install.exe", "uninstall.exe"]


def test_release_rejects_missing_business_member(release_source, tmp_path):
    import shutil

    shutil.rmtree(release_source / "packages/studio_story")
    with pytest.raises(releases.common.InstallerError, match="缺少成员"):
        releases.build_releases(
            source_root=release_source, output_dir=tmp_path / "out", platform_name="linux"
        )
