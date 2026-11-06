"""macOS/Linux 用户级安装与卸载；运行进程由 studio_api.launcher 管理。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import workspace as workspace_engine  # noqa: E402

OWNER = "ai-film-studio-posix-v1"
SCHEMA_VERSION = 1
MANAGED_DIRECTORIES = ("app", "venv", "run", "installer")
USER_DIRECTORIES = ("data", "config")
LAUNCHER_FILES = (
    "start-studio.sh",
    "stop-studio.sh",
    "studio-status.sh",
    "uninstall-studio.sh",
    "Start AI Film Studio.command",
    "Stop AI Film Studio.command",
)


def current_platform(explicit: str = "") -> str:
    if sys.platform == "darwin":
        actual = "macos"
    elif sys.platform.startswith("linux"):
        actual = "linux"
    else:
        raise common.InstallerError("此入口只支持 macOS/Linux；Windows 请使用 install.exe")
    if explicit and explicit != actual:
        raise common.InstallerError(f"当前系统是 {actual}，不能安装 {explicit} 发布包")
    return actual


def default_root(target: str) -> Path:
    if target == "macos":
        return Path.home() / "Library" / "Application Support" / common.APP_NAME
    return Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "ai-film-studio"


def _root(path: str | Path, *, source: Path | None = None) -> Path:
    raw = Path(path).expanduser().absolute()
    if any(value in str(raw) for value in ("\n", "\r", "\x00")) or raw.is_symlink():
        raise common.InstallerError("安装目录不能是符号链接或包含换行字符")
    root = raw.resolve()
    if len(root.parts) < 3 or root in {Path.home().resolve(), Path.home().resolve().parent}:
        raise common.InstallerError("请选择独立的应用安装目录，不能使用系统根或用户主目录")
    if source is not None:
        source = source.resolve()
        if root.is_relative_to(source) or source.is_relative_to(root):
            raise common.InstallerError("安装目录和源码载荷目录不能互相包含")
    if root.exists() and not root.is_dir():
        raise common.InstallerError("安装目录已存在且不是文件夹")
    return root


def _check_children(root: Path) -> None:
    for name in (*MANAGED_DIRECTORIES, *USER_DIRECTORIES, *LAUNCHER_FILES, common.MANIFEST_NAME):
        if (root / name).is_symlink():
            raise common.InstallerError(f"受管路径不能是符号链接：{root / name}")
    if (root / "config" / ".env").is_symlink():
        raise common.InstallerError("本机配置文件不能是符号链接")


@contextmanager
def operation_lock(root: Path):
    """与启动器共享生命周期锁；锁文件默认保留，避免更换 inode 后绕过锁。"""
    import fcntl

    run_dir = root / "run"
    if run_dir.is_symlink():
        raise common.InstallerError("运行目录不能是符号链接")
    run_dir.mkdir(exist_ok=True)
    lock_path = run_dir / "start.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise common.InstallerError("另一个启动、安装或卸载操作正在进行") from error
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def read_installation(root: Path, *, required: bool = True) -> dict:
    _check_children(root)
    manifest = common.read_manifest(root)
    if not manifest:
        if required:
            raise common.InstallerError("该目录没有本安装器的有效安装记录，拒绝删除")
        return {}
    if not isinstance(manifest, dict):
        raise common.InstallerError("安装记录格式不正确，拒绝覆盖/删除")
    expected = {
        "owner": OWNER,
        "schema_version": SCHEMA_VERSION,
        "install_root": str(root),
        "app_dir": str(root / "app"),
        "venv_dir": str(root / "venv"),
        "data_dir": str(root / "data"),
        "config_dir": str(root / "config"),
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise common.InstallerError("安装记录归属或目录不匹配，拒绝覆盖/删除")
    if manifest.get("platform") not in {"macos", "linux"}:
        raise common.InstallerError("该目录不属于 macOS/Linux 安装器")
    if manifest.get("owned_paths") != list((*MANAGED_DIRECTORIES, *USER_DIRECTORIES, *LAUNCHER_FILES)):
        raise common.InstallerError("安装记录的受管路径不匹配，拒绝覆盖/删除")
    return manifest


def find_python(explicit: str = "") -> str:
    candidates = (
        [explicit] if explicit else [sys.executable, "python3.13", "python3.12", "python3.11", "python3"]
    )
    for candidate in candidates:
        result = common._probe_python([candidate])
        if result and result[1] >= common.MIN_PYTHON:
            return result[0]
    raise common.InstallerError("需要 Python 3.11 或更新版本；可用 --python 指定已安装解释器")


def _check_ffmpeg() -> None:
    missing = [
        name for name in ("ffmpeg", "ffprobe") if not shutil.which(os.getenv(name.upper() + "_BIN") or name)
    ]
    if missing:
        raise common.InstallerError("缺少 " + ", ".join(missing) + "；请先为当前平台安装 FFmpeg 并加入 PATH")


def _check_source_links(source: Path) -> None:
    """源码载荷不跟随符号链接，防止复制链接指向的本机私有文件。"""
    for directory, subdirectories, files in os.walk(source, followlinks=False):
        path = Path(directory)
        ignored = common._ignore(directory, subdirectories + files)
        subdirectories[:] = [name for name in subdirectories if name not in ignored]
        for name in subdirectories + [name for name in files if name not in ignored]:
            if (path / name).is_symlink():
                raise common.InstallerError(f"发布载荷不能包含符号链接：{path / name}")


def _executable(path: Path, content: str) -> None:
    common.write_text(path, content)
    path.chmod(0o755)


def launcher_script(root: Path, action: str, port: int) -> str:
    python = root / "venv" / "bin" / "python"
    command = [
        str(python),
        "-m",
        "studio_api.launcher",
        action,
        "--install-root",
        str(root),
        "--port",
        str(port),
    ]
    return "#!/bin/sh\nset -eu\nexec " + shlex.join(command) + ' "$@"\n'


def _uninstall_script(root: Path) -> str:
    command = [
        str(root / "venv" / "bin" / "python"),
        str(root / "installer" / "posix.py"),
        "uninstall",
        "--dir",
        str(root),
    ]
    return "#!/bin/sh\nset -eu\nexec " + shlex.join(command) + ' "$@"\n'


def _shortcut_content(root: Path, target: str) -> tuple[str, str]:
    if target == "macos":
        return "AI Film Studio.command", "#!/bin/sh\nexec " + shlex.quote(
            str(root / "start-studio.sh")
        ) + ' "$@"\n'
    quoted = (
        str(root / "start-studio.sh")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("%", "%%")
    )
    return (
        "ai-film-studio.desktop",
        '[Desktop Entry]\nType=Application\nName=AI Film Studio\nExec="'
        + quoted
        + '"\nTerminal=false\nCategories=AudioVideo;\n',
    )


def _shortcut(root: Path, target: str, directory: Path | None, previous: list[dict]) -> dict | None:
    if directory is None:
        return None
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    name, content = _shortcut_content(root, target)
    link = directory / name
    if link.exists() or link.is_symlink():
        if link.is_symlink() or not link.is_file():
            raise common.InstallerError(f"快捷方式已存在，拒绝覆盖：{link}")
        digest = hashlib.sha256(link.read_bytes()).hexdigest()
        if not any(record.get("path") == str(link) and record.get("sha256") == digest for record in previous):
            raise common.InstallerError(f"快捷方式已存在且未被本安装记录持有：{link}")
    _executable(link, content)
    return {"path": str(link), "sha256": hashlib.sha256(content.encode()).hexdigest()}


def install(args: argparse.Namespace) -> dict:
    target = current_platform(args.platform)
    bundled = Path(__file__).resolve().parents[1] / "payload"
    source = common.payload_root(args.source or (str(bundled) if bundled.is_dir() else None))
    _check_source_links(source)
    root = _root(args.dir or default_root(target), source=source)
    existing = read_installation(root, required=False)
    if root.exists() and not existing and any(root.iterdir()):
        raise common.InstallerError("目录非空且无本安装器的有效记录，请另选 --dir")
    if (root / "run" / "instance.json").exists():
        raise common.InstallerError("检测到运行记录，请先使用 stop-studio.sh 停止实例后再安装")
    if existing and existing["platform"] != target:
        raise common.InstallerError("已安装的平台与目标平台不一致")
    if not 1 <= args.port <= 65535:
        raise common.InstallerError("端口必须在 1..65535 之间")
    extras = [item.strip() for item in args.extras.split(",") if item.strip()]
    metadata = common.project_metadata(source)
    workspace_engine.dependency_list(metadata, extras)
    python = find_python(args.python)
    _check_ffmpeg()
    manifest = {
        "owner": OWNER,
        "schema_version": SCHEMA_VERSION,
        "install_root": str(root),
        "root": str(root),
        "platform": target,
        "architecture": platform.machine(),
        "version": metadata["version"],
        "app": common.APP_NAME,
        "app_dir": str(root / "app"),
        "venv_dir": str(root / "venv"),
        "data_dir": str(root / "data"),
        "config_dir": str(root / "config"),
        "port": args.port,
        "env": args.env,
        "extras": extras,
        "owned_paths": list((*MANAGED_DIRECTORIES, *USER_DIRECTORIES, *LAUNCHER_FILES)),
        "shortcuts": list(existing.get("shortcuts", [])),
        "status": "installing",
        "installed_at": common.utc_now(),
    }
    if args.dry_run:
        common.log(
            json.dumps(
                {"action": "install", "installation": manifest, "source": str(source)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return manifest
    root.mkdir(parents=True, exist_ok=True)
    with operation_lock(root):
        current = read_installation(root, required=False)
        if current:
            if current["platform"] != target:
                raise common.InstallerError("已安装的平台与目标平台不一致")
            manifest["shortcuts"] = list(current.get("shortcuts", []))
        elif {item.name for item in root.iterdir()} - {"run"} or {
            item.name for item in (root / "run").iterdir()
        } - {"start.lock"}:
            raise common.InstallerError("安装目录在执行期间出现未知文件，拒绝覆盖")
        if (root / "run" / "instance.json").exists():
            raise common.InstallerError("实例在安装前已启动，请先停止实例")
        _check_children(root)
        common.write_manifest(root, manifest)
        for name in (*USER_DIRECTORIES, "run"):
            (root / name).mkdir(exist_ok=True)
        env_file = root / "config" / ".env"
        if not env_file.exists() and not env_file.is_symlink():
            common.write_text(env_file, "# 此文件保存本机配置；不会随应用更新覆盖。\n")
            env_file.chmod(0o600)
        venv = root / "venv"
        if not (venv / "bin" / "python").is_file():
            common.run([python, "-m", "venv", str(venv)])
        venv_python = venv / "bin" / "python"
        common.copy_payload(source, root / "app")
        workspace_engine.install_workspace(venv_python, root / "app", extras, dry_run=False)
        workspace_engine.verify_packages(venv_python)
        for action, filename in (
            ("start", "start-studio.sh"),
            ("stop", "stop-studio.sh"),
            ("status", "studio-status.sh"),
        ):
            _executable(root / filename, launcher_script(root, action, args.port))
        _executable(root / "uninstall-studio.sh", _uninstall_script(root))
        if target == "macos":
            for action, name in (("start", "Start"), ("stop", "Stop")):
                _executable(root / f"{name} AI Film Studio.command", launcher_script(root, action, args.port))
        (root / "installer").mkdir(exist_ok=True)
        for name in ("posix.py", "workspace.py", "common.py"):
            shutil.copy2(Path(__file__).with_name(name), root / "installer" / name)
        if not args.no_shortcuts:
            directory = (
                Path(args.shortcut_dir)
                if args.shortcut_dir
                else (
                    Path.home() / "Desktop"
                    if target == "macos"
                    else Path.home() / ".local/share/applications"
                )
            )
            recorded = _shortcut(root, target, directory, manifest["shortcuts"])
            if recorded:
                manifest["shortcuts"] = [
                    item for item in manifest["shortcuts"] if item.get("path") != recorded["path"]
                ]
                manifest["shortcuts"].append(recorded)
        manifest["status"] = "installed"
        common.write_manifest(root, manifest)
        common.log(f"安装完成：{root}\n启动：{root / 'start-studio.sh'}")
        return manifest


def _remove_shortcuts(manifest: dict, *, dry_run: bool) -> None:
    name, content = _shortcut_content(Path(manifest["install_root"]), manifest["platform"])
    expected_digest = hashlib.sha256(content.encode()).hexdigest()
    for record in manifest.get("shortcuts", []):
        if not isinstance(record, dict) or not record.get("path") or not record.get("sha256"):
            raise common.InstallerError("快捷方式记录格式不正确，拒绝删除")
        path = Path(record["path"])
        if path.name != name or record["sha256"] != expected_digest:
            raise common.InstallerError("快捷方式记录不属于当前安装目录，拒绝删除")
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest == record["sha256"] and not dry_run:
            path.unlink()


def uninstall(args: argparse.Namespace) -> dict:
    root = _root(args.dir or default_root(current_platform(args.platform)))
    if not root.exists():
        common.log(f"未发现安装目录，无需卸载：{root}")
        return {"status": "not_installed", "install_root": str(root)}
    manifest = read_installation(root)
    if args.dry_run:
        common.log(
            json.dumps(
                {"action": "uninstall", "install_root": str(root), "purge": args.purge}, ensure_ascii=False
            )
        )
        return manifest
    python = root / "venv" / "bin" / "python"
    if python.is_file() and (
        manifest.get("status") == "installed" or (root / "run" / "instance.json").exists()
    ):
        common.run([str(python), "-m", "studio_api.launcher", "stop", "--install-root", str(root)])
    elif (root / "run" / "instance.json").exists():
        raise common.InstallerError("运行记录存在但解释器缺失，无法验证实例已停止；拒绝删除")
    if (root / "run" / "instance.json").exists():
        raise common.InstallerError("停止操作后运行记录仍存在，拒绝删除运行环境")
    with operation_lock(root):
        manifest = read_installation(root)
        if (root / "run" / "instance.json").exists():
            raise common.InstallerError("实例在卸载前已启动，拒绝删除运行环境")
        manifest["status"] = "uninstalling"
        common.write_manifest(root, manifest)
        _remove_shortcuts(manifest, dry_run=False)
        for name in MANAGED_DIRECTORIES:
            if name == "run":
                continue
            path = root / name
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
        for name in LAUNCHER_FILES:
            (root / name).unlink(missing_ok=True)
        if args.purge:
            for name in USER_DIRECTORIES:
                path = root / name
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            (root / common.MANIFEST_NAME).unlink()
            shutil.rmtree(root / "run")
            if not any(root.iterdir()):
                root.rmdir()
        else:
            manifest.update(status="uninstalled", shortcuts=[])
            common.write_manifest(root, manifest)
        common.log("卸载完成；用户数据已" + ("按 --purge 删除" if args.purge else "保留"))
        return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Film Studio macOS/Linux 用户级安装器")
    commands = parser.add_subparsers(dest="action", required=True)
    install_parser = commands.add_parser("install", help="安装到独立用户目录")
    uninstall_parser = commands.add_parser("uninstall", help="卸载应用，默认保留用户数据")
    for command in (install_parser, uninstall_parser):
        command.add_argument("--dir", default="", help="独立安装目录")
        command.add_argument("--platform", choices=("macos", "linux"), default="")
        command.add_argument("--dry-run", action="store_true")
    install_parser.add_argument("--from", dest="source", default="")
    install_parser.add_argument("--python", default="")
    install_parser.add_argument("--port", type=int, default=8010)
    install_parser.add_argument("--extras", default="")
    install_parser.add_argument("--env", choices=("development", "production", "test"), default="development")
    install_parser.add_argument("--no-shortcuts", action="store_true")
    install_parser.add_argument("--shortcut-dir", default="")
    uninstall_parser.add_argument(
        "--purge", action="store_true", help="明确删除本安装目录内的用户数据和本机配置"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    common.ensure_utf8_console()
    try:
        args = parse_args(argv)
        if args.action == "install":
            install(args)
        else:
            uninstall(args)
        return 0
    except (common.InstallerError, OSError, subprocess.SubprocessError) as error:
        common.log(f"安装器错误：{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
