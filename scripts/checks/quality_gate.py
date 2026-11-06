"""本地与 CI 共用的只读质量门禁。

默认执行 Ruff lint、格式检查、渐进严格 mypy 和现有模块边界测试。
--scope tests 执行全量后端测试，--scope smoke 执行离线全流程；
所有执行均使用隔离数据目录和 mock 配置，
不启动网页服务、不调用真实模型，也不改写源码。

用法：
    uv run --frozen --extra dev python scripts/checks/quality_gate.py
    uv run --frozen --extra dev python scripts/checks/quality_gate.py --scope types
    uv run --frozen --extra dev python scripts/checks/quality_gate.py --scope tests
    uv run --frozen --extra dev python scripts/checks/quality_gate.py --scope smoke
    uv run --frozen --extra dev python scripts/checks/quality_gate.py --list
"""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCOPES = ("lint", "format", "types", "architecture")
SCOPES = (*DEFAULT_SCOPES, "tests", "smoke")
SOURCE_TARGETS = ("apps", "packages", "backend/tests", "scripts", "installer")


@dataclass(frozen=True)
class GateStep:
    """命令使用参数数组，不经 shell，避免路径和参数被解释为脚本。"""

    name: str
    command: tuple[str, ...]


def selected_scopes(requested: list[str] | None) -> tuple[str, ...]:
    """保持固定执行顺序；all 指默认四项，全量 tests 需要显式选择。"""
    selected = set(requested or DEFAULT_SCOPES)
    if "all" in selected:
        selected.remove("all")
        selected.update(DEFAULT_SCOPES)
    if "tests" in selected:
        # 全量 pytest 已包含模块边界用例，无需在同一轮重复运行。
        selected.discard("architecture")
    return tuple(scope for scope in SCOPES if scope in selected)


def build_steps(scopes: tuple[str, ...], python: str | None = None) -> list[GateStep]:
    executable = python or sys.executable
    commands = {
        "lint": ("-m", "ruff", "check", *SOURCE_TARGETS),
        "format": (
            "-m",
            "ruff",
            "format",
            "--check",
            "--output-format",
            "concise",
            *SOURCE_TARGETS,
        ),
        "types": ("-m", "mypy", "--config-file", "pyproject.toml"),
        "architecture": (
            "-m",
            "pytest",
            "-o",
            "addopts=",
            "-q",
            "backend/tests/test_modular_architecture.py",
        ),
        "tests": ("-m", "pytest", "-o", "addopts=", "-q", "backend/tests"),
        "smoke": ("scripts/smoke_pipeline.py",),
    }
    return [GateStep(scope, (executable, *commands[scope])) for scope in scopes]


def isolated_environment(root: Path, sandbox: Path) -> dict[str, str]:
    """对子进程固定 mock 和临时数据，清空继承的常见凭据，不改变终端环境。"""
    env = os.environ.copy()
    # .env 使用 setdefault 加载；空值阻止已列出的键再次加载。
    # 其他仅存在于 .env 的键仍可能加载，离线保证依靠强制 mock，不声称完整凭据沙箱。
    for name in tuple(env):
        if name.endswith(("_API_KEY", "_ACCESS_KEY_ID", "_SECRET_ACCESS_KEY")):
            env[name] = ""
    env.update(
        {
            "APP_ENV": "test",
            "APP_CONFIG_DIR": str(root / "config"),
            "APP_DATA_DIR": str(sandbox / "data"),
            "DATABASE_URL": f"sqlite:///{(sandbox / 'studio.db').as_posix()}",
            "STORAGE_ROOT": str(sandbox / "storage"),
            "STORAGE_BACKEND": "local",
            "AGENT_MODEL_PROVIDER": "mock",
            "AGENT_MODEL_ID": "",
            "FAST_GATEWAY_BASE_URL": "https://quality-gate.invalid/v1",
            "FAST_GATEWAY_MODEL": "mock-llm",
            "FAST_GATEWAY_API_KEY": "",
            "MODULE_CHECK_API_KEY": "",
            "QWEN_API_KEY": "",
            "MINIMAX_API_KEY": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(sandbox),
            "TMP": str(sandbox),
            "TEMP": str(sandbox),
        }
    )
    # 工作区成员由 uv 安装；清除临时路径注入，防止兼容目录掩盖漏装的包。
    env.pop("PYTHONPATH", None)
    return env


def stop_process(process: subprocess.Popen[bytes]) -> None:
    """回收本门禁创建的进程组，leader 已退出时也清理剩余后代。

    Windows 的 taskkill 仅能跟踪仍存在的父进程树；检查本身仍须管理自己的
    外部资源，不依赖本工具回收失去父进程关联的进程。
    """
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        if process.poll() is None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
        # 父进程结束不代表 FFmpeg 等同组后代均结束，始终清理剩余进程组。
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        if process.poll() is None:
            process.wait(timeout=5)
        return
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.kill()
    process.wait(timeout=5)


def run_step(step: GateStep, root: Path, env: dict[str, str], timeout: float) -> int:
    """继承工具输出，返回真实退出码；启动错误和超时均为门禁失败。"""
    print(f"[RUN] {step.name}: {shlex.join(step.command)}", flush=True)
    try:
        process = subprocess.Popen(step.command, cwd=root, env=env, start_new_session=os.name == "posix")
    except OSError as exc:
        print(f"[FAIL] {step.name}: 无法启动工具：{exc}", file=sys.stderr)
        return 127
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[FAIL] {step.name}: 超过 {timeout:g} 秒，正在回收进程。", file=sys.stderr)
        return 124
    finally:
        stop_process(process)


def run(scopes: tuple[str, ...], *, timeout: float, fail_fast: bool = False, root: Path = ROOT) -> int:
    steps = build_steps(scopes)
    if not steps:
        print("[FAIL] 未选择任何检查，不能将空执行视为通过。", file=sys.stderr)
        return 2
    results: list[tuple[str, int]] = []
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="studio_quality_gate_") as temporary:
            sandbox = Path(temporary).resolve()
            env = isolated_environment(root, sandbox)
            for step in steps:
                code = run_step(step, root, env, timeout)
                results.append((step.name, code))
                print(f"[{'PASS' if code == 0 else 'FAIL'}] {step.name}: exit={code}", flush=True)
                if code and fail_fast:
                    break
    except KeyboardInterrupt:
        print("[FAIL] 门禁被中断，测试进程和临时目录已回收。", file=sys.stderr)
        return 130
    print(
        f"质量门禁：{sum(code == 0 for _, code in results)}/{len(results)} 项通过，耗时 {time.monotonic() - started:.1f}s。"
    )
    return 0 if len(results) == len(steps) and all(code == 0 for _, code in results) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--scope", action="append", choices=("all", *SCOPES), help="选择检查，可重复；默认四项"
    )
    parser.add_argument("--list", action="store_true", help="只列出命令，不创建环境或执行检查")
    parser.add_argument("--fail-fast", action="store_true", help="首项失败后停止；默认收集所有结果")
    parser.add_argument("--timeout", type=float, default=600, help="每个检查最多执行秒数，默认600")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout 必须是有限正数")
    scopes = selected_scopes(args.scope)
    if args.list:
        for step in build_steps(scopes):
            print(f"{step.name}: {shlex.join(step.command)}")
        return 0
    return run(scopes, timeout=args.timeout, fail_fast=args.fail_fast)


if __name__ == "__main__":
    raise SystemExit(main())
