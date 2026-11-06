"""交付路径合约：完整源码载荷、秘密排除和锁定安装命令；不执行安装。"""

from __future__ import annotations

from pathlib import Path

import pytest
from installer import install

common = install.common


def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    files = {
        "pyproject.toml": '[project]\nname="ai-film-studio"\nversion="1.0.0"\n'
        '[tool.uv.workspace]\nmembers=["apps/*", "packages/*"]\n',
        "uv.lock": "version = 1\n",
        "apps/studio_api/pyproject.toml": '[project]\nname="studio-api"\n',
        "apps/studio_api/src/studio_api/__init__.py": "",
        "apps/studio_api/src/studio_api/main.py": "",
        "packages/studio_story/pyproject.toml": '[project]\nname="studio-story"\n',
        "packages/studio_story/src/studio_story/__init__.py": "",
        "config/app.yaml": "app: {}\n",
        "config/prompts/script/system.md": "system prompt",
        "web/index.html": "<html></html>",
        "web/assets/cover.png": "image fixture",
        "samples/novel_sample.txt": "sample",
        "scripts/sync_studio_resources.py": "",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def test_payload_keeps_every_member_and_resource_but_drops_local_state(tmp_path):
    root = workspace(tmp_path)
    for name in (
        ".env",
        "packages/studio_story/.env",
        "data/studio.db",
        "build/noise.py",
        ".idea/workspace.xml",
        ".vscode/settings.json",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private fixture")
    compatibility = root / "backend"
    compatibility.mkdir()
    try:
        (compatibility / "app").symlink_to(root / "apps/studio_api/src/studio_api", target_is_directory=True)
    except OSError:
        # Windows 未授予符号链接权限时仍验证整个旧目录会被排除。
        (compatibility / "app").mkdir()
    target = tmp_path / "payload"

    common.copy_payload(root, target)

    assert common.payload_root(str(target)) == target
    assert len(common.validate_payload(target)) == 2
    assert (target / "config/prompts/script/system.md").read_text() == "system prompt"
    assert (target / "web/assets/cover.png").is_file()
    assert not (target / "backend").exists()
    assert not list(target.rglob(".env"))
    assert not (target / "data").exists()
    assert not (target / "build").exists()
    assert not (target / ".idea").exists()
    assert not (target / ".vscode").exists()


@pytest.mark.parametrize(
    "missing",
    ["uv.lock", "packages/studio_story/pyproject.toml", "packages/studio_story/src/studio_story/__init__.py"],
)
def test_payload_rejects_incomplete_workspace(tmp_path, missing):
    root = workspace(tmp_path)
    (root / missing).unlink()
    with pytest.raises(common.InstallerError, match="incomplete|source is missing"):
        common.validate_payload(root)


@pytest.mark.parametrize("fail_sync", [False, True])
def test_installer_uses_frozen_local_workspace_and_cleans_bootstrap(tmp_path, monkeypatch, fail_sync):
    root = workspace(tmp_path)
    python = tmp_path / "installation" / "venv" / "bin" / "python"
    calls = []
    unrelated = python.parent.parent.parent / "uv-bootstrap"
    unrelated.mkdir(parents=True)
    (unrelated / "sentinel").write_text("unowned directory")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "--target" in command:
            bootstrap = Path(command[command.index("--target") + 1])
            executable = bootstrap / "bin" / ("uv.exe" if install.os.name == "nt" else "uv")
            executable.parent.mkdir(parents=True)
            executable.touch()
        elif len(command) > 1 and command[1] == "sync" and fail_sync:
            raise RuntimeError("sync failed")

    monkeypatch.setattr(install, "run", run)
    if fail_sync:
        with pytest.raises(RuntimeError, match="sync failed"):
            install.install_workspace(python, root, ["s3", "pdf"], dry_run=False)
    else:
        install.install_workspace(python, root, ["s3", "pdf"], dry_run=False)

    assert calls[0][0] == [str(python), str(root / "scripts/sync_studio_resources.py")]
    assert calls[1][0][-1] == "uv==0.12.9"
    command, kwargs = calls[2]
    assert command[1:5] == ["sync", "--frozen", "--no-editable", "--no-dev"]
    assert command[-4:] == ["--extra", "s3", "--extra", "pdf"]
    assert kwargs["cwd"] == root
    assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == str(python.parent.parent)
    bootstrap = Path(calls[1][0][calls[1][0].index("--target") + 1])
    assert not bootstrap.exists()
    assert (unrelated / "sentinel").read_text() == "unowned directory"
    assert "studio-api" not in calls[1][0]


def test_launcher_uses_installed_entrypoint_and_explicit_resources(tmp_path):
    text = install.launcher_script(tmp_path / "installation", 8010, "development")
    assert "-m studio_api.desktop --port 8010" in text
    assert "STUDIO_RESOURCE_ROOT=" in text
    assert "APP_CONFIG_DIR=" in text
    assert "PYTHONPATH" not in text
