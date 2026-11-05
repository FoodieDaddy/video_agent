"""模块4 CLI 回归：子进程隔离、离线边界、凭据脱敏和失败语义。

不启动应用监听，不依赖正式数据库或真实供应商。TCP 企图另写哨兵，即使
被测检查吞掉网络错误，也不能被误报为测试通过。
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
CHECKS = ROOT / "scripts" / "checks"
CHECKER = "module4_directing_storyboard.py"
FAKE_KEY = "module4-fixture-credential-must-not-leak"


def run_check(
    tmp_path: Path,
    *arguments: str,
    key_in_dotenv: bool = True,
    fake_http: bool = False,
    fake_reply: str = "success",
    extra_env: dict[str, str] | None = None,
):
    """配置副本指向假模型；.env 在夹具根，外部网络在子解释器启动时禁用。"""
    fixture_root = tmp_path / "fixture_project"
    check_dir = fixture_root / "scripts" / "checks"
    check_dir.mkdir(parents=True)
    for name in (CHECKER, "module2_script_agent.py"):
        shutil.copy2(CHECKS / name, check_dir / name)
    shutil.copytree(ROOT / "config", fixture_root / "config")
    for name in ("director", "storyboard"):
        path = fixture_root / "config" / "agents" / f"{name}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        data["model"].update(
            {
                "provider": "module4_fake",
                "model_id": f"fixture-{name}",
                "fallback_provider": None,
                "fallback_model_id": None,
                "provider_options": {},
            }
        )
        path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    path = fixture_root / "config" / "providers" / "llm.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["providers"]["module4_fake"] = {
        "enabled": True,
        "protocol": "openai_chat",
        "url": "https://module4.invalid/v1",
        "api_key": "env:MODULE4_FIXTURE_API_KEY",
        "models": ["fixture-director", "fixture-storyboard"],
        "timeout_seconds": 5,
        "max_concurrency": 1,
    }
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    dotenv = "FAST_GATEWAY_BASE_URL=https://unused.invalid/v1\nFAST_GATEWAY_MODEL=unused-model\n"
    if key_in_dotenv:
        dotenv += f"MODULE4_FIXTURE_API_KEY={FAKE_KEY}\n"
    (fixture_root / ".env").write_text(dotenv, encoding="utf-8")
    guard = tmp_path / "guard"
    guard.mkdir()
    attempts = tmp_path / "tcp-attempts.txt"
    bootstrap = f"""
import socket
from pathlib import Path
import app.core.settings as settings
settings.REPO_ROOT = Path({str(fixture_root)!r})
marker = Path({str(attempts)!r})
old_connect = socket.socket.connect
old_connect_ex = socket.socket.connect_ex
def deny_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        marker.write_text('unexpected TCP', encoding='utf-8')
        raise RuntimeError('TCP disabled by module4 CLI regression')
    return old_connect(self, address)
def deny_connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6):
        marker.write_text('unexpected TCP', encoding='utf-8')
        raise RuntimeError('TCP disabled by module4 CLI regression')
    return old_connect_ex(self, address)
socket.socket.connect = deny_connect
socket.socket.connect_ex = deny_connect_ex
"""
    if fake_http:
        bootstrap += f"""
import json
import os
import httpx
requests_path = Path({str(tmp_path / "fake-requests.json")!r})
async def fake_send(self, request, *args, **kwargs):
    if request.url.host != 'module4.invalid' or request.url.path != '/v1/chat/completions':
        marker.write_text('unexpected HTTP destination', encoding='utf-8')
        raise RuntimeError('unexpected HTTP destination')
    key = os.getenv('MODULE4_FIXTURE_API_KEY')
    assert key == {FAKE_KEY!r}, 'fixture dotenv credential was not loaded'
    assert request.headers.get('Authorization') == 'Bearer ' + key, 'credential was not used'
    body = json.loads(request.content)
    assert body['model'] in ['fixture-director', 'fixture-storyboard'], 'YAML model was overridden'
    history = json.loads(requests_path.read_text()) if requests_path.exists() else {{'calls': 0, 'models': []}}
    history['calls'] += 1
    history['models'].append(body['model'])
    requests_path.write_text(json.dumps(history), encoding='utf-8')
    if {fake_reply!r} == 'error_secret':
        return httpx.Response(400, text='fixture error containing ' + key, request=request)
    if body['model'] == 'fixture-director':
        output = {{'visual_style': '克制写实', 'shot_strategy': {{'total_shots': 3, 'avg_duration_seconds': 5.0}}}}
    else:
        output = {{'title': '假传输回归分镜', 'shots': [{{
            'description': '镜头' + str(n) + '：两人在旧书店递出信封',
            'scene_name': '旧书店', 'action': '递出信封',
            'camera': {{'shot_type': 'medium_shot', 'movement': 'static', 'angle': 'eye_level'}},
            'duration_seconds': 5.0, 'visual_prompt': '克制写实，雨夜旧书店，递信',
            'negative_prompt': '模糊，水印',
            'characters': [{{'character_name': '林简'}}],
            'dialogue': [{{'character_name': '苏晚', 'text': '我们一起送信。'}}],
        }} for n in range(1, 4)]}}
    return httpx.Response(200, json={{'id': 'module4_fake_request', 'choices': [{{
        'message': {{'content': json.dumps(output, ensure_ascii=False)}}
    }}], 'usage': {{'prompt_tokens': 30, 'completion_tokens': 50}}}}, request=request)
httpx.AsyncClient.send = fake_send
"""
    (guard / "sitecustomize.py").write_text(bootstrap, encoding="utf-8")
    runtime_tmp = tmp_path / "runtime_tmp"
    runtime_tmp.mkdir()
    env = os.environ.copy()
    env.pop("MODULE4_FIXTURE_API_KEY", None)
    env.update(
        {
            "PYTHONPATH": os.pathsep.join([str(guard), str(ROOT / "backend")]),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(runtime_tmp),
            "TEMP": str(runtime_tmp),
            "TMP": str(runtime_tmp),
            "FAST_GATEWAY_API_KEY": "",
            "MODULE_CHECK_API_KEY": "",
            "AGENT_MODEL_PROVIDER": "hostile-provider",
            "AGENT_MODEL_ID": "hostile-model",
        }
    )
    env.update(extra_env or {})
    report_path = tmp_path / "module4-report.json"
    result = subprocess.run(
        [sys.executable, str(check_dir / CHECKER), *arguments, "--report-json", str(report_path)],
        cwd=fixture_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert not attempts.exists(), result.stdout + result.stderr
    assert report_path.is_file(), result.stdout + result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return result, report, report_path


def test_module4_offline_reports_all_groups_and_only_allowed_targets(tmp_path):
    result, report, _ = run_check(tmp_path, "--offline")
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["mode"] == "offline" and report["success"] is True
    assert report["upstream"] == "saved_manual_and_synthetic_profiles"
    assert len({row["name"] for row in report["rows"]}) == len(report["rows"])
    assert all(row["status"] == "PASS" for row in report["rows"])
    assert {"directing", "storyboard", "second_gate"}.issubset({row["name"] for row in report["rows"]})
    primary = report["evidence"]["primary"]
    assert set(primary["agent_ids"]) == {"director", "storyboard"}
    assert primary["agent_runs"] == primary["model_logs"] == 4
    assert primary["attempts"] == 4
    assert not any(report["evidence"]["downstream_counts"].values())
    assert report["sandbox_removed"] is True
    assert not Path(report["sandbox_path"]).exists()


def test_module4_overrides_hostile_inherited_database_storage_and_config(tmp_path):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    database = foreign / "sentinel.db"
    database.write_bytes(b"not-sqlite-preserve-this")
    storage = foreign / "storage"
    storage.mkdir()
    marker = storage / "sentinel.txt"
    marker.write_text("preserve", encoding="utf-8")
    result, report, _ = run_check(
        tmp_path,
        "--offline",
        extra_env={
            "DATABASE_URL": f"sqlite:///{database}",
            "STORAGE_ROOT": str(storage),
            "STORAGE_BACKEND": "s3",
            "APP_CONFIG_DIR": str(foreign / "missing-config"),
            "APP_DATA_DIR": str(foreign / "data"),
            "APP_ENV": "production",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert database.read_bytes() == b"not-sqlite-preserve-this"
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert sorted(p.name for p in storage.iterdir()) == ["sentinel.txt"]
    assert not (foreign / "data").exists()
    for name in ("db", "storage", "data_dir", "config_dir"):
        assert Path(report[name]).is_relative_to(Path(report["sandbox_path"]))


def test_module4_keep_retains_owned_sandbox_and_redacts_credentials(tmp_path):
    result, report, report_path = run_check(tmp_path, "--offline", "--keep")
    sandbox = Path(report["sandbox_path"]).resolve()
    assert sandbox.is_relative_to((tmp_path / "runtime_tmp").resolve())
    try:
        assert result.returncode == 0, result.stdout + result.stderr
        assert report["sandbox_removed"] is False
        assert any(sandbox.rglob("*.db"))
        assert FAKE_KEY not in result.stdout + result.stderr + report_path.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def test_module4_missing_real_key_fails_without_hiding_required_skips(tmp_path):
    result, report, _ = run_check(tmp_path, key_in_dotenv=False)
    assert result.returncode != 0
    assert report["mode"] == "live" and report["success"] is False
    statuses = [row["status"] for row in report["rows"]]
    assert "FAIL" in statuses and "SKIP" in statuses
    assert any("MODULE4_FIXTURE_API_KEY" in row["detail"] for row in report["rows"])
    assert report["sandbox_removed"] is True
    assert not Path(report["sandbox_path"]).exists()


def test_module4_default_live_path_reads_yaml_dotenv_through_fake_http(tmp_path):
    """不传模型或密钥CLI参数，验证真实协议路径；网络仍完全是假传输。"""
    result, report, report_path = run_check(tmp_path, fake_http=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert report["mode"] == "live" and report["success"] is True
    for name in ("director", "storyboard"):
        config = report["effective_config"][name]
        assert config["provider"] == "module4_fake"
        assert config["model"] == f"fixture-{name}"
        assert config["api_key_env"] == "MODULE4_FIXTURE_API_KEY"
        assert config["max_retries"] == config["repair_attempts"] == 0
        assert config["fallback_provider"] is None
    requests = json.loads((tmp_path / "fake-requests.json").read_text(encoding="utf-8"))
    assert requests["calls"] == 4
    assert requests["models"].count("fixture-director") == 2
    assert requests["models"].count("fixture-storyboard") == 2
    assert FAKE_KEY not in result.stdout + result.stderr + report_path.read_text(encoding="utf-8")


def test_module4_provider_error_does_not_expose_dotenv_credential(tmp_path):
    result, report, report_path = run_check(tmp_path, fake_http=True, fake_reply="error_secret")
    assert result.returncode != 0 and report["success"] is False
    assert FAKE_KEY not in result.stdout + result.stderr + report_path.read_text(encoding="utf-8")
    assert any(row["status"] == "FAIL" for row in report["rows"])
    assert report["sandbox_removed"] is True
