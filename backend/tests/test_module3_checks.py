"""模块 3 自检入口的回归：验证报告、隔离和清理，而非复制脚本实现。

所有子进程只使用 mock，或在缺少凭据时验证真实模式的失败语义。
这里不启动 HTTP 服务，也不需要外部模型、API Key 或正式业务数据库。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = ROOT / "scripts" / "checks" / "module3_characters_scenes.py"


def run_check(tmp_path: Path, *args: str, extra_env: dict[str, str] | None = None):
    """通过公开 CLI 运行；临时根目录也受 pytest 管理，防止 --keep 遗留数据。

    不借用 conftest 的应用 fixture，避免一次检查隐式启动另一套 runtime。
    凭据变量显式置空，阻止开发机环境或 .env 意外让本测试连接真实模型。
    """
    runtime_tmp = tmp_path / "runtime_tmp"
    runtime_tmp.mkdir()
    report_path = tmp_path / "module3-report.json"
    guard_dir = tmp_path / "network_guard"
    guard_dir.mkdir()
    network_attempts = tmp_path / "network-attempts.txt"
    # 子解释器启动时加载，保证测试本身不会触发真实 HTTP 调用。记录企图后
    # 才抛异常，避免脚本捕获连接异常后仍错误地以成功退出而掩盖联网行为。
    (guard_dir / "sitecustomize.py").write_text(
        "import socket\n"
        "from pathlib import Path\n"
        f"marker = Path({str(network_attempts)!r})\n"
        "original_connect = socket.socket.connect\n"
        "original_connect_ex = socket.socket.connect_ex\n"
        "def guard_connect(self, address):\n"
        "    if self.family in (socket.AF_INET, socket.AF_INET6):\n"
        "        marker.write_text('unexpected network attempt', encoding='utf-8')\n"
        "        raise RuntimeError('network disabled in module3 regression')\n"
        "    return original_connect(self, address)\n"
        "def guard_connect_ex(self, address):\n"
        "    if self.family in (socket.AF_INET, socket.AF_INET6):\n"
        "        marker.write_text('unexpected network attempt', encoding='utf-8')\n"
        "        raise RuntimeError('network disabled in module3 regression')\n"
        "    return original_connect_ex(self, address)\n"
        "socket.socket.connect = guard_connect\n"
        "socket.socket.connect_ex = guard_connect_ex\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "MODULE_CHECK_API_KEY": "",
            "FAST_GATEWAY_API_KEY": "",
            "FAST_GATEWAY_BASE_URL": "https://module3-config.invalid/v1",
            "FAST_GATEWAY_MODEL": "module3-unused-gateway-model",
            "AGENT_MODEL_PROVIDER": "",
            "AGENT_MODEL_ID": "",
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(runtime_tmp),
            "TEMP": str(runtime_tmp),
            "TMP": str(runtime_tmp),
            "PYTHONPATH": os.pathsep.join(filter(None, [str(guard_dir), env.get("PYTHONPATH")])),
        }
    )
    env.update(extra_env or {})
    result = subprocess.run(
        [sys.executable, str(CHECK_SCRIPT), *args, "--report-json", str(report_path)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert not network_attempts.exists(), result.stdout + result.stderr
    assert report_path.is_file(), result.stdout + result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return result, report, report_path


def test_module3_offline_cli_reports_complete_success_and_no_downstream_calls(tmp_path):
    """一次离线运行必须执行全部检查，不能用 SKIP 换取成功退出。"""
    result, report, _ = run_check(tmp_path, "--offline")

    assert result.returncode == 0, result.stdout + result.stderr
    assert report["mode"] == "offline"
    assert report["upstream_script"] == "mock_fixture"
    assert report["success"] is True
    assert len(report["rows"]) == 10
    names = [row["name"] for row in report["rows"]]
    assert all(name.strip() for name in names)
    assert len(set(names)) == 10, names
    assert all(row["status"] == "PASS" for row in report["rows"]), report["rows"]
    primary = report["counts"]["primary"]
    assert primary["characters"] > 0
    assert primary["scenes"] > 0
    assert primary["expected_module3_calls"] == 2 + primary["characters"] + primary["scenes"]
    assert primary["module3_agent_runs"] == primary["expected_module3_calls"]
    assert primary["other_agent_runs"] == 0
    assert report["sandbox_removed"] is True
    assert not Path(report["sandbox_path"]).exists()


def test_module3_overrides_inherited_database_storage_and_configuration(tmp_path):
    """故意传入错误外部设置，检查脚本必须在建库、导入小说前完成隔离。

    哨兵文件不是 SQLite，若错误使用它，运行会失败；字节比较再确认没有
    被初始化或覆盖。存储目录里的哨兵也必须保持唯一，避免测试悄悄写素材。
    """
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    database = foreign / "studio.db"
    database.write_bytes(b"module3-foreign-database-do-not-touch")
    storage = foreign / "storage"
    storage.mkdir()
    marker = storage / "sentinel.txt"
    marker.write_text("keep existing storage", encoding="utf-8")
    before_database = database.read_bytes()
    before_storage = marker.read_bytes()

    result, report, _ = run_check(
        tmp_path,
        "--offline",
        extra_env={
            "DATABASE_URL": f"sqlite:///{database.as_posix()}",
            "STORAGE_ROOT": str(storage),
            "STORAGE_BACKEND": "s3",
            "APP_DATA_DIR": str(foreign / "data"),
            "APP_CONFIG_DIR": str(foreign / "missing-config"),
            "APP_ENV": "production",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert report["success"] is True
    assert database.read_bytes() == before_database
    assert marker.read_bytes() == before_storage
    assert sorted(path.name for path in storage.iterdir()) == ["sentinel.txt"]
    assert not (foreign / "data").exists()
    assert report["sandbox_removed"] is True


def test_module3_keep_retains_only_its_sandbox_and_redacts_credentials(tmp_path):
    """保留沙箱便于复核；公开输出和 JSON 都不得携带凭据值。"""
    fake_key = "module3-regression-secret-must-not-appear"
    result, report, report_path = run_check(
        tmp_path,
        "--offline",
        "--keep",
        extra_env={"MODULE_CHECK_API_KEY": fake_key},
    )
    sandbox = Path(report["sandbox_path"]).resolve()
    owned_root = (tmp_path / "runtime_tmp").resolve()
    # 只有确定属于本测试的路径才清理；报告若错误指向其他目录，直接失败。
    assert sandbox.is_relative_to(owned_root)
    try:
        assert result.returncode == 0, result.stdout + result.stderr
        assert report["success"] is True
        assert report["sandbox_removed"] is False
        assert sandbox.is_dir()
        assert any(sandbox.rglob("*.db"))
        public_output = result.stdout + result.stderr + report_path.read_text(encoding="utf-8")
        assert fake_key not in public_output
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def test_module3_live_missing_key_fails_and_preserves_skipped_checks(tmp_path):
    """本机无监听端口仅作配置值；缺 key 必须在真实请求前失败。"""
    result, report, _ = run_check(
        tmp_path,
        "--base-url",
        "http://127.0.0.1:1/v1",
        "--model",
        "module3-test-model",
        "--api-key-env",
        "MODULE_CHECK_API_KEY",
    )

    assert result.returncode != 0
    assert report["mode"] == "live"
    assert report["upstream_script"] == "mock_fixture"
    assert report["success"] is False
    assert len(report["rows"]) == 10
    assert len({row["name"] for row in report["rows"]}) == 10
    statuses = [row["status"] for row in report["rows"]]
    assert "FAIL" in statuses
    assert "SKIP" in statuses
    assert any("MODULE_CHECK_API_KEY" in row["detail"] for row in report["rows"])
    assert report["sandbox_removed"] is True
    assert not Path(report["sandbox_path"]).exists()
