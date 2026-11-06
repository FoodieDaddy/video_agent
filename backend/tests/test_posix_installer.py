"""POSIX 安装器文件所有权、生命周期和跨平台入口合约。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from installer import posix

pytestmark = pytest.mark.skipif(posix.os.name == "nt", reason="POSIX 生命周期锁需要 flock")


@pytest.fixture()
def payload(tmp_path):
    source = tmp_path / "payload"
    files = {
        "pyproject.toml": '[project]\nname="ai-film-studio"\nversion="1.0.0"\n[tool.uv.workspace]\nmembers=["apps/*"]\n',
        "uv.lock": "version=1\n",
        "apps/studio_api/pyproject.toml": '[project]\nname="studio-api"\n',
        "apps/studio_api/src/studio_api/__init__.py": "",
        "apps/studio_api/src/studio_api/main.py": "",
        "config/app.yaml": "app: {}\n",
        "web/index.html": "<html></html>",
        "samples/novel_sample.txt": "sample",
        "scripts/sync_studio_resources.py": "",
    }
    for name, text in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return source


@pytest.fixture()
def installation(tmp_path, payload, monkeypatch):
    root = tmp_path / "Studio with 'quotes'"
    shortcuts = tmp_path / "shortcuts"
    calls = []
    monkeypatch.setattr(posix, "current_platform", lambda explicit="": explicit or "macos")
    monkeypatch.setattr(posix, "find_python", lambda explicit="": "/test/python")
    monkeypatch.setattr(posix, "_check_ffmpeg", lambda: None)

    def run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["-m", "venv"]:
            python = Path(command[-1]) / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.touch()
        elif command[1:4] == ["-m", "studio_api.launcher", "stop"]:
            (root / "run" / "instance.json").unlink(missing_ok=True)

    def sync(python, source, extras, *, dry_run):
        assert python == root / "venv/bin/python"
        assert (source / "uv.lock").is_file()
        assert dry_run is False

    monkeypatch.setattr(posix.common, "run", run)
    monkeypatch.setattr(posix.workspace_engine, "install_workspace", sync)
    monkeypatch.setattr(posix.workspace_engine, "verify_packages", lambda python: None)
    args = posix.parse_args(
        ["install", "--dir", str(root), "--from", str(payload), "--shortcut-dir", str(shortcuts)]
    )
    return root, shortcuts, calls, args


def test_install_stop_uninstall_retains_data_and_config_then_explicitly_purges(installation):
    root, shortcuts, calls, args = installation
    manifest = posix.install(args)
    assert manifest["owner"] == posix.OWNER
    assert manifest["status"] == "installed"
    assert (root / "config/.env").is_file()
    assert (root / "installer/posix.py").is_file()
    for name in ("start-studio.sh", "Stop AI Film Studio.command", "uninstall-studio.sh"):
        path = root / name
        assert path.stat().st_mode & 0o111
        assert subprocess.run(["sh", "-n", str(path)]).returncode == 0
    assert "studio_api.launcher start" in (root / "start-studio.sh").read_text()
    (root / "data/sentinel").write_text("user-data")
    (root / "unknown.txt").write_text("unmanaged")
    (root / "run/instance.json").write_text('{"pid":1}')

    uninstall = posix.parse_args(["uninstall", "--dir", str(root)])
    posix.uninstall(uninstall)

    assert calls[-1][1:4] == ["-m", "studio_api.launcher", "stop"]
    assert (root / "data/sentinel").read_text() == "user-data"
    assert (root / "config/.env").is_file()
    assert not (root / "app").exists()
    assert not (root / "venv").exists()
    assert not list(shortcuts.iterdir())
    posix.uninstall(uninstall)  # 已卸载且保留数据的操作可重复执行。
    posix.uninstall(posix.parse_args(["uninstall", "--dir", str(root), "--purge"]))
    assert not (root / "data").exists()
    assert not (root / "config").exists()
    assert (root / "unknown.txt").read_text() == "unmanaged"


def test_install_dry_run_has_no_filesystem_side_effects(installation):
    root, shortcuts, calls, args = installation
    args.dry_run = True
    posix.install(args)
    assert not root.exists()
    assert not shortcuts.exists()
    assert calls == []


def test_reinstall_preserves_config_and_reuses_only_owned_shortcut(installation):
    root, shortcuts, calls, args = installation
    posix.install(args)
    (root / "config/.env").write_text("USER_CHOICE=keep\n")
    posix.install(args)
    assert (root / "config/.env").read_text() == "USER_CHOICE=keep\n"
    assert len(posix.read_installation(root)["shortcuts"]) == 1


def test_uninstall_refuses_to_delete_runtime_when_stop_fails(installation, monkeypatch):
    root, shortcuts, calls, args = installation
    posix.install(args)

    def failed_stop(*args, **kwargs):
        raise posix.common.InstallerError("unverified process")

    monkeypatch.setattr(posix.common, "run", failed_stop)
    with pytest.raises(posix.common.InstallerError, match="unverified"):
        posix.uninstall(posix.parse_args(["uninstall", "--dir", str(root), "--purge"]))
    assert (root / "venv/bin/python").is_file()
    assert (root / "config/.env").is_file()


@pytest.mark.parametrize("invalid", ["foreign-directory", "wrong-root", "symlink-data", "foreign-shortcut"])
def test_destructive_operations_reject_unowned_or_escaped_targets(installation, tmp_path, invalid):
    root, shortcuts, calls, args = installation
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "important.txt"
    sentinel.write_text("keep")
    if invalid == "foreign-directory":
        root.mkdir()
        (root / "user-file").write_text("keep")
    else:
        posix.install(args)
        manifest = posix.read_installation(root)
        if invalid == "wrong-root":
            manifest["data_dir"] = str(outside)
        elif invalid == "symlink-data":
            (root / "data").rmdir()
            (root / "data").symlink_to(outside, target_is_directory=True)
        else:
            manifest["shortcuts"] = [{"path": str(sentinel), "sha256": "forged"}]
        posix.common.write_manifest(root, manifest)
    with pytest.raises(posix.common.InstallerError):
        posix.uninstall(posix.parse_args(["uninstall", "--dir", str(root), "--purge"]))
    assert sentinel.read_text() == "keep"
    if invalid != "foreign-directory":
        assert (root / "app").is_dir()


def test_payload_symlink_cannot_copy_external_private_file(installation, payload, tmp_path):
    root, shortcuts, calls, args = installation
    secret = tmp_path / "private-file"
    secret.write_text("private fixture")
    (payload / "web/innocent.txt").symlink_to(secret)
    with pytest.raises(posix.common.InstallerError, match="符号链接"):
        posix.install(args)
    assert not root.exists()
    assert secret.read_text() == "private fixture"


def test_install_never_overwrites_unknown_shortcut(installation):
    root, shortcuts, calls, args = installation
    shortcuts.mkdir()
    user_file = shortcuts / "AI Film Studio.command"
    user_file.write_text("user-owned")
    with pytest.raises(posix.common.InstallerError, match="未被本安装记录持有"):
        posix.install(args)
    assert user_file.read_text() == "user-owned"


def test_install_record_with_live_instance_refuses_upgrade(installation):
    root, shortcuts, calls, args = installation
    posix.install(args)
    (root / "run/instance.json").write_text('{"pid":1}')
    with pytest.raises(posix.common.InstallerError, match="先.*停止"):
        posix.install(args)


def test_linux_desktop_shortcut_escapes_percent_and_preserves_modified_user_copy(installation):
    root, shortcuts, calls, args = installation
    args.platform = "linux"
    posix.install(args)
    desktop = shortcuts / "ai-film-studio.desktop"
    assert "Type=Application" in desktop.read_text()
    desktop.write_text("modified by owner")
    posix.uninstall(posix.parse_args(["uninstall", "--dir", str(root)]))
    assert desktop.read_text() == "modified by owner"


def test_unknown_extra_fails_before_creating_installation(installation):
    root, shortcuts, calls, args = installation
    args.extras = "does-not-exist"
    with pytest.raises(posix.common.InstallerError, match="Unknown extra"):
        posix.install(args)
    assert not root.exists()


def test_management_lock_prevents_install_or_uninstall_from_touching_runtime(installation):
    root, shortcuts, calls, args = installation
    posix.install(args)
    with posix.operation_lock(root):
        with pytest.raises(posix.common.InstallerError, match="操作正在进行"):
            posix.install(args)
        with pytest.raises(posix.common.InstallerError, match="操作正在进行"):
            posix.uninstall(posix.parse_args(["uninstall", "--dir", str(root)]))
    assert (root / "app").is_dir()
    assert posix.read_installation(root)["status"] == "installed"


def test_installing_and_uninstalling_states_reject_launcher_before_mutations(installation, monkeypatch):
    from studio_api import launcher

    root, shortcuts, calls, args = installation
    observed = []

    def during_install(*args, **kwargs):
        observed.append(posix.read_installation(root)["status"])
        with pytest.raises(launcher.LaunchError, match="安装尚未完成"):
            launcher.layout(root, require_installed=True)

    monkeypatch.setattr(posix.workspace_engine, "install_workspace", during_install)
    posix.install(args)
    remove_shortcuts = posix._remove_shortcuts

    def during_uninstall(manifest, **kwargs):
        observed.append(posix.read_installation(root)["status"])
        assert (root / "venv").is_dir()
        with pytest.raises(launcher.LaunchError, match="安装尚未完成"):
            launcher.layout(root, require_installed=True)
        remove_shortcuts(manifest, **kwargs)

    monkeypatch.setattr(posix, "_remove_shortcuts", during_uninstall)
    posix.uninstall(posix.parse_args(["uninstall", "--dir", str(root)]))
    assert observed == ["installing", "uninstalling"]
    assert (root / "run/start.lock").is_file()
    assert posix.read_installation(root)["status"] == "uninstalled"
