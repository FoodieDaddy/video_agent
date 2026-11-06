"""各平台安装器共用的冻结 workspace 安装引擎。

本模块不创建桌面入口、不停止运行进程、不决定用户安装目录。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import common
from common import InstallerError

UV_VERSION = "0.12.9"


def dependency_list(meta: dict, extras: list[str]) -> list[str]:
    available = meta.get("extras", {})
    unknown = [name for name in extras if name not in available]
    if unknown:
        raise InstallerError(
            f"Unknown extra(s): {', '.join(unknown)}. Available: {', '.join(sorted(available)) or 'none'}"
        )
    packages = list(meta.get("dependencies", []))
    for name in extras:
        packages.extend(available[name])
    return packages


def _commands(venv_python: Path, app_dir: Path, extras: list[str], bootstrap: Path):
    uv = bootstrap / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    bootstrap_command = [
        str(venv_python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--upgrade",
        "--target",
        str(bootstrap),
        f"uv=={UV_VERSION}",
    ]
    command = [
        str(uv),
        "sync",
        "--frozen",
        "--no-editable",
        "--no-dev",
        "--project",
        str(app_dir),
        "--python",
        str(venv_python),
    ]
    for extra in extras:
        command.extend(["--extra", extra])
    return uv, bootstrap_command, command


def install_workspace(
    venv_python: Path, app_dir: Path, extras: list[str], *, dry_run: bool, runner=None, logger=None
) -> None:
    """使用固定 uv 同步完整 workspace；只清理本次创建的随机引导目录。"""
    run = runner or common.run
    log = logger or common.log
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(venv_python.parent.parent)
    log(f"  synchronizing the bundled workspace with uv {UV_VERSION} and uv.lock")
    if dry_run:
        _, bootstrap_command, command = _commands(
            venv_python, app_dir, extras, Path(tempfile.gettempdir()) / "studio-uv-bootstrap-PREVIEW"
        )
        log(f"  would bootstrap: {bootstrap_command}")
        log(f"  would run: {command}")
        return
    common.validate_payload(app_dir)
    run([str(venv_python), str(app_dir / "scripts" / "sync_studio_resources.py")], cwd=app_dir)
    # 引导目录在 runtime 环境之外；避免精确同步清理自身，且不删除用户同名目录。
    with tempfile.TemporaryDirectory(prefix="studio-uv-bootstrap-", ignore_cleanup_errors=True) as directory:
        uv, bootstrap_command, command = _commands(venv_python, app_dir, extras, Path(directory))
        run(bootstrap_command)
        if not uv.is_file():
            raise InstallerError(f"Pinned uv bootstrap is missing: {uv}")
        run(command, cwd=app_dir, env=env)


def verify_packages(venv_python: Path, *, runner=None) -> None:
    run = runner or common.run
    run(
        [
            str(venv_python),
            "-c",
            "import fastapi, uvicorn, sqlalchemy, yaml, PIL, docx, pydantic, httpx; "
            "import studio_api.desktop, studio_api.launcher, studio_story, studio_production, studio_platform; "
            "print('workspace deps ok')",
        ]
    )
