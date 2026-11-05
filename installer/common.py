"""Shared helpers for the Windows one-click installer / uninstaller.

The installer is compiled with PyInstaller into ``install.exe`` (and
``uninstall.exe``).  It only uses the standard library: the frozen interpreter
must be able to run on a machine that has no Python at all, which is exactly the
case it is meant to fix.
"""

from __future__ import annotations

import ctypes
import glob
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

APP_NAME = "AI Film Studio"
APP_SLUG = "AIFilmStudio"
MANIFEST_NAME = "install.json"
LAUNCHER_NAME = "start-studio.cmd"
ICON_NAME = "studio.ico"
UNINSTALL_REGISTRY = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_SLUG}"

MIN_PYTHON = (3, 11)
PYTHON_VERSION = "3.12.10"
PYTHON_DOWNLOAD = "https://www.python.org/ftp/python/{version}/python-{version}-{arch}.exe"

# Never copied into the install directory: build output, local state, VCS data.
SKIP_NAMES = {
    "__pycache__",
    ".venv",
    "venv",
    "data",
    "dist",
    "build",
    "installer",
    ".git",
    ".github",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "node_modules",
    "backend",  # 仓库级旧入口链接与测试不参与安装；已安装 app 兼容包由 studio-api 提供。
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".db", ".sqlite3", ".egg-info"}

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class InstallerError(RuntimeError):
    """Raised for any condition the user can act on."""


# --------------------------------------------------------------------- basics
def ensure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # pragma: no cover - best effort only
            pass


def log(message: str = "") -> None:
    print(message, flush=True)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def pause_if_needed(enabled: bool) -> None:
    """Keep the window open when the exe was started from Explorer."""
    if not enabled or not is_frozen():
        return
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close this window...")
    except Exception:  # pragma: no cover
        pass


def resource_root() -> Path | None:
    """Directory PyInstaller unpacked our bundled resources into."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def default_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_SLUG


def payload_root(explicit: str | None = None) -> Path:
    """Application source that will be copied into the install directory."""
    if explicit:
        path = Path(explicit).expanduser().resolve()
        validate_payload(path)
        return path

    bundled = resource_root()
    if bundled is not None:
        candidate = bundled / "payload"
        if (candidate / "apps" / "studio_api" / "src" / "studio_api" / "main.py").is_file():
            validate_payload(candidate)
            return candidate

    # Running from a checkout: installer/ lives directly below the repo root.
    checkout = Path(__file__).resolve().parents[1]
    if (checkout / "apps" / "studio_api" / "src" / "studio_api" / "main.py").is_file():
        validate_payload(checkout)
        return checkout
    raise InstallerError(
        "Cannot find the application files. Run install.exe from the release folder "
        "or pass --from <path-to-source>."
    )


def validate_payload(path: Path) -> list[Path]:
    """验证完整 workspace 与共享资源；不执行安装或解析本地凭据。"""
    required = (
        "pyproject.toml",
        "uv.lock",
        "apps/studio_api/src/studio_api/main.py",
        "config/app.yaml",
        "web/index.html",
        "samples/novel_sample.txt",
        "scripts/sync_studio_resources.py",
    )
    missing = [name for name in required if not (path / name).is_file()]
    if missing:
        raise InstallerError(f"Workspace payload is incomplete: {', '.join(missing)}")
    workspace = read_toml(path / "pyproject.toml").get("tool", {}).get("uv", {}).get("workspace", {})
    patterns = workspace.get("members", [])
    if not patterns:
        raise InstallerError("Workspace payload has no declared members")
    excluded = {
        candidate.resolve() for pattern in workspace.get("exclude", []) for candidate in path.glob(pattern)
    }
    members = sorted(
        {
            candidate
            for pattern in patterns
            for candidate in path.glob(pattern)
            if candidate.is_dir() and candidate.resolve() not in excluded
        }
    )
    if not members:
        raise InstallerError("Workspace payload member patterns match no projects")
    for member in members:
        if not (member / "pyproject.toml").is_file() or not (member / "src").is_dir():
            raise InstallerError(f"Workspace member is incomplete: {member.relative_to(path)}")
        name = read_toml(member / "pyproject.toml").get("project", {}).get("name", "")
        module_name = name.replace("-", "_")
        if not name or not (member / "src" / module_name / "__init__.py").is_file():
            raise InstallerError(f"Workspace member source is missing: {member.relative_to(path)}")
    return members


def asset(name: str) -> Path | None:
    bundled = resource_root()
    if bundled is not None and (bundled / "assets" / name).is_file():
        return bundled / "assets" / name
    local = Path(__file__).resolve().parent / "assets" / name
    return local if local.is_file() else None


def read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return {}
    except tomllib.TOMLDecodeError as exc:
        raise InstallerError(f"Cannot parse {path}: {exc}") from exc


def project_metadata(payload: Path) -> dict:
    data = read_toml(payload / "pyproject.toml")
    project = data.get("project", {}) if isinstance(data, dict) else {}
    return {
        "name": str(project.get("name") or "ai-film-studio"),
        "version": str(project.get("version") or "0.0.0"),
        "dependencies": [str(item) for item in project.get("dependencies", []) or []],
        "extras": {
            str(key): [str(item) for item in value or []]
            for key, value in (project.get("optional-dependencies") or {}).items()
        },
    }


# -------------------------------------------------------------------- process
def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
    echo: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a command and stream its output so long pip installs stay visible."""
    if echo:
        log(f"  $ {' '.join(str(part) for part in command)}")
    process = subprocess.run(  # noqa: S603 - arguments are constructed by us
        [str(part) for part in command],
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if echo:
        for line in (process.stdout or "").splitlines():
            if line.strip():
                log(f"    {line}")
        for line in (process.stderr or "").splitlines():
            if line.strip():
                log(f"    {line}")
    if check and process.returncode != 0:
        tail = "\n".join(((process.stdout or "") + (process.stderr or "")).splitlines()[-15:])
        raise InstallerError(
            f"Command failed with exit code {process.returncode}:\n"
            f"  {' '.join(str(part) for part in command)}\n{tail}"
        )
    return process


def _probe_python(launcher: list[str]) -> tuple[str, tuple[int, int]] | None:
    """Ask a candidate launcher for its interpreter path and version."""
    probe = list(launcher) + [
        "-c",
        "import sys;print(sys.executable);print('%d.%d' % sys.version_info[:2])",
    ]
    try:
        result = subprocess.run(  # noqa: S603
            probe,
            capture_output=True,
            text=True,
            timeout=40,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    try:
        major, minor = (int(part) for part in lines[1].split(".", 1))
    except ValueError:
        return None
    if Path(lines[0]).is_file():
        return lines[0], (major, minor)
    return None


def _registry_pythons() -> list[str]:
    """Interpreters registered under ``Software\\Python\\PythonCore`` (newest first)."""
    if os.name != "nt":
        return []
    import winreg

    found: list[tuple[tuple[int, ...], str]] = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            base = winreg.OpenKey(hive, r"Software\Python\PythonCore")
        except OSError:
            continue
        with base:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(base, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(base, rf"{name}\InstallPath") as key:
                        value = winreg.QueryValueEx(key, "")[0]
                except OSError:
                    continue
                exe = Path(str(value)) / "python.exe"
                if not exe.is_file():
                    continue
                try:
                    version = tuple(int(part) for part in name.split(".")[:2])
                except ValueError:
                    version = (0, 0)
                found.append((version, str(exe)))
    found.sort(reverse=True)
    return [exe for _version, exe in found]


def find_python(root: Path, explicit: str | None = None) -> tuple[str, tuple[int, int]] | None:
    """Locate a usable CPython >= 3.11, preferring a private copy we installed."""
    candidates: list[list[str]] = []
    if explicit:
        candidates.append([explicit])
    private = root / "python" / "python.exe"
    if private.is_file():
        candidates.append([str(private)])
    candidates.extend(
        [
            ["py", "-3.12"],
            ["py", "-3.11"],
            ["py", "-3"],
            ["python"],
            ["python3"],
        ]
    )
    for launcher in candidates:
        found = _probe_python(launcher)
        if found and found[1] >= MIN_PYTHON:
            return found

    # Registry entries catch interpreters that are neither on PATH nor under
    # %LOCALAPPDATA%\Programs\Python (a per-machine install, a custom folder, ...).
    for exe in _registry_pythons():
        found = _probe_python([exe])
        if found and found[1] >= MIN_PYTHON:
            return found

    patterns: list[str] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("PROGRAMFILES")
    if local_appdata:
        patterns.append(str(Path(local_appdata) / "Programs" / "Python" / "Python3*" / "python.exe"))
    if program_files:
        patterns.append(str(Path(program_files) / "Python3*" / "python.exe"))
    patterns.append(r"C:\Python3*\python.exe")

    for pattern in patterns:
        for match in sorted(glob.glob(pattern), reverse=True):
            found = _probe_python([match])
            if found and found[1] >= MIN_PYTHON:
                return found
    return None


# ------------------------------------------------------------------- download
def download(url: str, destination: Path, *, label: str = "file") -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    log(f"  downloading {label}: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "ai-film-studio-installer"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            last_report = 0.0
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last_report > 1.5:
                        last_report = now
                        if total:
                            log(f"    {done / 1048576:.1f} / {total / 1048576:.1f} MB")
                        else:
                            log(f"    {done / 1048576:.1f} MB")
    except (urllib.error.URLError, OSError) as exc:
        destination.unlink(missing_ok=True)
        raise InstallerError(f"Download failed for {url}: {exc}") from exc
    return destination


# --------------------------------------------------------------------- files
def _ignore(_directory: str, names: list[str]) -> set[str]:
    skipped = set()
    for name in names:
        if name in SKIP_NAMES or name.endswith(".egg-info"):
            skipped.add(name)
        elif name == ".env" or name.startswith(".env."):
            skipped.add(name)
        elif Path(name).suffix.lower() in SKIP_SUFFIXES:
            skipped.add(name)
    return skipped


def copy_payload(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=_ignore)


def write_text(path: Path, content: str) -> None:
    """Write text verbatim: callers pass their own line endings (``.cmd`` needs CRLF).

    ``.cmd`` files are parsed by cmd.exe in the ANSI code page and must not start
    with a BOM - a BOM turns ``@echo off`` into an unknown command - so they are
    written with ``mbcs`` (cp936/cp1252/...) instead of UTF-8.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".cmd" and os.name == "nt":
        try:
            path.write_bytes(content.encode("mbcs"))
            return
        except (UnicodeEncodeError, LookupError):
            pass  # fall back to UTF-8 for paths the ANSI code page cannot hold
    # newline="" keeps \n untranslated, otherwise CRLF would become CRCRLF
    path.write_text(content, encoding="utf-8", newline="")


# ---------------------------------------------------------------------- ports
def port_available(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # SO_REUSEADDR on Windows lets you bind an already-used port, so ask for
        # exclusive use there; POSIX needs REUSEADDR to skip TIME_WAIT noise.
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(preferred: int) -> int:
    for port in range(preferred, preferred + 40):
        if port_available(port):
            return port
    raise InstallerError(f"No free TCP port between {preferred} and {preferred + 39}")


# ------------------------------------------------------------------ shortcuts
def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def powershell(script: str) -> None:
    run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        echo=False,
    )


def create_shortcut(
    link: Path,
    target: Path,
    *,
    arguments: str = "",
    working_dir: Path | None = None,
    icon: Path | None = None,
    description: str = APP_NAME,
) -> Path:
    link.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{_ps_quote(str(link))}'); "
        f"$s.TargetPath = '{_ps_quote(str(target))}'; "
        f"$s.Arguments = '{_ps_quote(arguments)}'; "
        f"$s.WorkingDirectory = '{_ps_quote(str(working_dir or target.parent))}'; "
        f"$s.Description = '{_ps_quote(description)}'; "
    )
    if icon and icon.is_file():
        script += f"$s.IconLocation = '{_ps_quote(str(icon))}'; "
    script += "$s.Save()"
    powershell(script)
    return link


def desktop_dir() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"


def start_menu_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def remove_path(path: Path) -> None:
    """Delete a file or directory tree, tolerating locked/in-use files."""
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink(missing_ok=True)
    except OSError:
        pass


def delete_self_on_reboot(path: Path) -> None:
    """A running exe cannot delete itself; schedule it for the next boot."""
    try:
        ctypes.windll.kernel32.MoveFileExW(str(path), None, 0x4)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - best effort only
        pass


# ------------------------------------------------------------------- manifest
def manifest_path(root: Path) -> Path:
    return root / MANIFEST_NAME


def read_manifest(root: Path) -> dict:
    path = manifest_path(root)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_manifest(root: Path, data: dict) -> Path:
    path = manifest_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# ------------------------------------------------------------------- registry
def register_uninstall(manifest: dict) -> None:
    """Show the app in Settings -> Apps so users can also uninstall from there."""
    import winreg

    root = Path(manifest["root"])
    uninstaller = root / "uninstall.exe"
    values = {
        "DisplayName": APP_NAME,
        "DisplayVersion": str(manifest.get("version", "")),
        "Publisher": "AI Film Studio",
        "InstallLocation": str(root),
        "UninstallString": f'"{uninstaller}"',
        "QuietUninstallString": f'"{uninstaller}" --yes',
        "DisplayIcon": str(root / ICON_NAME) if (root / ICON_NAME).is_file() else str(uninstaller),
        "NoModify": 1,
        "NoRepair": 1,
        "EstimatedSize": max(1, int(_tree_size(root) / 1024)),
    }
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_REGISTRY, 0, winreg.KEY_WRITE) as key:
        for name, value in values.items():
            if isinstance(value, int):
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
            else:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def unregister_uninstall() -> None:
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REGISTRY)
    except FileNotFoundError:
        pass


def _tree_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


# ------------------------------------------------------------------ processes
def processes_under(root: Path, *, exclude_self: bool = True) -> list[int]:
    """PIDs of processes whose executable lives inside the install directory.

    ``uninstall.exe`` normally sits inside that directory, so its own PID (and the
    onefile bootloader parent, which uses the same executable) must be filtered out -
    otherwise the uninstaller kills itself in the middle of the removal.
    """
    if os.name != "nt":
        return []
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.ExecutablePath -and "
        f"$_.ExecutablePath.StartsWith('{_ps_quote(str(root))}', 'OrdinalIgnoreCase') }} | "
        "Select-Object -ExpandProperty ProcessId"
    )
    result = run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        echo=False,
    )
    pids: list[int] = []
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    if exclude_self:
        own = {os.getpid(), os.getppid()}
        pids = [pid for pid in pids if pid not in own]
    return pids


def kill_pids(pids: list[int]) -> None:
    for pid in pids:
        run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, echo=False)


# --------------------------------------------------------------------- system
def ffmpeg_available() -> bool:
    if shutil.which("ffmpeg"):
        return True
    return any(
        Path(candidate).is_file() for candidate in ("C:/ffmpeg/bin/ffmpeg.exe", "D:/ffmpeg/bin/ffmpeg.exe")
    )


def winget_available() -> bool:
    return shutil.which("winget") is not None


def machine_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return "amd64"


def python_installer_url() -> str:
    return PYTHON_DOWNLOAD.format(version=PYTHON_VERSION, arch=machine_arch())


# ------------------------------------------------------------------- selftest
def self_test(*, expect_payload: bool) -> int:
    """Print diagnostics for ``install.exe --selftest`` (used by the build)."""
    log(f"{APP_NAME} self test")
    ok = True
    log(f"  python   : {sys.version.split()[0]} ({sys.executable})")
    log(f"  frozen   : {is_frozen()}")
    log(f"  arch     : {machine_arch()}")
    try:
        import ssl

        log(f"  ssl      : {ssl.OPENSSL_VERSION}")
    except Exception as exc:  # missing OpenSSL DLLs => downloads cannot work
        ok = False
        log(f"  ssl      : BROKEN ({exc})")
    if expect_payload:
        try:
            log(f"  payload  : {payload_root(None)}")
        except InstallerError as exc:
            ok = False
            log(f"  payload  : MISSING ({exc})")
    log(f"  ffmpeg   : {'found on PATH' if ffmpeg_available() else 'not found'}")
    log(f"  target   : {default_root()}")
    log("self test passed." if ok else "self test FAILED.")
    return 0 if ok else 1
