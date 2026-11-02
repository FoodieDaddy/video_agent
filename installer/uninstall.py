"""AI Film Studio uninstaller (compiled to ``uninstall.exe``).

Stops a running studio, removes the shortcuts and registry entry, deletes the
virtual environment, the private Python copy and the application files.
User data (``<root>\\data``: SQLite database, uploads, generated media) is kept
unless ``--purge`` is passed.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402 - after sys.path fiddling so the frozen exe works
    APP_NAME,
    ICON_NAME,
    LAUNCHER_NAME,
    InstallerError,
    default_root,
    delete_self_on_reboot,
    desktop_dir,
    ensure_utf8_console,
    kill_pids,
    log,
    pause_if_needed,
    processes_under,
    read_manifest,
    remove_path,
    self_test,
    start_menu_dir,
    unregister_uninstall,
)

FILE_TARGETS = (
    LAUNCHER_NAME,
    ICON_NAME,
    "install.json",
    "python-setup.exe",
    ".install-requirements.txt",
    "uninstall.exe",
    "start-studio.bat",
)
DIR_TARGETS = ("app", "venv", "python")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="uninstall.exe",
        description=f"Remove {APP_NAME} from this computer.",
    )
    parser.add_argument("--dir", default="", help="install directory (default: %%LOCALAPPDATA%%\\AIFilmStudio)")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--purge", action="store_true", help="also delete user data (database, media)")
    parser.add_argument("--dry-run", action="store_true", help="print what would be removed")
    parser.add_argument("--selftest", action="store_true", help="print diagnostics and exit (used by the build)")
    parser.add_argument("--no-pause", action="store_true", help="never wait for Enter at the end")
    return parser.parse_args(argv)


def shortcut_targets(manifest: dict) -> list[Path]:
    recorded = [Path(item) for item in manifest.get("shortcuts") or []]
    defaults = [
        desktop_dir() / f"{APP_NAME}.lnk",
        start_menu_dir() / APP_NAME / f"{APP_NAME}.lnk",
        start_menu_dir() / APP_NAME / "Uninstall AI Film Studio.lnk",
    ]
    seen: dict[str, Path] = {}
    for path in [*recorded, *defaults]:
        seen[str(path).lower()] = path
    return list(seen.values())


def looks_installed(root: Path) -> bool:
    return any((root / item).exists() for item in DIR_TARGETS) or (root / LAUNCHER_NAME).is_file()


def install_root(explicit: str) -> Path:
    """Which folder to uninstall.

    The start-menu shortcut starts this exe with no arguments, so the copy inside an
    installation must default to the folder it was copied into - not to
    ``%LOCALAPPDATA%\\AIFilmStudio``, which may be a different (or no) installation.
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    exe_dir = Path(sys.executable).resolve().parent
    if read_manifest(exe_dir) or looks_installed(exe_dir):
        return exe_dir
    return default_root()


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_console()
    args = parse_args(argv)
    if args.selftest:
        return self_test(expect_payload=False)
    root = install_root(args.dir)
    manifest = read_manifest(root)

    log(f"{APP_NAME} uninstaller")
    log(f"  install dir : {root}")

    if not manifest and not looks_installed(root) and not (args.purge and (root / "data").exists()):
        log(f"  nothing to remove: {APP_NAME} does not look installed in this folder.")
        pause_if_needed(not args.no_pause)
        return 0

    data_dir = Path(manifest.get("data_dir") or root / "data")
    version = manifest.get("version") or "unknown"
    log(f"  version     : {version}")
    if args.purge:
        log(f"  user data   : {data_dir} WILL BE DELETED")
    else:
        log(f"  user data   : {data_dir} will be kept (use --purge to delete it)")

    running = processes_under(root)
    if running:
        log(f"  running     : {len(running)} process(es) will be stopped")
    shortcuts = shortcut_targets(manifest)

    if args.dry_run:
        log("\nDry run - the following would be removed:")
        for name in DIR_TARGETS:
            if (root / name).exists():
                log(f"  dir  {root / name}")
        for name in FILE_TARGETS:
            if (root / name).exists():
                log(f"  file {root / name}")
        for link in shortcuts:
            if link.exists():
                log(f"  link {link}")
        if manifest.get("registry", True):
            log("  registry HKCU\\...\\Uninstall\\AIFilmStudio")
        if args.purge:
            log(f"  data {data_dir}")
        return 0

    if not args.yes:
        try:
            answer = input("\nType YES to uninstall: ").strip()
        except EOFError:
            answer = ""
        if answer.upper() != "YES":
            log("Cancelled.")
            pause_if_needed(not args.no_pause)
            return 1

    try:
        if running:
            log("\nStopping the studio...")
            kill_pids(running)
            time.sleep(1.5)

        log("Removing shortcuts...")
        for link in shortcuts:
            if link.exists():
                remove_path(link)
                log(f"  {link}")
        menu_dir = start_menu_dir() / APP_NAME
        if menu_dir.is_dir() and not any(menu_dir.iterdir()):
            remove_path(menu_dir)

        log("Removing the uninstall registry entry...")
        unregister_uninstall()

        log("Removing application files...")
        for name in DIR_TARGETS:
            path = root / name
            if path.exists():
                remove_path(path)
                log(f"  {path}")
        for name in FILE_TARGETS:
            path = root / name
            if path.exists() and path != Path(sys.executable).resolve():
                remove_path(path)
                log(f"  {path}")

        if args.purge:
            log("Removing user data...")
            remove_path(data_dir)
            remove_path(root)
            log("\nDone. AI Film Studio and its data were removed.")
        else:
            for child in list(root.iterdir()):
                if child.is_dir() and child.resolve() != data_dir.resolve():
                    remove_path(child)
            log("\nDone. The application was removed; user data was kept at:")
            log(f"  {data_dir}")
            log("Run uninstall.exe --purge (or delete that folder) to remove it as well.")

        self_path = Path(sys.executable).resolve()
        if self_path.parent == root or self_path.parent == (root / "uninstall.exe").parent:
            if self_path.exists():
                delete_self_on_reboot(self_path)
                log("\nThis uninstaller is inside the install folder and will be deleted on the next restart.")
        return 0
    except InstallerError as exc:
        log(f"\nERROR: {exc}")
        return 1
    except OSError as exc:
        log(f"\nERROR while removing files: {exc}")
        log("Close any window of the studio (or the uninstall window) and try again.")
        return 1
    finally:
        pause_if_needed(not args.no_pause)


if __name__ == "__main__":
    raise SystemExit(main())
