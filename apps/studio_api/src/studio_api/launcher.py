"""安装实例的启动、状态和停止入口；只管理带自身身份标识的进程。"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
import webbrowser
from pathlib import Path


class LaunchError(RuntimeError):
    pass


def layout(root: Path, *, require_installed: bool = False) -> tuple[Path, dict]:
    root = root.expanduser().resolve()
    manifest = root / "install.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise LaunchError("未找到受管安装清单")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise LaunchError("安装清单格式无效")
    if data.get("owner") != "ai-film-studio-posix-v1" or data.get("schema_version") != 1:
        raise LaunchError("安装清单不属于本启动器")
    if Path(data.get("install_root", "")).resolve() != root:
        raise LaunchError("安装清单路径与当前目录不一致")
    if require_installed and data.get("status") != "installed":
        raise LaunchError("安装尚未完成或正在卸载，拒绝启动")
    if any(char in str(root) for char in ("\n", "\r", "\0")):
        raise LaunchError("安装路径包含无效控制字符")
    for name in ("app", "venv", "data", "config", "run"):
        if (root / name).is_symlink():
            raise LaunchError(f"受管目录不能是符号链接：{name}")
    env_file = root / "config" / ".env"
    if env_file.is_symlink() or not env_file.is_file():
        raise LaunchError("缺少安装实例的 config/.env，拒绝回退读取其他环境配置")
    (root / "run").mkdir(exist_ok=True)
    return root, data


@contextlib.contextmanager
def exclusive_lock(path: Path, timeout: float = 0):
    """持有文件锁到上下文结束；锁文件不保存 PID，崩溃后由系统释放。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise LaunchError("锁文件不能是符号链接")
    handle = path.open("a+b")
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    handle.write(b"0")
                    handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise LaunchError("已有实例或管理操作持有运行锁") from exc
                time.sleep(0.1)
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def global_lock_path() -> Path:
    explicit = os.environ.get("STUDIO_INSTANCE_LOCK_FILE")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "ai-film-studio" / "instance.lock"


def _locked(path: Path) -> bool:
    try:
        with exclusive_lock(path):
            return False
    except LaunchError:
        return True


def process_identity(pid: int) -> tuple[str, str] | None:
    """取得进程创建时间与命令，查询失败时不把 PID 当成可停止目标。"""
    if pid <= 1:
        return None
    if os.name == "nt":
        script = (
            f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}';"
            "if($p){@{start=$p.CreationDate.ToString('o');command=$p.CommandLine}|ConvertTo-Json -Compress}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True
        )
        if result.returncode or not result.stdout.strip():
            return None
        record = json.loads(result.stdout)
        return record["start"], record["command"]
    environment = {
        **os.environ,
        "LC_TIME": "C",
        "LC_CTYPE": "UTF-8" if sys.platform == "darwin" else "C.UTF-8",
        "TZ": "UTC",
    }
    environment.pop("LC_ALL", None)
    result = subprocess.run(
        ["ps", "-ww", "-p", str(pid), "-o", "lstart=", "-o", "command="],
        capture_output=True,
        text=True,
        env=environment,
    )
    if result.returncode:
        return None
    parts = result.stdout.strip().split(maxsplit=5)
    return (" ".join(parts[:5]), parts[5]) if len(parts) == 6 else None


def state_of(root: Path) -> dict | None:
    path = root / "run" / "instance.json"
    if path.is_symlink():
        raise LaunchError("运行状态不能是符号链接")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (ValueError, TypeError) as exc:
        raise LaunchError("运行状态文件损坏，拒绝猜测进程归属") from exc
    return state if isinstance(state, dict) else None


def owned_process(root: Path, state: dict | None) -> bool:
    if not state or state.get("install_root") != str(root):
        return False
    instance_id = state.get("instance_id", "")
    if not isinstance(instance_id, str) or not re.fullmatch(r"[0-9a-f]{32}", instance_id):
        return False
    try:
        pid = int(state.get("pid", 0))
    except (ValueError, TypeError):
        return False
    identity = process_identity(pid)
    if identity is None:
        return False
    start, command = identity
    return (
        start == state.get("process_start")
        and "studio_api.launcher" in command
        and "serve" in command
        and str(root) in command
        and instance_id in command
    )


def status(root: Path) -> dict:
    state = state_of(root)
    running = owned_process(root, state)
    return {
        "running": running,
        "install_root": str(root),
        "pid": state.get("pid") if running else None,
        "url": state.get("url") if running else None,
        "unverified_lock": not running and _locked(root / "run" / "instance.lock"),
    }


def _write_state(root: Path, state: dict) -> None:
    path = root / "run" / "instance.json"
    temporary = path.with_name("instance.json.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _available(host: str, port: int) -> bool:
    with socket.socket() as connection:
        if os.name == "nt":
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            connection.bind((host, port))
        except OSError:
            return False
    return True


def runtime_environment(root: Path, manifest: dict) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "STUDIO_RESOURCE_ROOT": str(root / "app"),
            "APP_CONFIG_DIR": str(root / "app" / "config"),
            "APP_ENV_FILE": str(root / "config" / ".env"),
            "APP_DATA_DIR": str(root / "data"),
            "DATABASE_URL": f"sqlite:///{(root / 'data' / 'studio.db').as_posix()}",
            "STORAGE_ROOT": str(root / "data" / "storage"),
            "APP_ENV": str(manifest.get("env", "development")),
            "PYTHONUNBUFFERED": "1",
        }
    )
    env.pop("PYTHONPATH", None)
    return env


def start(root: Path, manifest: dict, host: str, port: int, no_browser: bool) -> dict:
    import urllib.request

    local_http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    with exclusive_lock(root / "run" / "start.lock", timeout=35):
        # 安装/卸载共用同一管理锁；不能使用等待锁之前读取的旧清单。
        root, manifest = layout(root, require_installed=True)
        current = status(root)
        if current["running"]:
            if current["url"] != f"http://{host}:{port}/":
                raise LaunchError("该安装实例已经运行，不能换端口启动第二个实例")
            if not no_browser:
                webbrowser.open(current["url"])
            return {**current, "already_running": True}
        if current["unverified_lock"]:
            raise LaunchError("运行锁被未知进程占用，请先核对现有实例")
        if not _available(host, port):
            raise LaunchError(f"端口 {port} 已被占用，请使用现有实例或先停止该实例")
        instance_id = uuid.uuid4().hex
        command = [
            sys.executable,
            "-m",
            "studio_api.launcher",
            "serve",
            "--install-root",
            str(root),
            "--host",
            host,
            "--port",
            str(port),
            "--instance-id",
            instance_id,
        ]
        log_path = root / "run" / "studio.log"
        with log_path.open("ab") as output:
            worker = subprocess.Popen(
                command,
                cwd=root,
                env=runtime_environment(root, manifest),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=os.name != "nt",
            )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if worker.poll() is not None:
                raise LaunchError(f"启动失败（退出码 {worker.returncode}），请查看 {log_path}")
            state = state_of(root)
            if state and state.get("instance_id") == instance_id and owned_process(root, state):
                try:
                    with local_http.open(f"http://{host}:{port}/health", timeout=1) as response:
                        healthy = response.status == 200
                    if healthy:
                        if not no_browser:
                            webbrowser.open(state["url"])
                        return status(root)
                except (OSError, ValueError):
                    pass
            time.sleep(0.2)
        # Popen 是本调用创建的进程；超时只结束该子进程，绝不按端口猜测目标。
        worker.terminate()
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=5)
        raise LaunchError(f"启动超时，请查看 {log_path}")


def serve(root: Path, manifest: dict, host: str, port: int, instance_id: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", instance_id):
        raise LaunchError("worker 缺少有效运行身份")
    root, manifest = layout(root, require_installed=True)
    with exclusive_lock(global_lock_path()), exclusive_lock(root / "run" / "instance.lock"):
        if not _available(host, port):
            raise LaunchError(f"端口 {port} 已被占用")
        identity = process_identity(os.getpid())
        if identity is None:
            raise LaunchError("无法确认 worker 进程身份")
        os.environ.update(runtime_environment(root, manifest))
        _write_state(
            root,
            {
                "install_root": str(root),
                "pid": os.getpid(),
                "instance_id": instance_id,
                "process_start": identity[0],
                "host": host,
                "port": port,
                "url": f"http://{host}:{port}/",
            },
        )
        try:
            import uvicorn

            uvicorn.run("studio_api.main:app", host=host, port=port, workers=1, reload=False)
        finally:
            current = state_of(root)
            if current and current.get("instance_id") == instance_id:
                (root / "run" / "instance.json").unlink(missing_ok=True)


def stop(root: Path, force: bool = False) -> dict:
    with exclusive_lock(root / "run" / "start.lock", timeout=35):
        state = state_of(root)
        if not owned_process(root, state):
            if _locked(root / "run" / "instance.lock"):
                raise LaunchError("无法核验占用运行锁的进程，未发送停止信号")
            (root / "run" / "instance.json").unlink(missing_ok=True)
            return {"running": False, "install_root": str(root), "already_stopped": True}
        pid = int(state["pid"])
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if not owned_process(root, state) and not _locked(root / "run" / "instance.lock"):
                (root / "run" / "instance.json").unlink(missing_ok=True)
                return {"running": False, "install_root": str(root)}
            time.sleep(0.2)
        if force and owned_process(root, state):
            if os.name != "nt" and os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if not _locked(root / "run" / "instance.lock"):
                    (root / "run" / "instance.json").unlink(missing_ok=True)
                    return {"running": False, "install_root": str(root), "forced": True}
                time.sleep(0.2)
        raise LaunchError("实例未在期限内停止，保留安装目录；核对任务后可使用 --force")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="管理 AI Film Studio 的受管安装实例")
    parser.add_argument("action", nargs="?", choices=("start", "status", "stop", "serve"), default="start")
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--instance-id", default="", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        root, manifest = layout(args.install_root)
        port = args.port if args.port is not None else int(manifest.get("port", 8010))
        if not 1 <= port <= 65535:
            raise LaunchError("端口必须在 1 到 65535 之间")
        if args.action == "serve":
            serve(root, manifest, args.host, port, args.instance_id)
            return 0
        result = (
            status(root)
            if args.action == "status"
            else stop(root, args.force)
            if args.action == "stop"
            else start(root, manifest, args.host, port, args.no_browser)
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (LaunchError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
