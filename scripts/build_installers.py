"""Build ``dist/install.exe`` and ``dist/uninstall.exe``.

Usage (Windows, from the repository root):

    python scripts/build_installers.py

The PyInstaller bootstrappers only use the standard library, so they run on a
machine without Python.  The application itself is staged into ``build/payload``
and embedded in ``install.exe``; installation synchronizes every member against
the included ``uv.lock`` using a pinned uv bootstrap.

The script rebuilds itself with a clean python.org CPython: an executable frozen
from a conda interpreter ships without the OpenSSL DLLs, and its ``_ssl`` module
then fails to import - which would break the very download step install.exe
exists for.  Pass ``--rebuild-python`` to throw the build interpreter away.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_DIR = REPO_ROOT / "build"
PAYLOAD_DIR = BUILD_DIR / "payload"
DIST_DIR = REPO_ROOT / "dist"
ASSETS_DIR = REPO_ROOT / "installer" / "assets"
INSTALLER_DIR = REPO_ROOT / "installer"
BUILD_PYTHON_DIR = BUILD_DIR / "python"
BUILD_VENV_DIR = BUILD_DIR / "venv"
BUILD_READY = BUILD_DIR / "venv-ready.txt"
BUILD_REQUIREMENTS = ("pyinstaller>=6.6", "pillow>=10")

sys.path.insert(0, str(INSTALLER_DIR))
sys.path.insert(0, str(REPO_ROOT))

from common import (  # noqa: E402 - the installer package is not importable
    PYTHON_VERSION,
    download,
    log,
    machine_arch,
    project_metadata,
    python_installer_url,
    run,
)
from scripts.build_releases import (  # noqa: E402
    committed_windows_source_fingerprint,
    payload_source_manifest,
    source_snapshot,
    write_windows_installers_manifest,
)
from scripts.build_releases import (  # noqa: E402
    stage_payload as stage_workspace_payload,
)

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def build_venv_python() -> Path:
    return BUILD_VENV_DIR / "Scripts" / "python.exe"


def is_conda_python() -> bool:
    return "Anaconda" in sys.version or bool(os.environ.get("CONDA_PREFIX"))


def bootstrap_build_python(force: bool = False) -> Path:
    """Install a python.org CPython + build venv under ``build/``."""
    venv_python = build_venv_python()
    if venv_python.is_file() and BUILD_READY.is_file() and not force:
        return venv_python

    if force:
        shutil.rmtree(BUILD_VENV_DIR, ignore_errors=True)
        shutil.rmtree(BUILD_PYTHON_DIR, ignore_errors=True)
        BUILD_READY.unlink(missing_ok=True)

    python = BUILD_PYTHON_DIR / "python.exe"
    if not python.is_file():
        url = python_installer_url()
        log(f"fetching python.org CPython {PYTHON_VERSION} ({machine_arch()})")
        setup = download(url, BUILD_DIR / "python-setup.exe", label="build Python")
        log(f"installing it into {BUILD_PYTHON_DIR} (silent, ~1 minute)...")
        run(
            [
                str(setup),
                "/quiet",
                "InstallAllUsers=0",
                f"TargetDir={BUILD_PYTHON_DIR}",
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
        setup.unlink(missing_ok=True)
    if not python.is_file():
        raise SystemExit(f"build Python was installed but {python} is missing")

    if not venv_python.is_file():
        log(f"creating the build virtual environment {BUILD_VENV_DIR}")
        run([str(python), "-m", "venv", str(BUILD_VENV_DIR)])
    log("installing the build requirements")
    run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            *BUILD_REQUIREMENTS,
        ]
    )
    BUILD_READY.parent.mkdir(parents=True, exist_ok=True)
    BUILD_READY.write_text(f"{PYTHON_VERSION}\n", encoding="utf-8")
    return venv_python


def paint_icon(path: Path) -> Path:
    """Draw a clapperboard-ish icon so shortcuts do not look generic."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        log("Pillow is not installed - building without a custom icon")
        return path if path.is_file() else Path()

    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, size - 8, size - 8), radius=44, fill=(24, 28, 38, 255))
    # clapper stripes
    top = 44
    draw.rectangle((36, top, size - 36, top + 52), fill=(232, 236, 244, 255))
    for index in range(6):
        left = 36 + index * 30
        draw.polygon(
            [(left, top), (left + 16, top), (left + 8, top + 52), (left - 8, top + 52)],
            fill=(214, 60, 52, 255),
        )
    # play triangle
    draw.polygon([(104, 128), (104, 208), (178, 168)], fill=(248, 196, 68, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    return path


def stage_payload(source_root: Path | None = None) -> Path:
    log(f"staging application files into {PAYLOAD_DIR}")
    # 默认来源是 HEAD；只有显式参数才允许调用方提供目录当前内容。
    with source_snapshot(source_root, git_root=REPO_ROOT) as (source, provenance):
        stage_workspace_payload(source, PAYLOAD_DIR)
        metadata = payload_source_manifest(PAYLOAD_DIR, provenance)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (BUILD_DIR / "windows-payload-source.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return PAYLOAD_DIR


def run_pyinstaller(name: str, script: Path, *, with_payload: bool, icon: Path | None) -> Path:
    work = BUILD_DIR / "pyinstaller" / name
    spec = BUILD_DIR / "spec"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--console",
        "--name",
        name,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(work),
        "--specpath",
        str(spec),
        "--paths",
        str(INSTALLER_DIR),
        "--add-data",
        f"{ASSETS_DIR}{os.pathsep}assets",
    ]
    if icon and icon.is_file():
        command += ["--icon", str(icon)]
    if with_payload:
        command += ["--add-data", f"{PAYLOAD_DIR}{os.pathsep}payload"]
    command.append(str(script))

    log(f"building {name}.exe")
    subprocess.run(command, check=True, cwd=REPO_ROOT)
    output = DIST_DIR / f"{name}.exe"
    if not output.is_file():
        raise SystemExit(f"PyInstaller did not produce {output}")
    return output


def verify(exe: Path) -> None:
    """Run ``install.exe --selftest``; it fails when the frozen SSL is broken."""
    log(f"verifying {exe.name}")
    result = subprocess.run([str(exe), "--selftest"], cwd=REPO_ROOT)
    if result.returncode != 0:
        raise SystemExit(f"{exe.name} failed its self test (exit code {result.returncode})")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build dist/install.exe and dist/uninstall.exe.")
    parser.add_argument(
        "--rebuild-python",
        action="store_true",
        help="discard build/venv and build/python and bootstrap them again",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        help="显式指定内嵌载荷源码目录；缺省使用 Git HEAD 快照，编译安装代码仍须匹配 HEAD",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if os.name != "nt":
        log("PyInstaller builds Windows executables on Windows only - run this script on Windows.")
        return 2

    source_fingerprint = committed_windows_source_fingerprint(REPO_ROOT)

    if is_conda_python() and not Path(sys.executable).resolve().is_relative_to(BUILD_VENV_DIR.resolve()):
        log(f"the current interpreter is conda-based ({sys.version.split()[0]});")
        log("its executables ship without OpenSSL, so the installers are built with python.org CPython.")

    venv_python = bootstrap_build_python(force=args.rebuild_python)
    if Path(sys.executable).resolve() != venv_python.resolve():
        log(f"re-running the build with {venv_python}")
        log("")
        return subprocess.run(
            [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=REPO_ROOT
        ).returncode

    log(f"repository: {REPO_ROOT}")
    log(f"build python: {sys.version.split()[0]} ({sys.executable})")
    icon = paint_icon(ASSETS_DIR / "studio.ico")
    # 旧清单不能在本次构建失败后继续冒充新一轮成功产物。
    (DIST_DIR / "windows-installers.json").unlink(missing_ok=True)
    stage_payload(args.source_root)
    payload_source = json.loads((BUILD_DIR / "windows-payload-source.json").read_text(encoding="utf-8"))
    if payload_source["files_sha256"].get("uv.lock") != source_fingerprint["uv_lock_sha256"]:
        raise SystemExit("内嵌载荷锁文件与已提交的安装构建输入不一致")
    if project_metadata(PAYLOAD_DIR)["version"] != source_fingerprint["version"]:
        raise SystemExit("内嵌载荷版本与已提交的安装构建输入不一致")
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(BUILD_DIR / "spec", ignore_errors=True)

    install_exe = run_pyinstaller("install", INSTALLER_DIR / "install.py", with_payload=True, icon=icon)
    uninstall_exe = run_pyinstaller(
        "uninstall", INSTALLER_DIR / "uninstall.py", with_payload=False, icon=icon
    )
    verify(install_exe)
    verify(uninstall_exe)
    if payload_source_manifest(PAYLOAD_DIR, payload_source) != payload_source:
        raise SystemExit("Windows 编译期间内嵌载荷发生变化，请重新构建")
    sidecar = write_windows_installers_manifest(
        REPO_ROOT,
        DIST_DIR,
        payload_source=payload_source,
        expected_source=source_fingerprint,
    )

    log("")
    for exe in (install_exe, uninstall_exe):
        log(f"  {exe}  ({exe.stat().st_size / 1048576:.1f} MB)")
    log(f"  {sidecar} (source and executable hashes)")
    log("")
    log("Ship install.exe and uninstall.exe together:")
    log("  install.exe    deploy (downloads Python if needed, installs dependencies, shortcuts)")
    log("  uninstall.exe  remove the environment (add --purge to drop user data too)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
