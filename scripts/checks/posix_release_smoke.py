"""真实 macOS/Linux 发布包生命周期验收。

本工具只管理自己安装到临时目录的实例。默认端口已有服务时直接拒绝，
不停止其他实例、不自动换端口；由调用方协调正式服务的暂停与恢复。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_STAGES = ["characters_scenes", "storyboard", "shots", "final"]
EXPECTED_MEMBERS = {
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


class CheckFailure(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or "\\" in name
        or any(part in {"", ".", ".."} for part in name.split("/"))
        or any(":" in part for part in path.parts)
        or any(char in name for char in ("\0", "\n", "\r"))
    ):
        raise CheckFailure(f"发布包路径不安全：{name!r}")
    return path


def unpack_and_verify(archive: Path, destination: Path) -> tuple[Path, dict[str, Any]]:
    """验证 tar 只含单根常规文件，并核对发布清单覆盖的全部文件。"""
    with tarfile.open(archive, "r:gz") as package:
        members = package.getmembers()
        if not members or len(members) > 10000:
            raise CheckFailure("发布包为空或文件数量超出验收范围")
        names: set[str] = set()
        total = 0
        for member in members:
            relative = safe_path(member.name)
            if not member.isfile() or len(relative.parts) < 2:
                raise CheckFailure(f"发布包只允许单根目录下的常规文件：{member.name}")
            if member.name in names:
                raise CheckFailure(f"发布包包含重复文件：{member.name}")
            names.add(member.name)
            total += member.size
            if member.size < 0 or member.size > 128 * 1024 * 1024 or total > 512 * 1024 * 1024:
                raise CheckFailure("发布包体积超出验收范围")
        roots = {PurePosixPath(name).parts[0] for name in names}
        if len(roots) != 1:
            raise CheckFailure("发布包必须只有一个顶层目录")
        destination.mkdir(parents=True, exist_ok=False)
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = package.extractfile(member)
            if source is None:
                raise CheckFailure(f"无法读取发布文件：{member.name}")
            with source, target.open("wb") as output:
                while block := source.read(1024 * 1024):
                    output.write(block)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    root = destination / roots.pop()
    try:
        manifest = json.loads((root / "release.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckFailure("缺少有效 release.json") from exc
    if not isinstance(manifest, dict) or manifest.get("name") != "ai-film-studio":
        raise CheckFailure("发布清单不属于 AI Film Studio")
    platform_name = (
        "macos" if sys.platform == "darwin" else "linux" if sys.platform.startswith("linux") else ""
    )
    if manifest.get("platform") != platform_name:
        raise CheckFailure(f"发布包不适用于当前 {platform_name or sys.platform} 平台")
    if manifest.get("schema_version") != 1 or manifest.get("artifact_kind") != "source-bootstrap":
        raise CheckFailure("仅验收当前 POSIX source-bootstrap 发布格式")
    descriptions = manifest.get("workspace_members")
    if (
        not isinstance(descriptions, list)
        or len(descriptions) != 13
        or manifest.get("workspace_member_count") != 13
        or {item.get("name") for item in descriptions if isinstance(item, dict)} != EXPECTED_MEMBERS
    ):
        raise CheckFailure("发布清单必须包含预期的 13 个 workspace 成员")
    expected = manifest.get("content_sha256")
    if not isinstance(expected, dict):
        raise CheckFailure("发布清单缺少文件哈希")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if set(expected) != actual - {"release.json"}:
        raise CheckFailure("发布文件集合与哈希清单不一致")
    for name, digest in expected.items():
        relative = safe_path(name)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise CheckFailure(f"发布文件哈希无效：{name}")
        if sha256(root.joinpath(*relative.parts)) != digest:
            raise CheckFailure(f"发布文件哈希不符：{name}")
    required = ("install.sh", "uninstall.sh", "installer/posix.py", "payload/uv.lock")
    if any(name not in expected for name in required):
        raise CheckFailure("发布包缺少 POSIX 安装入口或共享锁文件")
    if manifest.get("uv_lock_sha256") != sha256(root / "payload/uv.lock"):
        raise CheckFailure("发布锁文件哈希不一致")
    return root, manifest


def port_available(port: int) -> bool:
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def isolated_environment(temporary: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in tuple(env):
        if re.search(r"(?:API_KEY|ACCESS_KEY|TOKEN|PASSWORD|SECRET|AUTHORIZATION)", name, re.I):
            env.pop(name, None)
    for name in ("PYTHONPATH", "STUDIO_RESOURCE_ROOT", "APP_CONFIG_DIR"):
        env.pop(name, None)
    empty = temporary / "empty.env"
    empty.write_text("", encoding="utf-8")
    env.update(
        STUDIO_PYTHON=sys.executable,
        STUDIO_INSTANCE_LOCK_FILE=str(temporary / "global-instance.lock"),
        APP_ENV="test",
        APP_ENV_FILE=str(empty),
        APP_DATA_DIR=str(temporary / "bootstrap-data"),
        DATABASE_URL=f"sqlite:///{(temporary / 'bootstrap.db').as_posix()}",
        STORAGE_ROOT=str(temporary / "bootstrap-storage"),
        STORAGE_BACKEND="local",
        APP_ALLOW_DEV_AUTH="1",
        AGENT_MODEL_PROVIDER="mock",
        AGENT_MODEL_ID="",
        FAST_GATEWAY_BASE_URL="https://posix-release.invalid/v1",
        FAST_GATEWAY_MODEL="mock-llm",
        FAST_GATEWAY_API_KEY="",
        QWEN_API_KEY="",
        MINIMAX_API_KEY="",
        PYTHONUNBUFFERED="1",
    )
    return env


def redacted_tail(text: str, temporary: Path | None) -> str:
    """报告仅保留错误尾段，清除继承环境中的凭据值与 URL 登录信息。"""
    for key, value in os.environ.items():
        if len(value) >= 6 and re.search(
            r"API_KEY|ACCESS_KEY|TOKEN|PASSWORD|SECRET|AUTHORIZATION", key, re.I
        ):
            text = text.replace(value, "<redacted>")
    text = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1<redacted>@", text)
    text = re.sub(r"(?i)(Bearer\s+)\S+", r"\1<redacted>", text)
    if temporary is not None:
        text = text.replace(str(temporary), "<temporary-root>")
    return "\n".join(text.splitlines()[-25:])[-6000:]


def run_command(
    command: list[str], env: dict[str, str], *, timeout: float = 600
) -> subprocess.CompletedProcess[str]:
    """超时只回收本调用新建的命令进程组；受管 server 由 finally 的 launcher 停止。"""
    process = subprocess.Popen(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
        # 命令 leader 已退出时，仍清理本调用创建的组内 pip/编译等后代。
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def require_success(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode:
        raise CheckFailure(f"命令退出码 {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def command_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    output = require_success(result)
    for line in reversed(output.splitlines()):
        with contextlib.suppress(ValueError):
            data = json.loads(line)
            if isinstance(data, dict):
                return data
    raise CheckFailure("启动器未返回 JSON 状态")


def request(base: str, path: str, *, body: dict | None = None, raw: bool = False):
    headers = {"X-User-Id": "posix-release-check", "X-User-Role": "admin"}
    content = None
    if body is not None:
        content = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(urllib.parse.urljoin(base, path), data=content, headers=headers)
    try:
        local_http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with local_http.open(req, timeout=180) as response:
            value = response.read()
            if response.status not in {200, 201, 202}:
                raise CheckFailure(f"HTTP {response.status}: {path}")
    except urllib.error.HTTPError as exc:
        raise CheckFailure(f"HTTP {exc.code}: {path}\n{exc.read().decode('utf-8', 'replace')}") from exc
    return value if raw else json.loads(value)


def verify_http(base: str, temporary: Path) -> dict[str, Any]:
    health = request(base, "/health")
    if health.get("status") != "ok" or health.get("env") != "test":
        raise CheckFailure("健康接口未报告隔离 test 环境")
    for path in ("/", "/app.js", "/styles.css", "/assets/favicon.svg"):
        if not request(base, path, raw=True):
            raise CheckFailure(f"静态资源为空：{path}")
    request(base, "/api/v1/meta")
    project = request(base, "/api/v1/projects", body={"name": "POSIX 发布隔离验收"})
    pid = project["id"]
    request(base, f"/api/v1/projects/{pid}/upload?sample=true", body={})
    started = request(base, f"/api/v1/projects/{pid}/workflows/start?wait=true", body={})
    if started["task"]["status"] != "succeeded":
        raise CheckFailure(f"工作流任务失败：{started['task'].get('error', '')}")
    stages = []
    for _ in range(8):
        dashboard = request(base, f"/api/v1/projects/{pid}/dashboard")
        if not dashboard["pending_reviews"]:
            break
        review = dashboard["pending_reviews"][0]
        stages.append(review["stage"])
        request(base, f"/api/v1/reviews/{review['id']}?wait=true", body={"status": "approved"})
    if stages != EXPECTED_STAGES or dashboard["workflow"]["status"] != "completed":
        raise CheckFailure(f"四关流程未完成：{stages} / {dashboard.get('workflow')}")
    exported = request(base, f"/api/v1/projects/{pid}/export")
    if not exported["ready"]:
        raise CheckFailure("导出接口没有可用成片")
    media = request(base, exported["film"]["url"], raw=True)
    if len(media) <= 1000:
        raise CheckFailure("导出成片过小")
    film = temporary / "probe-film.mp4"
    film.write_bytes(media)
    probe = run_command(
        [os.environ.get("FFPROBE_BIN") or "ffprobe", "-v", "error", "-show_format", "-of", "json", str(film)],
        os.environ.copy(),
        timeout=30,
    )
    duration = float(json.loads(require_success(probe))["format"]["duration"])
    if duration <= 0:
        raise CheckFailure("FFprobe 未确认有效成片时长")
    return {
        "health_console_meta": True,
        "review_stages": stages,
        "workflow": "completed",
        "export_bytes": len(media),
        "ffprobe_duration_seconds": duration,
    }


def observed_process(root: Path) -> tuple[int, str] | None:
    """只观察受管状态文件中的唯一 token，清理不按端口或任意 PID 发信号。"""
    try:
        state = json.loads((root / "run/instance.json").read_text())
        pid, token = int(state["pid"]), str(state["instance_id"])
        if pid <= 1 or not re.fullmatch(r"[0-9a-f]{32}", token):
            return None
        if state.get("install_root") != str(root):
            return None
        return pid, token
    except (OSError, ValueError, KeyError, TypeError):
        return None


def process_remains(identity: tuple[int, str] | None) -> bool:
    if identity is None:
        return False
    result = subprocess.run(
        ["ps", "-ww", "-p", str(identity[0]), "-o", "command="], capture_output=True, text=True
    )
    return result.returncode == 0 and identity[1] in result.stdout and "studio_api.launcher" in result.stdout


def run(archive: Path, port: int, report_path: Path) -> int:
    report: dict[str, Any] = {
        "result": "failed",
        "mode": "real POSIX install + TCP HTTP; forced mock",
        "archive": archive.name,
        "port": port,
        "stages": [],
    }
    temporary: Path | None = None
    root: Path | None = None
    env: dict[str, str] | None = None
    identity = None
    temporary_manager = None
    code = 1
    cleanup_ok = True
    try:
        if not port_available(port):
            report["result"] = "blocked"
            raise CheckFailure(f"端口 {port} 已被占用，验收不会停止现有服务或自动换端口")
        report["archive_sha256"] = sha256(archive)
        temporary_manager = tempfile.TemporaryDirectory(prefix="studio POSIX 发布验收 ")
        temporary = Path(temporary_manager.name).resolve()
        root = temporary / "测试安装 带空格"
        env = isolated_environment(temporary)
        print("[RUN] 发布归档路径与全部文件哈希", flush=True)
        release, manifest = unpack_and_verify(archive, temporary / "解压 发布包")
        report.update(
            platform=manifest["platform"],
            version=manifest["version"],
            source=manifest.get("source"),
            workspace_member_count=13,
        )
        report["stages"].append("archive_integrity")
        print("[RUN] 临时目录真实冻结安装", flush=True)
        require_success(
            run_command(
                [
                    str(release / "install.sh"),
                    "--dir",
                    str(root),
                    "--python",
                    sys.executable,
                    "--env",
                    "test",
                    "--port",
                    str(port),
                    "--no-shortcuts",
                ],
                env,
            )
        )
        report["stages"].append("install")
        if not port_available(port):
            raise CheckFailure("安装期间目标端口被其他服务占用，拒绝启动测试实例")
        print("[RUN] 真实单实例启动与重复启动检查", flush=True)
        state = command_json(run_command([str(root / "start-studio.sh"), "--no-browser"], env, timeout=60))
        identity = observed_process(root)
        if not state.get("running") or identity is None or state.get("pid") != identity[0]:
            raise CheckFailure("启动器没有报告有效受管实例")
        duplicate = command_json(
            run_command([str(root / "start-studio.sh"), "--no-browser"], env, timeout=60)
        )
        if duplicate.get("pid") != state["pid"] or not duplicate.get("already_running"):
            raise CheckFailure("重复启动未复用原实例")
        with socket.socket() as spare:
            spare.bind(("127.0.0.1", 0))
            other_port = spare.getsockname()[1]
        refused = run_command(
            [str(root / "start-studio.sh"), "--port", str(other_port), "--no-browser"], env, timeout=60
        )
        if refused.returncode == 0:
            raise CheckFailure("运行中的同一安装目录允许另开端口实例")
        status = command_json(run_command([str(root / "studio-status.sh")], env, timeout=30))
        if status.get("pid") != state["pid"]:
            raise CheckFailure("拒绝另开端口后原实例发生变化")
        with Path(env["STUDIO_INSTANCE_LOCK_FILE"]).open("a+b") as lock:
            import fcntl

            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                report["global_instance_lock_held"] = True
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                raise CheckFailure("运行中的实例未持有跨安装目录的全局锁")
        report.update(duplicate_start_reused_pid=True, different_port_refused=True)
        report["stages"].append("single_instance")
        print("[RUN] HTTP 四关、FFmpeg 与媒体导出", flush=True)
        report.update(verify_http(f"http://127.0.0.1:{port}/", temporary))
        report["stages"].append("http_workflow")
        print("[RUN] 受管停止与端口释放", flush=True)
        stopped = command_json(run_command([str(root / "stop-studio.sh")], env, timeout=60))
        if stopped.get("running") or process_remains(identity) or not port_available(port):
            raise CheckFailure("停止后实例进程或端口仍未释放")
        report["stages"].append("stop")
        with contextlib.closing(
            sqlite3.connect((root / "data/studio.db").as_uri() + "?mode=ro", uri=True)
        ) as database:
            providers = sorted(
                row[0] for row in database.execute("SELECT DISTINCT model_provider FROM agent_runs")
            )
        if providers != ["mock"]:
            raise CheckFailure(f"发现非 mock 执行记录：{providers}")
        report["recorded_model_providers"] = providers
        data_marker = root / "data" / "preserve-marker.txt"
        config_marker = root / "config" / "preserve-marker.txt"
        for marker in (data_marker, config_marker):
            marker.write_text("用户数据保留检查", encoding="utf-8")
        print("[RUN] 默认卸载保留数据，再显式清除测试数据", flush=True)
        uninstall = [str(release / "uninstall.sh"), "--dir", str(root)]
        require_success(run_command(uninstall, env, timeout=60))
        if (
            (root / "venv").exists()
            or (root / "app").exists()
            or not all(p.is_file() for p in (data_marker, config_marker))
        ):
            raise CheckFailure("默认卸载未正确移除运行环境或保留用户数据")
        report["default_uninstall_preserved_data_config"] = True
        require_success(run_command([*uninstall, "--purge"], env, timeout=60))
        if root.exists():
            raise CheckFailure("显式 purge 后测试安装根仍有残留")
        report["purge_removed_installation"] = True
        report["stages"].append("uninstall_and_purge")
        report["result"] = "passed"
        code = 0
    except KeyboardInterrupt:
        report["error"] = "验收被中断"
        code = 130
    except (CheckFailure, OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as exc:
        report["error"] = redacted_tail(str(exc), temporary)
    finally:
        if report["result"] != "passed" and root is not None:
            log_path = root / "run" / "studio.log"
            if log_path.is_file():
                report["startup_log_tail"] = redacted_tail(
                    log_path.read_text(encoding="utf-8", errors="replace"), temporary
                )
        if root is not None and env is not None and (root / "install.json").is_file():
            try:
                if observed_process(root) is not None:
                    require_success(
                        run_command(
                            [
                                sys.executable,
                                "-m",
                                "studio_api.launcher",
                                "stop",
                                "--install-root",
                                str(root),
                                "--force",
                            ],
                            env,
                            timeout=60,
                        )
                    )
                if process_remains(identity):
                    raise CheckFailure("受管停止后仍观察到测试进程；保留临时目录供恢复，拒绝按端口误杀")
            except (CheckFailure, OSError, subprocess.SubprocessError) as exc:
                cleanup_ok = False
                report["cleanup_error"] = redacted_tail(str(exc), temporary)
                report["result"] = "failed"
                code = 1
        report["test_process_removed"] = not process_remains(identity)
        if temporary_manager is not None:
            if cleanup_ok and report["test_process_removed"]:
                temporary_manager.cleanup()
                report["temporary_directory_removed"] = not temporary.exists()
            else:
                # 无法确认进程归属时，保留现场比删除运行中的数据目录更安全。
                temporary_manager._finalizer.detach()
                report["temporary_directory_removed"] = False
                report["recovery_directory"] = str(temporary)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path, help="当前平台的发布 .tar.gz")
    parser.add_argument("--port", default=8010, type=int)
    parser.add_argument("--report-json", required=True, type=Path)
    args = parser.parse_args(argv)
    if os.name != "posix" or not (sys.platform == "darwin" or sys.platform.startswith("linux")):
        parser.error("真实生命周期验收只支持 macOS/Linux")
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1 到 65535 之间")
    return run(args.release.expanduser().resolve(), args.port, args.report_json.expanduser().resolve())


if __name__ == "__main__":
    raise SystemExit(main())
