"""受管启动器的文件、进程归属与数据隔离合约，不启动网页服务。"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from studio_api import launcher


def installed_root(tmp_path: Path) -> Path:
    root = tmp_path / "安装目录 with spaces"
    for name in ("app", "venv", "data", "config", "run"):
        (root / name).mkdir(parents=True)
    (root / "config/.env").write_text("", encoding="utf-8")
    (root / "install.json").write_text(
        json.dumps(
            {
                "owner": "ai-film-studio-posix-v1",
                "schema_version": 1,
                "status": "installed",
                "install_root": str(root),
                "port": 8010,
            }
        )
    )
    return root


def test_missing_instance_env_cannot_fall_back_to_repository_config(tmp_path):
    root = installed_root(tmp_path)
    (root / "config/.env").unlink()
    with pytest.raises(launcher.LaunchError, match="config/.env"):
        launcher.layout(root)


def test_layout_rejects_foreign_directory_and_symlinked_data(tmp_path):
    root = installed_root(tmp_path)
    original = json.loads((root / "install.json").read_text())
    (root / "install.json").write_text(json.dumps({**original, "owner": "another-program"}))
    with pytest.raises(launcher.LaunchError, match="不属于"):
        launcher.layout(root)
    (root / "install.json").write_text(json.dumps(original))
    (root / "data").rmdir()
    (root / "data").symlink_to(tmp_path)
    with pytest.raises(launcher.LaunchError, match="符号链接"):
        launcher.layout(root)


def test_ownership_requires_birth_time_root_and_run_marker(tmp_path, monkeypatch):
    root = installed_root(tmp_path)
    token = "a" * 32
    state = {"pid": 123, "install_root": str(root), "instance_id": token, "process_start": "birth"}
    command = f"python -m studio_api.launcher serve --install-root {root} --instance-id {token}"
    monkeypatch.setattr(launcher, "process_identity", lambda pid: ("birth", command))
    assert launcher.owned_process(root, state)
    assert not launcher.owned_process(root, {**state, "process_start": "old-birth"})
    assert not launcher.owned_process(root, {**state, "install_root": str(tmp_path)})
    monkeypatch.setattr(launcher, "process_identity", lambda pid: ("birth", "python unrelated-program"))
    assert not launcher.owned_process(root, state)


def test_stale_pid_file_never_signals_an_unrelated_live_process(tmp_path, monkeypatch):
    root = installed_root(tmp_path)
    state = {
        "pid": os.getpid(),
        "install_root": str(root),
        "instance_id": "b" * 32,
        "process_start": launcher.process_identity(os.getpid())[0],
    }
    (root / "run/instance.json").write_text(json.dumps(state))
    calls = []
    monkeypatch.setattr(launcher.os, "kill", lambda *args: calls.append(args))
    assert launcher.stop(root)["already_stopped"]
    assert calls == []
    assert not (root / "run/instance.json").exists()


def test_instance_lock_is_exclusive_and_released(tmp_path):
    path = tmp_path / "run.lock"
    with launcher.exclusive_lock(path):
        with pytest.raises(launcher.LaunchError, match="运行锁"):
            with launcher.exclusive_lock(path):
                pytest.fail("不能取得同一锁")
    with launcher.exclusive_lock(path):
        pass


def test_runtime_paths_override_inherited_formal_paths(tmp_path, monkeypatch):
    root = installed_root(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///formal-do-not-use.db")
    monkeypatch.setenv("STORAGE_ROOT", "/formal-do-not-use")
    monkeypatch.setenv("APP_ENV_FILE", "/formal/.env")
    monkeypatch.setenv("PYTHONPATH", "/formal/backend")
    env = launcher.runtime_environment(root, {"env": "test"})
    assert env["APP_ENV_FILE"] == str(root / "config/.env")
    assert env["STORAGE_ROOT"] == str(root / "data/storage")
    assert env["DATABASE_URL"] == f"sqlite:///{(root / 'data/studio.db').as_posix()}"
    assert env["STUDIO_RESOURCE_ROOT"] == str(root / "app")
    assert "PYTHONPATH" not in env


@pytest.mark.skipif(os.name != "posix", reason="POSIX ps 的 UTF-8 参数显示")
def test_real_process_identity_preserves_unicode_install_paths(tmp_path):
    marker = str(tmp_path / "测试安装 带空格")
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)", marker])
    try:
        identity = launcher.process_identity(process.pid)
        assert identity is not None
        assert marker in identity[1]
    finally:
        process.terminate()
        process.wait(timeout=5)
