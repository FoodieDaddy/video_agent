"""分别构建 Windows、macOS 与 Linux 的可审查发布归档。

默认对当前 Git HEAD 做快照，工作区尚未提交的代码、配置和前端改动不会混入发布。
显式 --source-root 用于 CI 已检出的源码或调用方准备的隔离源码树。
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "installer"))

import common  # noqa: E402

PLATFORMS = ("macos", "linux", "windows")
PAYLOAD_ROOTS = {"apps", "packages", "config", "web", "samples", "scripts", "pyproject.toml", "uv.lock"}
INSTALLER_FILES = ("common.py", "workspace.py", "posix.py", "install.py", "uninstall.py")
REQUIRED_MEMBERS = {
    "studio-api",
    "studio-projects",
    "studio-story",
    "studio-characters",
    "studio-scenes",
    "studio-production",
    "studio-reviews",
    "studio-workflow",
    "studio-assets",
    "studio-configuration",
    "studio-ai-runtime",
    "studio-platform",
    "studio-contracts",
}
PE_ARCHITECTURES = {0x014C: "x86", 0x8664: "x86_64", 0xAA64: "arm64"}
WINDOWS_INSTALLER_MANIFEST = "windows-installers.json"
WINDOWS_INSTALLER_SOURCE_FILES = (
    "installer/common.py",
    "installer/workspace.py",
    "installer/install.py",
    "installer/uninstall.py",
    "scripts/build_installers.py",
    "scripts/build_releases.py",
    "scripts/sync_studio_resources.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_relative(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or any(":" in p for p in path.parts)
    ):
        raise common.InstallerError(f"发布路径不安全：{name}")
    return path


@contextmanager
def source_snapshot(
    explicit: Path | None = None,
    *,
    git_root: Path | None = None,
) -> Iterator[tuple[Path, dict]]:
    """Git 工作区默认发布已提交快照；显式目录由调用方提供来源责任。"""
    if explicit is not None:
        root = explicit.expanduser().resolve()
        if not root.is_dir():
            raise common.InstallerError(f"源码目录不存在：{root}")
        yield root, {"kind": "explicit-source-tree", "commit": None}
        return
    repository = git_root or REPO_ROOT
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        archive = subprocess.run(
            ["git", "archive", "--format=tar", commit],
            cwd=repository,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise common.InstallerError("无法取得已提交源码，请使用 --source-root 指定隔离源码目录") from exc
    with tempfile.TemporaryDirectory(prefix="studio-release-source-") as temp:
        root = Path(temp)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            # 不解包符号链接。旧 backend 链接不属于发布载荷；其他链接也不应变成文件泄露入口。
            for member in tar.getmembers():
                relative = _safe_relative(member.name)
                if member.issym() or member.islnk():
                    if relative.parts[0] == "backend":
                        continue
                    raise common.InstallerError(f"发布源码不接受链接：{member.name}")
                if not member.isdir() and not member.isfile():
                    raise common.InstallerError(f"发布源码不接受特殊文件：{member.name}")
            members = [m for m in tar.getmembers() if not m.issym() and not m.islnk()]
            tar.extractall(root, members=members, filter="data")
        yield root, {"kind": "git-archive", "commit": commit}


def _reject_payload_links(source: Path) -> None:
    """复制前拒绝可见源码链接；跳过原复制规则已排除的本地状态。"""
    for name in PAYLOAD_ROOTS:
        base = source / name
        if not base.exists() and not base.is_symlink():
            continue
        for candidate in (base, *base.rglob("*")):
            relative = candidate.relative_to(source)
            if any(
                part in common.SKIP_NAMES
                or part == ".env"
                or part.startswith(".env.")
                or part.endswith(".egg-info")
                or Path(part).suffix.lower() in common.SKIP_SUFFIXES
                for part in relative.parts
            ):
                continue
            _safe_relative(relative.as_posix())
            if candidate.is_symlink():
                raise common.InstallerError(f"发布载荷不接受链接：{relative}")


def _copy_installer(source: Path, destination: Path) -> None:
    destination.mkdir()
    for name in INSTALLER_FILES:
        path = source / "installer" / name
        if not path.is_file() or path.is_symlink():
            raise common.InstallerError(f"安装入口缺失：installer/{name}；请先提交本批安装代码")
        (destination / name).write_bytes(path.read_bytes())


def stage_payload(source: Path, target: Path) -> list[dict[str, str]]:
    _reject_payload_links(source)
    common.copy_payload(source, target)
    for path in target.iterdir():
        if path.name not in PAYLOAD_ROOTS:
            if path.is_dir():
                import shutil

                shutil.rmtree(path)
            else:
                path.unlink()
    members = common.validate_payload(target)
    descriptions = [
        {
            "name": common.read_toml(member / "pyproject.toml")["project"]["name"],
            "path": member.relative_to(target).as_posix(),
        }
        for member in members
    ]
    missing = REQUIRED_MEMBERS - {item["name"] for item in descriptions}
    if missing:
        raise common.InstallerError(f"发布载荷缺少成员：{', '.join(sorted(missing))}")
    # 同步复制后的资源，不执行调用方目录里的任意同步代码。
    from scripts.sync_studio_resources import sync_resources

    sync_resources(target)
    return sorted(descriptions, key=lambda item: item["name"])


def pe_architecture(path: Path) -> str:
    """验证 DOS/PE 标识并读取架构；这不代表已在 Windows 执行自检。"""
    if not path.is_file() or path.is_symlink():
        raise common.InstallerError(f"缺少原生 Windows 产物：{path.name}")
    with path.open("rb") as handle:
        header = handle.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise common.InstallerError(f"无效 Windows 可执行文件：{path.name}")
        offset = struct.unpack_from("<I", header, 0x3C)[0]
        if offset < 64 or offset + 6 > path.stat().st_size:
            raise common.InstallerError(f"无效 PE 头位置：{path.name}")
        handle.seek(offset)
        pe = handle.read(6)
        if pe[:4] != b"PE\0\0":
            raise common.InstallerError(f"无效 PE 标识：{path.name}")
        machine = struct.unpack_from("<H", pe, 4)[0]
    try:
        return PE_ARCHITECTURES[machine]
    except KeyError as exc:
        raise common.InstallerError(f"不支持的 Windows 产物架构：{machine:#x}") from exc


def windows_source_fingerprint(source: Path) -> dict:
    """取得 Windows 引导器实际依赖的源码、锁文件和版本；不执行构建。"""
    hashes = {}
    for relative in WINDOWS_INSTALLER_SOURCE_FILES:
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise common.InstallerError(f"Windows 构建源码缺失：{relative}")
        hashes[relative] = sha256(path)
    lock = source / "uv.lock"
    if not lock.is_file() or lock.is_symlink():
        raise common.InstallerError("Windows 构建缺少唯一 uv.lock")
    # 归档源码树没有 Git 元数据时保持 None；不能猜测其历史提交。
    commit = None
    if (source / ".git").exists():
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=source,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise common.InstallerError("无法读取 Windows 构建来源提交") from exc
    return {
        "version": common.project_metadata(source)["version"],
        "source_commit": commit,
        "uv_lock_sha256": sha256(lock),
        "installer_source_sha256": hashes,
    }


def committed_windows_source_fingerprint(source: Path) -> dict:
    """编译必要输入必须与 HEAD 字节一致；不拒绝无关文档或前端改动。"""
    fingerprint = windows_source_fingerprint(source)
    if fingerprint["source_commit"] is None:
        raise common.InstallerError("原生 Windows 构建需要 Git HEAD 来源；请从已提交的源码检出构建")
    for relative in (*WINDOWS_INSTALLER_SOURCE_FILES, "uv.lock", "pyproject.toml"):
        try:
            committed = subprocess.run(
                ["git", "show", f"HEAD:{relative}"],
                cwd=source,
                check=True,
                capture_output=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise common.InstallerError(f"HEAD 缺少 Windows 构建输入：{relative}") from exc
        if (source / relative).read_bytes() != committed:
            raise common.InstallerError(
                f"Windows 构建输入与 HEAD 字节不一致：{relative}；请先提交安装代码并使用一致换行检出"
            )
    return fingerprint


def payload_source_manifest(payload: Path, provenance: dict) -> dict:
    """记录实际内嵌载荷的来源及完整文件指纹，不包含绝对路径。"""
    files = {path.relative_to(payload).as_posix(): sha256(path) for path in _files(payload)}
    serialized = json.dumps(files, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "kind": provenance["kind"],
        "commit": provenance.get("commit"),
        "file_count": len(files),
        "files_sha256": files,
        "content_sha256": hashlib.sha256(serialized).hexdigest(),
    }


def write_windows_installers_manifest(
    source: Path,
    output_dir: Path,
    *,
    payload_source: dict,
    expected_source: dict | None = None,
) -> Path:
    """由完成两份 EXE 自检的 Windows 构建流程调用，绑定输入与产物哈希。"""
    fingerprint = windows_source_fingerprint(source)
    if expected_source is not None and fingerprint != expected_source:
        raise common.InstallerError("Windows 构建期间源码或锁文件发生变化，请重新构建")
    executables = {}
    for action in ("install", "uninstall"):
        path = output_dir / f"{action}.exe"
        architecture = pe_architecture(path)
        executables[path.name] = {"sha256": sha256(path), "architecture": architecture}
    architectures = {item["architecture"] for item in executables.values()}
    if len(architectures) != 1:
        raise common.InstallerError("Windows 安装与卸载产物架构不一致")
    manifest = {
        "schema_version": 1,
        **fingerprint,
        "architecture": architectures.pop(),
        "executables": executables,
        "payload_source": payload_source,
    }
    target = output_dir / WINDOWS_INSTALLER_MANIFEST
    temporary = target.with_suffix(".json.partial")
    try:
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def validate_windows_installers_manifest(
    source: Path,
    executable_dir: Path,
    provenance: dict,
    architecture: str,
) -> dict:
    """原生 EXE 必须与正在发布的安装源码、版本、锁文件和提交一致。"""
    sidecar = executable_dir / WINDOWS_INSTALLER_MANIFEST
    if not sidecar.is_file() or sidecar.is_symlink():
        raise common.InstallerError(
            f"缺少 Windows 来源清单 {WINDOWS_INSTALLER_MANIFEST}；请重新构建原生 EXE，或使用 --source-only"
        )
    try:
        manifest = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise common.InstallerError("Windows 来源清单不可读取或不是有效 JSON") from exc
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 1
    ):
        raise common.InstallerError("Windows 来源清单版本不受支持")
    current = windows_source_fingerprint(source)
    for key in ("version", "uv_lock_sha256", "installer_source_sha256"):
        if manifest.get(key) != current[key]:
            raise common.InstallerError(f"Windows EXE 与当前发布载荷来源不一致：{key}")
    if provenance.get("kind") == "git-archive" and manifest.get("source_commit") != provenance["commit"]:
        raise common.InstallerError("Windows EXE 的来源提交与发布快照不一致")
    if manifest.get("architecture") != architecture:
        raise common.InstallerError("Windows 来源清单架构与 EXE 不一致")
    payload_source = manifest.get("payload_source")
    if not isinstance(payload_source, dict) or not {
        "kind",
        "commit",
        "file_count",
        "files_sha256",
        "content_sha256",
    } <= set(payload_source):
        raise common.InstallerError("Windows 来源清单缺少完整内嵌载荷指纹，请重新构建")
    if provenance.get("kind") == "git-archive" and (
        payload_source.get("kind") != "git-archive" or payload_source.get("commit") != provenance["commit"]
    ):
        raise common.InstallerError("Windows EXE 的内嵌载荷来源与发布快照不一致")
    executables = manifest.get("executables")
    if not isinstance(executables, dict) or set(executables) != {"install.exe", "uninstall.exe"}:
        raise common.InstallerError("Windows 来源清单必须覆盖安装与卸载两份 EXE")
    for filename, expected in executables.items():
        path = executable_dir / filename
        if not isinstance(expected, dict) or expected != {
            "sha256": sha256(path),
            "architecture": architecture,
        }:
            raise common.InstallerError(f"Windows EXE 哈希或架构与来源清单不一致：{filename}")
    return manifest


def validate_embedded_windows_payload(manifest: dict, payload: Path) -> None:
    """外部发布载荷须与构建时实际内嵌的文件逐项相同。"""
    expected = manifest["payload_source"]
    actual = payload_source_manifest(payload, {"kind": expected["kind"], "commit": expected["commit"]})
    if actual != expected:
        raise common.InstallerError("Windows EXE 的内嵌载荷文件与当前发布载荷不一致")


def posix_script(platform_name: str, action: str) -> str:
    extra = f' --platform {platform_name} --from "$RELEASE_DIR/payload"' if action == "install" else ""
    return f"""#!/bin/sh
set -eu
RELEASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for candidate in "${{STUDIO_PYTHON:-}}" python3.12 python3.11 python3; do
    [ -n "$candidate" ] || continue
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
        exec "$candidate" "$RELEASE_DIR/installer/posix.py" {action}{extra} "$@"
    fi
done
printf '%s\n' '需要 Python 3.11 或更新版本；可用 STUDIO_PYTHON 指定解释器。' >&2
exit 1
"""


def windows_script(native: bool, action: str) -> str:
    source_args = ' --from "%~dp0payload"' if action == "install" else ""
    if native:
        return f'@echo off\r\nsetlocal\r\n"%~dp0{action}.exe"{source_args} %*\r\nexit /b %ERRORLEVEL%\r\n'
    return f'''@echo off
setlocal
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>nul
    if not errorlevel 1 (
        py -3 "%~dp0installer\\{action}.py"{source_args} %*
        exit /b
    )
)
python -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>nul
if errorlevel 1 (
    echo Python 3.11 or newer is required for this source-bootstrap archive. 1>&2
    exit /b 1
)
python "%~dp0installer\\{action}.py"{source_args} %*
exit /b %ERRORLEVEL%
'''.replace("\n", "\r\n")


def _write_entrypoints(root: Path, platform_name: str, native: bool) -> None:
    if platform_name == "windows":
        for action in ("install", "uninstall"):
            (root / f"{action}.cmd").write_bytes(windows_script(native, action).encode("utf-8"))
        return
    for action in ("install", "uninstall"):
        path = root / f"{action}.sh"
        path.write_text(posix_script(platform_name, action), encoding="utf-8")
        path.chmod(0o755)
    if platform_name == "macos":
        command = root / "Install.command"
        command.write_text(
            '#!/bin/sh\nset -eu\nRELEASE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$RELEASE_DIR/install.sh" "$@"\n',
            encoding="utf-8",
        )
        command.chmod(0o755)


def _files(root: Path) -> list[Path]:
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()), key=lambda p: p.relative_to(root).as_posix()
    )
    for path in files:
        _safe_relative(path.relative_to(root).as_posix())
        if path.is_symlink():
            raise common.InstallerError(f"发布文件不能是链接：{path}")
    return files


def write_archive(root: Path, target: Path, platform_name: str) -> None:
    files = _files(root)
    if platform_name == "windows":
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                name = f"{root.name}/{path.relative_to(root).as_posix()}"
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | (0o755 if os.access(path, os.X_OK) else 0o644)) << 16
                archive.writestr(info, path.read_bytes())
        return
    with target.open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for path in files:
                info = tarfile.TarInfo(f"{root.name}/{path.relative_to(root).as_posix()}")
                info.size = path.stat().st_size
                info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(path.read_bytes()))


def build_releases(
    *,
    source_root: Path | None = None,
    output_dir: Path | None = None,
    platform_name: str = "all",
    windows_exe_dir: Path | None = None,
    source_only: bool = False,
) -> list[dict]:
    platforms = PLATFORMS if platform_name == "all" else (platform_name,)
    if any(name not in PLATFORMS for name in platforms):
        raise common.InstallerError(f"未知发布平台：{platform_name}")
    native_windows = "windows" in platforms and not source_only
    architecture = "runtime-native"
    if native_windows:
        if windows_exe_dir is None:
            raise common.InstallerError(
                "Windows 原生产物需要 --windows-exe-dir；仅打包源码时显式使用 --source-only"
            )
        architectures = {
            pe_architecture(windows_exe_dir / f"{action}.exe") for action in ("install", "uninstall")
        }
        if len(architectures) != 1:
            raise common.InstallerError("Windows 安装与卸载产物架构不一致")
        architecture = architectures.pop()
    output_dir = (output_dir or REPO_ROOT / "dist" / "releases").expanduser().resolve()
    results = []
    with source_snapshot(source_root) as (source, provenance):
        common.validate_payload(source)
        version = common.project_metadata(source)["version"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version):
            raise common.InstallerError(f"发布版本不适合作为文件名：{version}")
        windows_manifest = (
            validate_windows_installers_manifest(source, windows_exe_dir, provenance, architecture)
            if native_windows
            else None
        )
        with tempfile.TemporaryDirectory(prefix="studio-release-stage-") as temp:
            for name in platforms:
                kind = "native-bootstrap" if name == "windows" and native_windows else "source-bootstrap"
                directory = Path(temp) / f"ai-film-studio-{version}-{name}-{kind}"
                directory.mkdir()
                members = stage_payload(source, directory / "payload")
                _copy_installer(source, directory / "installer")
                if name == "windows" and native_windows:
                    validate_embedded_windows_payload(windows_manifest, directory / "payload")
                    for action in ("install", "uninstall"):
                        copied = directory / f"{action}.exe"
                        copied.write_bytes((windows_exe_dir / f"{action}.exe").read_bytes())
                        if sha256(copied) != windows_manifest["executables"][copied.name]["sha256"]:
                            raise common.InstallerError(f"Windows EXE 在归档复制期间发生变化：{copied.name}")
                    (directory / WINDOWS_INSTALLER_MANIFEST).write_text(
                        json.dumps(windows_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                _write_entrypoints(directory, name, native_windows)
                (directory / "README.txt").write_text(
                    f"AI Film Studio {version} — {name}\n\n"
                    f"发布类型：{kind}。本归档未捆绑应用 Python 运行时或 FFmpeg。\n"
                    + (
                        "macOS/Linux 源码安装需要 Python >=3.11、ffmpeg/ffprobe，以及下载锁定依赖的网络。\n"
                        if name != "windows"
                        else "Windows 原生引导器可下载 Python；source-bootstrap 入口本身要求 Python >=3.11。\n"
                    )
                    + "请先读 release.json 的平台、前置条件与哈希。安装目录含空格可通过带引号的 --dir 指定。\n"
                    + (
                        "运行 ./install.sh [--dir ROOT]；卸载使用 ./uninstall.sh --dir ROOT，默认保留数据和配置。\n"
                        if name != "windows"
                        else "运行 install.cmd [--dir ROOT]；卸载使用 uninstall.cmd --dir ROOT。\n"
                    )
                    + "发布归档构建不代表已通过每个目标操作系统的原生安装或卸载验收。\n",
                    encoding="utf-8",
                )
                manifest = {
                    "schema_version": 1,
                    "name": "ai-film-studio",
                    "version": version,
                    "platform": name,
                    "artifact_kind": kind,
                    "architecture": architecture
                    if name == "windows" and native_windows
                    else "runtime-native; source payload, not a universal binary",
                    "source": provenance,
                    "uv_version": "0.12.9",
                    "uv_lock_sha256": sha256(directory / "payload/uv.lock"),
                    "workspace_member_count": len(members),
                    "workspace_members": members,
                    "prerequisites": {
                        "python": ">=3.11" if kind == "source-bootstrap" else "bootstrap can install CPython",
                        "ffmpeg": "ffmpeg and ffprobe available",
                        "network": "required for pinned uv and locked dependencies",
                    },
                    "native_executables_executed": False,
                    "native_installer_manifest": WINDOWS_INSTALLER_MANIFEST
                    if name == "windows" and native_windows
                    else None,
                    "content_sha256": {
                        path.relative_to(directory).as_posix(): sha256(path) for path in _files(directory)
                    },
                    "content_hash_scope": "all regular files except release.json itself",
                }
                (directory / "release.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                output_dir.mkdir(parents=True, exist_ok=True)
                suffix = ".zip" if name == "windows" else ".tar.gz"
                archive = output_dir / f"{directory.name}{suffix}"
                # 最终路径只在完整归档写成后替换，避免把中断产物当成发布包。
                partial = output_dir / f".{archive.name}.partial"
                try:
                    write_archive(directory, partial, name)
                    partial.replace(archive)
                finally:
                    partial.unlink(missing_ok=True)
                results.append(
                    {
                        "platform": name,
                        "artifact_kind": kind,
                        "path": str(archive),
                        "sha256": sha256(archive),
                        "workspace_member_count": len(members),
                    }
                )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, help="CI 检出或调用方准备的隔离源码；缺省使用 Git HEAD")
    parser.add_argument("--output-dir", type=Path, help="归档输出目录，缺省 dist/releases")
    parser.add_argument("--platform", choices=(*PLATFORMS, "all"), default="all")
    parser.add_argument(
        "--windows-exe-dir", type=Path, help="原生 Windows 构建生成 install.exe/uninstall.exe 的目录"
    )
    parser.add_argument(
        "--source-only", action="store_true", help="Windows 显式仅发布源码引导包，不冒充原生 EXE"
    )
    args = parser.parse_args(argv)
    try:
        results = build_releases(
            source_root=args.source_root,
            output_dir=args.output_dir,
            platform_name=args.platform,
            windows_exe_dir=args.windows_exe_dir,
            source_only=args.source_only,
        )
    except (common.InstallerError, OSError) as exc:
        parser.exit(1, f"发布构建失败：{exc}\n")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
