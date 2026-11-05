"""AI Film Studio one-click installer (compiled to ``install.exe``).

What it does, in order:

1. picks an install directory (default ``%LOCALAPPDATA%\\AIFilmStudio``);
2. finds CPython >= 3.11, or downloads and installs a private copy;
3. copies the complete workspace and creates a virtual environment;
4. synchronizes its lockfile, writes ``start-studio.cmd`` and a manifest;
5. creates desktop / start-menu shortcuts and an uninstall registry entry;
6. optionally starts the studio and opens the browser.

Run it with ``--dry-run`` to see the plan without touching anything.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
from common import (  # noqa: E402 - after sys.path fiddling so the frozen exe works
    APP_NAME,
    ICON_NAME,
    LAUNCHER_NAME,
    PYTHON_VERSION,
    InstallerError,
    copy_payload,
    create_shortcut,
    default_root,
    desktop_dir,
    download,
    ensure_utf8_console,
    ffmpeg_available,
    find_python,
    kill_pids,
    log,
    pause_if_needed,
    payload_root,
    port_available,
    processes_under,
    project_metadata,
    python_installer_url,
    read_manifest,
    register_uninstall,
    run,
    start_menu_dir,
    utc_now,
    winget_available,
    write_manifest,
    write_text,
)

UV_VERSION = "0.12.9"


# --------------------------------------------------------------------- launcher
def launcher_script(root: Path, port: int, env: str) -> str:
    """A console script the shortcut can point at: it starts and stops the app."""
    app_dir = root / "app"
    venv_python = root / "venv" / "Scripts" / "python.exe"
    lines = [
        "@echo off",
        "setlocal",
        f"title {APP_NAME}",
        f'set "APP_ENV={env}"',
        f'set "APP_DATA_DIR={root}\\data"',
        f'set "STORAGE_ROOT={root}\\data\\storage"',
        f'set "STUDIO_RESOURCE_ROOT={app_dir}"',
        f'set "APP_CONFIG_DIR={app_dir}\\config"',
        "set PYTHONIOENCODING=utf-8",
        "set PYTHONUTF8=1",
        f'cd /d "{app_dir}"',
        f'"{venv_python}" -m studio_api.desktop --port {port} %*',
        'set "STUDIO_EXIT=%ERRORLEVEL%"',
        "rem leave the application folder, otherwise this window keeps it locked",
        'cd /d "%USERPROFILE%"',
        'if not "%STUDIO_EXIT%"=="0" pause',
    ]
    return "\r\n".join(lines) + "\r\n"


def sibling_uninstaller() -> Path | None:
    """``uninstall.exe`` shipped next to this exe is copied into the install dir."""
    candidates = []
    if common.is_frozen():
        candidates.append(Path(sys.executable).with_name("uninstall.exe"))
    candidates.append(Path.cwd() / "uninstall.exe")
    candidates.append(Path(__file__).resolve().parent / "uninstall.exe")
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve() != Path(sys.executable).resolve():
            return candidate
    return None


# -------------------------------------------------------------------- install
def install_python(root: Path, *, dry_run: bool) -> str:
    url = python_installer_url()
    # The python.org installer silently ignores a relative TargetDir, so resolve it here.
    target = (root / "python").resolve()
    log(
        f"  no Python >= {'.'.join(str(part) for part in common.MIN_PYTHON)} found; "
        f"a private copy will be installed into {target}"
    )
    if dry_run:
        return str(target / "python.exe")
    installer = download(url, root / "python-setup.exe", label="Python runtime")
    log("  running the Python installer silently (this takes a minute)...")
    run(
        [
            str(installer),
            "/quiet",
            "InstallAllUsers=0",
            f"TargetDir={target}",
            "PrependPath=0",
            "Include_launcher=0",
            "Shortcuts=0",
            "AssociateFiles=0",
            "Include_test=0",
            "Include_doc=0",
            "Include_symbols=0",
            "Include_debug=0",
        ]
    )
    installer.unlink(missing_ok=True)
    python = target / "python.exe"
    if not python.is_file():
        # The bundle is registered per version: if this exact CPython is already
        # installed anywhere, the downloaded exe exits 0 without installing again.
        raise InstallerError(
            f"The Python runtime did not install into {target}.\n"
            f"  Python {PYTHON_VERSION} may already be installed somewhere: re-run with "
            '--python "<path to python.exe>" to reuse it, or install CPython manually '
            "and run this installer again."
        )
    return str(python)


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


def install_workspace(venv_python: Path, app_dir: Path, extras: list[str], *, dry_run: bool) -> None:
    """使用固定 uv 同步完整 workspace；本地成员不会被当成 PyPI 包下载。"""
    bootstrap = venv_python.parent.parent.parent / "uv-bootstrap"
    # uv 官方 --target 布局把可执行文件放在目标的 bin/（Windows 同样如此）。
    uv = bootstrap / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    # uv 放在 runtime 环境外，避免精确同步清理自身或 Windows 的文件锁冲突。
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
    env = os.environ.copy()
    env["UV_PROJECT_ENVIRONMENT"] = str(venv_python.parent.parent)
    log(f"  synchronizing the bundled workspace with uv {UV_VERSION} and uv.lock")
    if dry_run:
        log(f"  would bootstrap: {bootstrap_command}")
        log(f"  would run: {command}")
        return
    common.validate_payload(app_dir)
    run([str(venv_python), str(app_dir / "scripts" / "sync_studio_resources.py")], cwd=app_dir)
    try:
        run(bootstrap_command)
        if not uv.is_file():
            raise InstallerError(f"Pinned uv bootstrap is missing: {uv}")
        run(command, cwd=app_dir, env=env)
    finally:
        shutil.rmtree(bootstrap, ignore_errors=True)


def verify_packages(venv_python: Path) -> None:
    run(
        [
            str(venv_python),
            "-c",
            "import fastapi, uvicorn, sqlalchemy, yaml, PIL, docx, pydantic, httpx; "
            "import studio_api.desktop, studio_story, studio_production, studio_platform; "
            "print('workspace deps ok')",
        ]
    )


def create_shortcuts(root: Path, *, enabled: bool) -> list[str]:
    if not enabled:
        return []
    launcher = root / LAUNCHER_NAME
    icon = root / ICON_NAME if (root / ICON_NAME).is_file() else None
    created: list[Path] = []
    created.append(
        create_shortcut(
            desktop_dir() / f"{APP_NAME}.lnk",
            launcher,
            working_dir=root,
            icon=icon,
            description=f"{APP_NAME} - start the studio",
        )
    )
    menu = start_menu_dir() / APP_NAME
    created.append(
        create_shortcut(
            menu / f"{APP_NAME}.lnk",
            launcher,
            working_dir=root,
            icon=icon,
            description=f"{APP_NAME} - start the studio",
        )
    )
    uninstaller = root / "uninstall.exe"
    if uninstaller.is_file():
        created.append(
            create_shortcut(
                menu / "Uninstall AI Film Studio.lnk",
                uninstaller,
                arguments=f'--dir "{root}"',
                working_dir=root,
                icon=icon,
                description=f"Remove {APP_NAME} from this computer",
            )
        )
    return [str(path) for path in created]


def default_shortcut_paths() -> list[str]:
    return [
        str(desktop_dir() / f"{APP_NAME}.lnk"),
        str(start_menu_dir() / APP_NAME / f"{APP_NAME}.lnk"),
        str(start_menu_dir() / APP_NAME / "Uninstall AI Film Studio.lnk"),
    ]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install.exe",
        description="Install AI Film Studio for the current user (no admin rights needed).",
    )
    parser.add_argument(
        "--dir", default="", help="install directory (default: %%LOCALAPPDATA%%\\AIFilmStudio)"
    )
    parser.add_argument("--port", type=int, default=0, help="preferred HTTP port (default 8010)")
    parser.add_argument("--python", default="", help="path to a Python >= 3.11 to build the venv with")
    parser.add_argument("--extras", default="", help="comma separated optional extras, e.g. s3,pdf")
    parser.add_argument(
        "--from", dest="source", default="", help="use this source tree instead of the bundled payload"
    )
    parser.add_argument("--env", default="development", help="APP_ENV for the launcher (default development)")
    parser.add_argument(
        "--no-shortcuts", action="store_true", help="do not create desktop/start-menu shortcuts"
    )
    parser.add_argument(
        "--no-registry", action="store_true", help="do not add a Settings > Apps uninstall entry"
    )
    parser.add_argument("--no-launch", action="store_true", help="do not start the studio afterwards")
    parser.add_argument("--with-ffmpeg", action="store_true", help="try to install FFmpeg through winget")
    parser.add_argument("--force", action="store_true", help="install into a non-empty directory")
    parser.add_argument("--dry-run", action="store_true", help="print the plan without changing anything")
    parser.add_argument(
        "--selftest", action="store_true", help="print diagnostics and exit (used by the build)"
    )
    parser.add_argument("--no-pause", action="store_true", help="never wait for Enter at the end")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_console()
    args = parse_args(argv)
    if args.selftest:
        return common.self_test(expect_payload=True)
    dry_run = bool(args.dry_run)
    extras = [item.strip() for item in args.extras.split(",") if item.strip()]

    root = Path(args.dir).expanduser().resolve() if args.dir else default_root()
    existing = read_manifest(root)
    log(f"{APP_NAME} installer")
    log(f"  install dir : {root}")
    if dry_run:
        log("  mode        : dry run (nothing will be written)")

    try:
        payload = payload_root(args.source)
        meta = project_metadata(payload)
        dependency_list(meta, extras)  # 先校验 extra 名称，避免复制后才发现输入错误。
        log(f"  version     : {meta['version']}")
        log(f"  payload     : {payload}")

        if root.exists() and not existing and any(root.iterdir()) and not args.force:
            raise InstallerError(
                f"{root} is not empty and has no installation manifest. "
                "Use --dir to pick another folder or --force to install anyway."
            )
        if not dry_run:
            root.mkdir(parents=True, exist_ok=True)

        # ---------------------------------------------------------- 1. python
        log("\n[1/7] Python runtime")
        found = find_python(root, args.python or None)
        if found:
            python_exe, version = found
            log(f"  using {python_exe} ({version[0]}.{version[1]})")
        else:
            python_exe = install_python(root, dry_run=dry_run)

        # ------------------------------------------------------------ 2. venv
        log("\n[2/7] Virtual environment")
        venv = root / "venv"
        venv_python = venv / "Scripts" / "python.exe"
        if venv_python.is_file():
            log(f"  reusing {venv}")
        elif dry_run:
            log(f"  would create {venv}")
        else:
            run([python_exe, "-m", "venv", str(venv)])
        if not venv_python.is_file():
            venv_python = venv / "bin" / "python"

        # ---------------------------------------------------------- 3. app files
        log("\n[3/7] Application files")
        app_dir = root / "app"
        running = processes_under(root)
        if running and not dry_run:
            # Re-installing over a running studio would fail: its files are locked.
            log(f"  stopping {len(running)} running process(es) of the studio")
            kill_pids(running)
            time.sleep(1.5)
        if dry_run:
            log(f"  would copy {payload} -> {app_dir}")
        else:
            copy_payload(payload, app_dir)
            log(f"  copied to {app_dir}")
            icon_source = common.asset(ICON_NAME)
            if icon_source:
                shutil.copy2(icon_source, root / ICON_NAME)
            uninstaller = sibling_uninstaller()
            if uninstaller is not None:
                shutil.copy2(uninstaller, root / "uninstall.exe")
                log("  copied uninstall.exe into the install directory")

        # 本地成员源码必须先复制，再同步包含 workspace 依赖的冻结锁文件。
        log("\n[4/7] Locked workspace dependencies")
        install_workspace(venv_python, app_dir, extras, dry_run=dry_run)
        if not dry_run:
            verify_packages(venv_python)

        # ------------------------------------------------------ 5. launcher file
        log("\n[5/7] Launcher and manifest")
        previous_port = int(existing.get("port") or 0)
        preferred = args.port or previous_port or 8010
        if port_available(preferred):
            port = preferred
        else:
            raise InstallerError(
                f"Port {preferred} is busy. Close the existing studio or explicitly select --port."
            )
        if dry_run:
            log(f"  would write {root / LAUNCHER_NAME} (port {port})")
        else:
            write_text(root / LAUNCHER_NAME, launcher_script(root, port, args.env))
            log(f"  wrote {root / LAUNCHER_NAME} (port {port})")

        manifest = {
            "app": APP_NAME,
            "version": meta["version"],
            "root": str(root),
            "app_dir": str(app_dir),
            "venv": str(venv),
            "data_dir": str(root / "data"),
            "port": port,
            "env": args.env,
            "extras": extras,
            "private_python": str(root / "python") if (root / "python").is_dir() else "",
            "shortcuts": default_shortcut_paths() if not args.no_shortcuts else [],
            "registry": not args.no_registry,
            "installed_at": utc_now(),
            # A frozen payload lives in PyInstaller's temp folder and disappears
            # with the exe, so only record a source tree that will still exist.
            "payload": "" if common.is_frozen() else str(payload),
        }
        if not dry_run:
            write_manifest(root, manifest)

        # -------------------------------------------------------- 6. shortcuts
        log("\n[6/7] Shortcuts and registry")
        if args.no_shortcuts:
            log("  skipped (--no-shortcuts)")
        elif dry_run:
            log(f"  would create shortcuts in {desktop_dir()} and {start_menu_dir() / APP_NAME}")
        else:
            shortcuts = create_shortcuts(root, enabled=True)
            manifest["shortcuts"] = shortcuts
            for path in shortcuts:
                log(f"  {path}")
            write_manifest(root, manifest)
        if args.no_registry:
            log("  registry entry skipped (--no-registry)")
        elif dry_run:
            log("  would register the uninstall entry under HKCU")
        else:
            register_uninstall(manifest)
            log("  registered in Settings > Apps")

        # ------------------------------------------------------------ 7. ffmpeg
        log("\n[7/7] FFmpeg (video rendering)")
        if ffmpeg_available():
            log("  ffmpeg found on PATH")
        elif args.with_ffmpeg and winget_available():
            if dry_run:
                log("  would run: winget install Gyan.FFmpeg")
            else:
                log("  installing FFmpeg through winget...")
                run(
                    [
                        "winget",
                        "install",
                        "--id",
                        "Gyan.FFmpeg",
                        "--silent",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                    ],
                    check=False,
                )
        else:
            log("  WARNING: ffmpeg was not found. The pipeline can still plan the timeline,")
            log("           but rendering a film needs FFmpeg. Install it with:")
            log("             winget install Gyan.FFmpeg")
            log("           or run this installer again with --with-ffmpeg.")

        if dry_run:
            log("\nDry run complete - nothing was changed.")
            return 0

        log("\nInstallation complete.")
        log(f"  start    : {root / LAUNCHER_NAME}")
        log(f"  console  : http://127.0.0.1:{port}/")
        log(f"  data     : {root / 'data'}")
        log(f"  uninstall: {root / 'uninstall.exe'}")

        if not args.no_launch:
            log("\nStarting the studio...")
            try:
                # CreateProcess cannot run a .cmd directly; ShellExecute can, and it gives
                # the studio its own console window (closing it stops the studio).
                os.startfile(str(root / LAUNCHER_NAME))  # type: ignore[attr-defined]
            except OSError as exc:
                log(f"  could not start it automatically ({exc})")
                log(f"  start it yourself with {root / LAUNCHER_NAME}")
        return 0
    except InstallerError as exc:
        log(f"\nERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        log("\nCancelled.")
        return 130
    except Exception as exc:  # pragma: no cover - unexpected failure
        log(f"\nUNEXPECTED ERROR: {type(exc).__name__}: {exc}")
        return 1
    finally:
        pause_if_needed(not args.no_pause)


if __name__ == "__main__":
    raise SystemExit(main())
