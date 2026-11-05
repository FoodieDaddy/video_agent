"""模块2自检CLI的回归：沙箱、默认YAML/.env、凭据和完整通过语义。

测试使用临时项目配置副本和假的.env；即便测试live路径也只经过httpx假传输。
子进程还记录并阻止TCP连接，防止错误路由到开发机上配置的真实模型服务。
不使用应用fixture、不启动HTTP监听、不写正式业务数据。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "checks" / "module2_script_agent.py"
FAKE_KEY = "module2-fake-dotenv-credential-must-never-appear"


def run_check(
    tmp_path: Path,
    *arguments: str,
    key_in_dotenv: bool = True,
    fake_reply: str = "success",
    extra_env: dict[str, str] | None = None,
):
    """复制入口与配置，保留真实backend实现；只替换.env位置和HTTP传输。"""
    project = tmp_path / "fixture_project"
    (project / "scripts" / "checks").mkdir(parents=True)
    shutil.copy2(CHECKER, project / "scripts" / "checks" / CHECKER.name)
    shutil.copytree(ROOT / "config", project / "config")
    agent_path = project / "config" / "agents" / "script.yaml"
    agent = yaml.safe_load(agent_path.read_text(encoding="utf-8"))
    agent["model"].update(
        {
            "provider": "module2_fake",
            "model_id": "module2-fake-model",
            "fallback_provider": None,
            "fallback_model_id": None,
            "provider_options": {},
        }
    )
    agent["generation"].update({"timeout_seconds": 5, "max_retries": 1})
    agent_path.write_text(yaml.safe_dump(agent, allow_unicode=True, sort_keys=False), encoding="utf-8")
    provider_path = project / "config" / "providers" / "llm.yaml"
    providers = yaml.safe_load(provider_path.read_text(encoding="utf-8"))
    providers["providers"]["module2_fake"] = {
        "enabled": True,
        "protocol": "openai_chat",
        "url": "https://module2.invalid/v1",
        "api_key": "env:MODULE2_FIXTURE_API_KEY",
        "models": ["module2-fake-model"],
        "timeout_seconds": 5,
        "max_concurrency": 1,
    }
    provider_path.write_text(yaml.safe_dump(providers, allow_unicode=True, sort_keys=False), encoding="utf-8")
    dotenv = (
        "# 测试夹具，不是真实凭据。\nAGENT_MODEL_PROVIDER=mock\nAGENT_MODEL_ID=wrong-global-model\n"
        "FAST_GATEWAY_BASE_URL=https://module2-config.invalid/v1\n"
        "FAST_GATEWAY_MODEL=module2-unused-gateway-model\n"
    )
    if key_in_dotenv:
        dotenv += f"MODULE2_FIXTURE_API_KEY={FAKE_KEY}\n"
    (project / ".env").write_text(dotenv, encoding="utf-8")

    runtime_tmp = tmp_path / "runtime_tmp"
    runtime_tmp.mkdir()
    guard_dir = tmp_path / "guard"
    guard_dir.mkdir()
    attempts = tmp_path / "tcp-attempts.txt"
    requests = tmp_path / "fake-requests.json"
    # sitecustomize在被测脚本导入前执行。HTTP假传输只认本测试的域名；
    # 未命中假传输的任何TCP连接都记录后抛错，不能被checker吞掉后蒙混过关。
    bootstrap = f"""
import json
import os
import socket
from pathlib import Path
import httpx
import app.core.settings as settings
settings.REPO_ROOT = Path({str(project)!r})
marker = Path({str(attempts)!r})
requests_path = Path({str(requests)!r})
old_connect = socket.socket.connect
old_connect_ex = socket.socket.connect_ex
def deny_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        marker.write_text("unexpected TCP", encoding="utf-8")
        raise RuntimeError("TCP disabled by module2 regression")
    return old_connect(self, address)
def deny_connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        marker.write_text("unexpected TCP", encoding="utf-8")
        raise RuntimeError("TCP disabled by module2 regression")
    return old_connect_ex(self, address)
socket.socket.connect = deny_connect
socket.socket.connect_ex = deny_connect_ex
async def fake_send(self, request, *args, **kwargs):
    if request.url.host != "module2.invalid" or request.url.path != "/v1/chat/completions":
        marker.write_text("unexpected HTTP destination", encoding="utf-8")
        raise RuntimeError("unexpected HTTP destination")
    key = os.getenv("MODULE2_FIXTURE_API_KEY")
    assert key == {FAKE_KEY!r}, "the fake dotenv credential was not loaded"
    assert request.headers.get("Authorization") == "Bearer " + key, "credential was not used"
    body = json.loads(request.content)
    assert body["model"] == "module2-fake-model", "YAML model was overridden by dotenv"
    history = json.loads(requests_path.read_text()) if requests_path.exists() else {{"calls": 0}}
    history["calls"] += 1
    history["authorization_ok"] = True
    requests_path.write_text(json.dumps(history), encoding="utf-8")
    if {fake_reply!r} == "error_secret":
        return httpx.Response(400, text="fixture error containing " + key, request=request)
    output = {{"title": "假传输回归剧本", "chapters": [], "events": [{{
        "title": "开场", "description": "两个人在旧书店交谈。", "chapter_index": 1,
        "characters": ["林简", "苏晚"], "location": "旧书店", "importance": 0.8,
    }}], "dialogues": []}}
    return httpx.Response(200, json={{"id": "module2_fake_request", "choices": [{{
        "message": {{"content": json.dumps(output, ensure_ascii=False)}}
    }}], "usage": {{"prompt_tokens": 30, "completion_tokens": 50}}}}, request=request)
httpx.AsyncClient.send = fake_send
"""
    (guard_dir / "sitecustomize.py").write_text(bootstrap, encoding="utf-8")
    env = os.environ.copy()
    env.pop("MODULE2_FIXTURE_API_KEY", None)
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(runtime_tmp),
            "TMP": str(runtime_tmp),
            "TEMP": str(runtime_tmp),
            "AGENT_MODEL_PROVIDER": "hostile-provider",
            "AGENT_MODEL_ID": "hostile-model",
            "PYTHONPATH": os.pathsep.join([str(guard_dir), str(ROOT / "backend")]),
        }
    )
    env.update(extra_env or {})
    report_path = tmp_path / "module2-report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(project / "scripts" / "checks" / CHECKER.name),
            *arguments,
            "--report-json",
            str(report_path),
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert not attempts.exists(), result.stdout + result.stderr
    assert report_path.is_file(), result.stdout + result.stderr
    return result, json.loads(report_path.read_text(encoding="utf-8")), report_path, requests


def test_module2_offline_executes_all_eight_groups_and_links_evidence(tmp_path):
    result, report, _, requests = run_check(tmp_path, "--offline")

    assert result.returncode == 0, result.stdout + result.stderr
    assert report["mode"] == "offline" and report["success"] is True
    assert len(report["rows"]) == 8
    assert len({row["name"] for row in report["rows"]}) == 8
    assert all(row["status"] == "PASS" for row in report["rows"])
    assert report["evidence"]["agent_run_id"]
    assert report["evidence"]["events"] > 0
    assert report["evidence"]["provider"] == "mock"
    assert not requests.exists()
    assert report["sandbox_removed"] is True
    assert not Path(report["sandbox_path"]).exists()


def test_module2_isolates_hostile_inherited_database_and_storage(tmp_path):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    database = foreign / "sentinel.db"
    database.write_bytes(b"not-a-database-do-not-touch")
    storage = foreign / "storage"
    storage.mkdir()
    (storage / "sentinel.txt").write_text("keep", encoding="utf-8")
    result, report, _, _ = run_check(
        tmp_path,
        "--offline",
        extra_env={
            "DATABASE_URL": f"sqlite:///{database}",
            "STORAGE_ROOT": str(storage),
            "STORAGE_BACKEND": "s3",
            "APP_ENV": "production",
            "APP_DATA_DIR": str(foreign / "data"),
            "APP_CONFIG_DIR": str(foreign / "missing-config"),
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert report["success"] is True
    assert database.read_bytes() == b"not-a-database-do-not-touch"
    assert sorted(path.name for path in storage.iterdir()) == ["sentinel.txt"]
    assert (storage / "sentinel.txt").read_text(encoding="utf-8") == "keep"
    assert not (foreign / "data").exists()
    for key in ("db", "storage", "config_dir", "data_dir"):
        assert Path(report[key]).is_relative_to(Path(report["sandbox_path"]))


def test_module2_default_cli_uses_yaml_and_automatically_loads_dotenv(tmp_path):
    """没有模型/密钥CLI参数，凭据只存在假的.env中，且真的用于假HTTP请求。"""
    result, report, report_path, requests = run_check(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert report["mode"] == "live" and report["success"] is True
    assert report["effective_config"]["provider"] == "module2_fake"
    assert report["effective_config"]["model"] == "module2-fake-model"
    assert report["effective_config"]["api_key_env"] == "MODULE2_FIXTURE_API_KEY"
    assert report["effective_config"]["has_api_key"] is True
    assert report["evidence"]["provider"] == "module2_fake"
    assert report["evidence"]["request_id"] == "module2_fake_request"
    assert json.loads(requests.read_text()) == {"calls": 1, "authorization_ok": True}
    assert FAKE_KEY not in result.stdout + result.stderr + report_path.read_text()
    assert report["sandbox_removed"] is True


def test_module2_keep_and_budget_override_update_effective_fingerprint(tmp_path):
    baseline, baseline_report, _, _ = run_check(tmp_path / "baseline", "--offline")
    result, report, _, requests = run_check(
        tmp_path / "override",
        "--offline",
        "--keep",
        "--max-tokens",
        "512",
        "--timeout",
        "13",
    )
    sandbox = Path(report["sandbox_path"]).resolve()
    assert sandbox.is_relative_to((tmp_path / "override" / "runtime_tmp").resolve())
    try:
        assert baseline.returncode == result.returncode == 0, result.stdout + result.stderr
        assert report["sandbox_removed"] is False and sandbox.is_dir()
        assert Path(report["db"]).is_file()
        assert report["effective_config"]["max_tokens"] == 512
        assert report["effective_config"]["agent_timeout_seconds"] == 13
        assert report["effective_config"]["provider_timeout_seconds"] == 13
        assert (
            report["effective_config"]["config_version"]
            != baseline_report["effective_config"]["config_version"]
        )
        assert report["evidence"]["config_version"] == report["effective_config"]["config_version"]
        assert "worst_case" not in result.stdout and "decode_guess" not in result.stdout
        assert not requests.exists()
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def test_module2_missing_dotenv_credential_fails_before_any_request(tmp_path):
    result, report, _, requests = run_check(tmp_path, key_in_dotenv=False)

    assert result.returncode == 1
    assert report["success"] is False and len(report["rows"]) == 8
    rows = {row["name"]: row for row in report["rows"]}
    assert rows["3 agent config"]["status"] == "FAIL"
    assert (
        "MODULE2_FIXTURE_API_KEY" in rows["3 agent config"]["detail"]
        or "MODULE2_FIXTURE_API_KEY" in result.stdout
    )
    assert rows["4 run script"]["status"] == "SKIP"
    assert rows["6 evidence"]["status"] == "SKIP"
    assert rows["7 schema guard"]["status"] == rows["8 repair loop"]["status"] == "PASS"
    assert not requests.exists()
    assert report["sandbox_removed"] is True


def test_module2_provider_error_redacts_credential_from_all_outputs(tmp_path):
    result, report, report_path, requests = run_check(tmp_path, fake_reply="error_secret")

    assert result.returncode == 1 and report["success"] is False
    assert any(row["name"] == "4 run script" and row["status"] == "FAIL" for row in report["rows"])
    assert requests.is_file()
    assert FAKE_KEY not in result.stdout + result.stderr + report_path.read_text(encoding="utf-8")
    assert "[REDACTED]" in result.stdout + result.stderr + report_path.read_text(encoding="utf-8")
    assert report["sandbox_removed"] is True
