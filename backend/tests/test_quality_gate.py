"""共享门禁的编排回归；替换子进程，不递归运行真实检查或接触模型。"""

from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def gate(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "quality_gate_regression", ROOT / "scripts/checks/quality_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_gate_selects_defaults_and_deduplicates_full_test_scope(gate):
    assert gate.selected_scopes(None) == ("lint", "format", "types", "architecture")
    assert gate.selected_scopes(["types", "lint", "types"]) == ("lint", "types")
    assert gate.selected_scopes(["all", "tests"]) == ("lint", "format", "types", "tests")
    commands = {
        step.name: step.command for step in gate.build_steps(gate.DEFAULT_SCOPES, python="python-test")
    }
    assert commands["lint"] == (
        "python-test",
        "-m",
        "ruff",
        "check",
        "apps",
        "packages",
        "backend/tests",
        "scripts",
        "installer",
    )
    assert "--check" in commands["format"]
    assert commands["types"] == ("python-test", "-m", "mypy", "--config-file", "pyproject.toml")
    assert commands["architecture"][-1] == "backend/tests/test_modular_architecture.py"


def test_gate_uses_installed_workspace_members_without_pythonpath_override(gate, tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "legacy-source"))
    env = gate.isolated_environment(tmp_path, tmp_path / "sandbox")
    assert "PYTHONPATH" not in env
    assert os.environ["PYTHONPATH"] == str(tmp_path / "legacy-source")


def test_list_is_read_only_and_never_starts_a_subprocess(gate, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("--list 不应执行门禁或创建子进程")

    monkeypatch.setattr(gate, "run", forbidden)
    assert gate.main(["--scope", "types", "--list"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("types:") and "mypy" in output
    assert "ruff" not in output


def test_smoke_scope_overrides_live_settings_and_removes_artifacts(gate, tmp_path, monkeypatch):
    """旧 smoke 会继承环境；共享入口必须覆盖模型和存储，并回收其临时产物。"""
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "live-provider-do-not-use")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///formal.db")
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "formal-storage"))
    seen = []

    def fake_run(step, root, env, timeout):
        assert step.command[-1] == "scripts/smoke_pipeline.py"
        assert env["AGENT_MODEL_PROVIDER"] == "mock"
        sandbox = Path(env["TMPDIR"])
        assert Path(env["STORAGE_ROOT"]).is_relative_to(sandbox)
        assert env["DATABASE_URL"] != "sqlite:///formal.db"
        (sandbox / "smoke-artifact").write_text("temporary", encoding="utf-8")
        seen.append(sandbox)
        return 0

    monkeypatch.setattr(gate, "run_step", fake_run)
    assert gate.main(["--scope", "smoke"]) == 0
    assert len(seen) == 1 and not seen[0].exists()
    assert os.environ["AGENT_MODEL_PROVIDER"] == "live-provider-do-not-use"
    assert not (tmp_path / "formal-storage").exists()


@pytest.mark.parametrize("fail_fast,expected", [(False, ["lint", "types"]), (True, ["lint"])])
def test_failure_result_preserves_environment_and_cleans_sandbox(
    gate, tmp_path, monkeypatch, fail_fast, expected
):
    foreign_data = tmp_path / "formal-data"
    foreign_data.mkdir()
    marker = foreign_data / "sentinel"
    marker.write_text("unchanged", encoding="utf-8")
    monkeypatch.setenv("APP_DATA_DIR", str(foreign_data))
    monkeypatch.setenv("DATABASE_URL", "sqlite:///formal-do-not-use.db")
    monkeypatch.setenv("FAST_GATEWAY_API_KEY", "gate-parent-credential-do-not-forward")
    monkeypatch.setenv("CUSTOM_API_KEY", "another-parent-credential")
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "real-provider-do-not-use")
    before = dict(os.environ)
    seen = []
    sandboxes = []

    def fake_run(step, root, env, timeout):
        seen.append(step.name)
        assert root == tmp_path and timeout == 9
        sandbox = Path(env["TMPDIR"])
        sandboxes.append(sandbox)
        assert sandbox.exists()
        assert Path(env["APP_DATA_DIR"]).is_relative_to(sandbox)
        assert Path(env["STORAGE_ROOT"]).is_relative_to(sandbox)
        assert env["DATABASE_URL"].endswith("/studio.db")
        assert env["STORAGE_BACKEND"] == "local"
        assert env["AGENT_MODEL_PROVIDER"] == "mock"
        assert env["FAST_GATEWAY_MODEL"] == "mock-llm"
        assert env["FAST_GATEWAY_API_KEY"] == env["CUSTOM_API_KEY"] == ""
        (sandbox / "created-by-fake-check").write_text("temporary", encoding="utf-8")
        return 3 if step.name == "lint" else 0

    monkeypatch.setattr(gate, "run_step", fake_run)
    assert gate.run(("lint", "types"), root=tmp_path, timeout=9, fail_fast=fail_fast) == 1
    assert seen == expected
    assert all(not sandbox.exists() for sandbox in sandboxes)
    assert dict(os.environ) == before
    assert marker.read_text() == "unchanged"
    assert sorted(path.name for path in foreign_data.iterdir()) == ["sentinel"]


@pytest.mark.parametrize("outcome,expected_code", [("timeout", 1), ("interrupt", 130)])
def test_timeout_and_interrupt_reap_process_before_removing_sandbox(
    gate, tmp_path, monkeypatch, outcome, expected_code
):
    state = {}

    class FakeProcess:
        def wait(self, timeout):
            if outcome == "timeout":
                raise subprocess.TimeoutExpired("fake-tool", timeout)
            raise KeyboardInterrupt

    def fake_popen(command, *, cwd, env, start_new_session):
        state["sandbox"] = Path(env["TMPDIR"])
        state["process"] = FakeProcess()
        assert cwd == tmp_path
        assert start_new_session == (os.name == "posix")
        return state["process"]

    def fake_stop(process):
        assert process is state["process"]
        assert state["sandbox"].exists(), "资源目录应在停止子进程后清理"
        state["stopped"] = True

    monkeypatch.setattr(gate.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(gate, "stop_process", fake_stop)
    assert gate.run(("lint",), root=tmp_path, timeout=0.1) == expected_code
    assert state["stopped"] is True
    assert not state["sandbox"].exists()


def test_missing_tool_is_a_failed_gate_without_a_real_process(gate, tmp_path, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("fake missing tool")

    monkeypatch.setattr(gate.subprocess, "Popen", missing)
    assert gate.run(("types",), root=tmp_path, timeout=1) == 1
    assert gate.run((), root=tmp_path, timeout=1) == 2


@pytest.mark.skipif(os.name != "posix", reason="POSIX 进程组清理契约")
def test_process_group_is_killed_when_graceful_shutdown_times_out(gate, monkeypatch):
    signals = []

    class FakeProcess:
        pid = 12345
        calls = 0

        def poll(self):
            return None

        def wait(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("fake-child", timeout)
            return -signal.SIGKILL

    monkeypatch.setattr(gate.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    process = FakeProcess()
    gate.stop_process(process)
    assert signals == [(12345, signal.SIGTERM), (12345, signal.SIGKILL)]
    assert process.calls == 2


@pytest.mark.skipif(os.name != "posix", reason="POSIX 进程组清理契约")
@pytest.mark.parametrize("already_exited", [True, False])
def test_process_group_cleanup_does_not_stop_at_exited_leader(gate, monkeypatch, already_exited):
    signals = []

    class FakeProcess:
        pid = 12346
        done = already_exited

        def poll(self):
            return 0 if self.done else None

        def wait(self, timeout):
            self.done = True
            return 0

    monkeypatch.setattr(gate.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    gate.stop_process(FakeProcess())
    assert signals == [(12346, signal.SIGTERM), (12346, signal.SIGKILL)]


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_timeout_is_rejected_before_execution(gate, value):
    with pytest.raises(SystemExit) as exc:
        gate.main(["--timeout", value])
    assert exc.value.code == 2
