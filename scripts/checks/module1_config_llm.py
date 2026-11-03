r"""模块 1：配置层 + 文字模型接入（config -> provider -> qwen chat）。

本文件是"分模块测试"的第一个模块，只回答一个问题：

    YAML 里的供应商/智能体配置，能不能真正变出一个可用的文字模型客户端，
    并成功拿到一份结构化 JSON？

模块边界（本文件覆盖的代码，按调用顺序）：

    1. config/providers/llm.yaml          qwen 供应商：url / api_key / models / extra.request_defaults
    2. config/agents/*.yaml               每个智能体的 model.provider / model.model_id
    3. app/core/config_store.py           读 YAML -> ProviderConfig / AgentConfig
    4. app/providers/registry.py          resolve_provider_config -> build_provider -> get_llm
    5. app/providers/openai_compat.py     OpenAICompatibleLLMProvider.generate + _extract_json
    6. 消费方 app/agents/base.py          _provider_for() / _call()（本模块只测到 provider，不跑智能体）

本模块【不】做的事（留给后续模块，所以可以反复运行，不写任何业务数据）：

    - 不连数据库、不建项目、不解析小说、不跑工作流
    - 不调用视频/图片/语音模型
    - 不启动 HTTP 服务（直接 import 服务层代码）

七项检查（前五项离线，第六项真实调用一次，第七项纯单元）：

    1 settings + ConfigStore   配置目录、YAML 能否读进来、智能体数量
    2 enabled providers        哪些供应商启用、协议、URL、是否拿到密钥
    3 agent -> model mapping   17 个智能体分别指向哪个供应商/模型
    4 provider factory         get_llm() 是否产出 OpenAICompatibleLLMProvider，
                               以及 request_defaults(reasoning_effort) 是否带上了
    5 api key resolution       env:QWEN_API_KEY -> .env 里的值（打码显示）
    6 live chat call           真实发一次结构化请求，检查 tokens / latency / JSON
    7 json extraction          模型输出里混着思考过程（</think>）时的解析能力

用法（在仓库根目录执行）：

    .\.venv\Scripts\python.exe scripts\checks\module1_config_llm.py
    .\.venv\Scripts\python.exe scripts\checks\module1_config_llm.py --offline
    .\.venv\Scripts\python.exe scripts\checks\module1_config_llm.py --agent director --verbose

退出码：0 = 全部通过；1 = 有失败项（失败项会打印处理建议）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# 让脚本既能直接运行，也能被 pytest / 其他脚本 import。
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config_models import GenerationConfig  # noqa: E402
from app.core.config_store import ConfigStore  # noqa: E402
from app.core.settings import Settings, load_settings  # noqa: E402
from app.providers import registry  # noqa: E402
from app.providers.base import LLMProvider, LLMRequest  # noqa: E402
from app.providers.openai_compat import _extract_json  # noqa: E402

# 智能体 YAML 里的 model.capability 只是文档字段；真正决定"去哪个供应商文件里找"
# 的是下面这张能力->文件(stem)的对应表（llm.yaml / vision.yaml / image.yaml ...）。
CAPABILITY_BUCKETS = {
    "text_reasoning": "llm",
    "vision": "vision",
    "image_generation": "image",
    "speech_synthesis": "audio",
    "video_generation": "video",
}

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


@dataclass
class Report:
    """收集每一步的结果，最后统一打印结论。"""

    rows: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.rows.append((name, status, detail))
        print(f"[{status}] {name:<32s} {detail}")

    @property
    def failed(self) -> list[tuple[str, str, str]]:
        return [row for row in self.rows if row[1] == FAIL]


def _mask(value: str) -> str:
    """密钥打码：保留前 3 位和后 2 位，便于确认"读到了哪一个值"又不泄露。"""
    if not value:
        return "<empty>"
    if len(value) <= 5:
        return "*" * len(value)
    return f"{value[:3]}***{value[-2:]}"


def check_config(settings: Settings, report: Report) -> tuple[ConfigStore | None, list[str]]:
    """第 1 步：配置目录结构 + YAML 加载。"""
    problems: list[str] = []
    for sub in ("providers", "agents", "workflows"):
        if not (settings.config_dir / sub).is_dir():
            problems.append(f"missing {settings.config_dir / sub}")
    try:
        store = ConfigStore(settings)
    except Exception as exc:  # YAML 语法错误会在这里炸
        report.add("1 settings + ConfigStore", FAIL, f"{type(exc).__name__}: {exc}")
        return None, problems

    agent_ids = store.agent_ids()
    if not agent_ids:
        problems.append("no agents loaded from config/agents/*.yaml")
    dotenv = ROOT / ".env"
    detail = (
        f"config={settings.config_dir} agents={len(agent_ids)} "
        f"dotenv={'yes' if dotenv.is_file() else 'no'}"
    )
    report.add("1 settings + ConfigStore", PASS if not problems else FAIL, detail)
    return store, problems


def check_providers(store: ConfigStore, report: Report) -> None:
    """第 2 步：列出启用的供应商，确认文字模型那一桶有可用的密钥。"""
    print("\n  capability  name          protocol        key  url")
    enabled_llm_with_key = 0
    for capability in ("llm", "vision", "image", "video", "audio"):
        for name, config in sorted(store.providers(capability).items()):
            if not config.enabled:
                continue
            has_key = bool(config.resolved_api_key())
            if capability == "llm" and has_key:
                enabled_llm_with_key += 1
            print(
                f"  {capability:<11s} {name:<13s} {config.protocol_name():<15s} "
                f"{'yes' if has_key else 'no ':3s}  {config.resolved_url() or '-'}"
            )
    ok = enabled_llm_with_key >= 1
    detail = f"{enabled_llm_with_key} enabled llm provider(s) with api key"
    report.add("2 enabled providers", PASS if ok else FAIL, detail)
    if not ok:
        print("     hint: config/providers/llm.yaml -> enabled: true, api_key: env:NAME, "
              "and NAME must exist in .env")


def check_agent_mapping(store: ConfigStore, report: Report) -> dict[str, list[str]]:
    """第 3 步：每个智能体指向哪个供应商/模型；供应商名写错在这里就能发现。"""
    known = {
        name
        for capability in ("llm", "vision", "image", "video", "audio")
        for name in store.providers(capability)
    }
    groups: dict[tuple[str, str], list[str]] = {}
    unknown: list[str] = []
    bucket_warnings: list[str] = []
    for agent_id in store.agent_ids():
        model = store.agent(agent_id).model
        groups.setdefault((model.provider, model.model_id), []).append(agent_id)
        if model.provider not in known:
            unknown.append(
                f"{agent_id} -> provider '{model.provider}' is not defined in any providers/*.yaml"
            )
            continue
        expected_bucket = CAPABILITY_BUCKETS.get(model.capability)
        if expected_bucket and model.provider not in store.providers(expected_bucket):
            bucket_warnings.append(
                f"{agent_id}: capability={model.capability} expects {expected_bucket}.yaml, "
                f"but provider '{model.provider}' is declared elsewhere"
            )

    print("\n  provider      model            agents")
    for (provider, model_id), agents in sorted(groups.items()):
        print(f"  {provider:<13s} {model_id:<16s} {len(agents):2d}  {', '.join(sorted(agents))}")
    for warning in bucket_warnings:
        print(f"  WARN {warning}")
    detail = f"{len(store.agent_ids())} agents -> {len(groups)} provider/model pairs"
    ok = not unknown
    report.add("3 agent -> model mapping", PASS if ok else FAIL, detail)
    for item in unknown:
        print(f"     error: {item}")
    return {f"{k[0]}/{k[1]}": v for k, v in groups.items()}


def check_factory(store: ConfigStore, agent_id: str, report: Report) -> LLMProvider | None:
    """第 4 步：走 registry.get_llm()，看能不能造出真正的 LLM 客户端。

    这一步是"配置 -> 代码"的交汇点：
      AgentConfig.model (provider/model_id)
        -> resolve_provider_config()  取出并校验 qwen 配置（enabled / api_key）
        -> _provider_options()        拼出 api_key / base_url / timeout / extra
        -> OpenAICompatibleLLMProvider(name, model_id, options)
    """
    try:
        model = store.agent(agent_id).model
        provider = registry.get_llm(store, model)
    except Exception as exc:
        report.add("4 provider factory", FAIL, f"{type(exc).__name__}: {exc}")
        return None

    problems: list[str] = []
    if not isinstance(provider, LLMProvider):
        problems.append(f"{type(provider).__name__} 不是 LLMProvider")
    if provider.model_id != model.model_id:
        problems.append(f"model_id 不一致: {provider.model_id} != {model.model_id}")
    base_url = provider.options.get("base_url") or ""
    if not base_url:
        problems.append("options.base_url 为空（url 未解析）")
    defaults = provider.options.get("request_defaults") or {}
    # qwen 这条链路依赖 provider 级 request_defaults 才不会被服务端 400 拒绝。
    if model.provider == "qwen" and not defaults.get("reasoning_effort"):
        problems.append("request_defaults.reasoning_effort 缺失，vLLM 会返回 400")

    detail = (
        f"{type(provider).__name__} name={provider.name} model={provider.model_id} "
        f"url={base_url} timeout={provider.options.get('timeout_seconds')}s "
        f"defaults={defaults or '-'}"
    )
    report.add("4 provider factory", PASS if not problems else FAIL, detail)
    for item in problems:
        print(f"     error: {item}")
    return provider


def check_keys(store: ConfigStore, report: Report) -> None:
    """第 5 步：api_key: env:NAME 这种写法，到底解析成了什么（打码）。"""
    print("\n  provider      declared source        resolved")
    problems: list[str] = []
    seen = 0
    for capability in ("llm", "vision", "image", "video", "audio"):
        for name, config in sorted(store.providers(capability).items()):
            if not config.enabled or not config.declares_api_key():
                continue
            seen += 1
            value = config.resolved_api_key()
            if not value:
                problems.append(f"{name}: {config.api_key_source()} 解析为空")
            print(f"  {capability}/{name:<11s} {config.api_key_source():<20s} {_mask(value)}")
    ok = seen > 0 and not problems
    detail = f"{seen} provider(s) declared a key, {len(problems)} unresolved"
    report.add("5 api key resolution", PASS if ok else FAIL, detail)
    for item in problems:
        print(f"     hint: add the missing value to .env -> {item}")


async def call_once(provider: LLMProvider, max_tokens: int) -> tuple[object, float]:
    """第 6 步的核心：一次真实的结构化调用（与智能体走同一条 generate()）。"""
    request = LLMRequest(
        system="You are a contract test for module 1. Answer with JSON only.",
        user='Return exactly this JSON object, nothing else: {"ok": true, "module": "m1"}',
        schema_name="module1_probe",
        # 只要 response_schema 非空，provider 就会加 response_format 并尝试解析 JSON。
        response_schema={"type": "object", "required": ["ok"]},
        generation=GenerationConfig(temperature=0.2, max_output_tokens=max_tokens),
    )
    started = time.perf_counter()
    result = await provider.generate(request)
    return result, time.perf_counter() - started


def check_live(provider: LLMProvider, report: Report, offline: bool, verbose: bool) -> None:
    """第 6 步：真实网络调用（--offline 时跳过）。"""
    if offline:
        report.add("6 live chat call", SKIP, "skipped by --offline")
        return
    try:
        result, wall = asyncio.run(call_once(provider, max_tokens=192))
    except Exception as exc:
        detail = f"{type(exc).__name__}: {str(exc)[:220]}"
        report.add("6 live chat call", FAIL, detail)
        print("     hint: 400 with 'Unexpected reasoning effort' -> request_defaults was dropped;")
        print("           401/403 -> wrong key in .env; connection error -> port 8000 is not up")
        return

    problems: list[str] = []
    if not getattr(result, "tokens_out", 0):
        problems.append("completion_tokens=0")
    if getattr(result, "structured", None) is None:
        problems.append("structured is None even though response_schema was provided")
    elif result.structured.get("ok") is not True:
        problems.append(f"JSON content does not match the contract: {result.structured}")
    latency = result.meta.get("latency_ms", 0) if isinstance(result.meta, dict) else 0
    detail = (
        f"wall={wall:.1f}s provider_latency={latency}ms "
        f"in={result.tokens_in} out={result.tokens_out} model={result.model_id}"
    )
    report.add("6 live chat call", PASS if not problems else FAIL, detail)
    for item in problems:
        print(f"     error: {item}")
    if verbose:
        text = (result.text or "").replace("\n", "\\n")
        print(f"     raw text: {text[:220]}")
        print(f"     structured: {result.structured}")


def check_extraction(report: Report, verbose: bool) -> None:
    """第 7 步：纯单元检查——模型输出带思考过程时，JSON 还能不能取出来。"""
    cases: list[tuple[str, str, dict]] = [
        ("plain", '{"ok": true}', {"ok": True}),
        ("nested", '{"a": {"b": 1}}', {"a": {"b": 1}}),
        ("trace", 'The user wants JSON.\n</think>{"ok": true}', {"ok": True}),
        ("fenced", '```json\n{"ok": true}\n```', {"ok": True}),
    ]
    problems: list[str] = []
    for name, text, expected in cases:
        try:
            got = _extract_json(text)
        except Exception as exc:
            problems.append(f"{name}: raised {type(exc).__name__}")
            continue
        if got != expected:
            problems.append(f"{name}: expected {expected} got {got}")
        elif verbose:
            print(f"     {name}: {got}")
    # 完全不是 JSON 时必须抛错，而不是返回空 dict（否则上层会把脏数据写库）。
    try:
        _extract_json("no json here at all")
    except Exception:
        pass
    else:
        problems.append("negative: non-JSON input did not raise")

    detail = f"{len(cases) + 1} cases, {len(problems)} failed"
    report.add("7 json extraction", PASS if not problems else FAIL, detail)
    for item in problems:
        print(f"     error: {item}")


def run(agent_id: str = "script", offline: bool = False, verbose: bool = False) -> int:
    report = Report()
    print("=== Module 1: config -> provider -> text model ===")
    settings = load_settings()
    print(f"config dir : {settings.config_dir}")
    print(f"data dir   : {settings.data_dir}")

    store, problems = check_config(settings, report)
    for item in problems:
        print(f"     error: {item}")
    if store is None:
        return _summary(report)

    check_providers(store, report)
    check_agent_mapping(store, report)

    if store.try_agent(agent_id) is None:
        report.add("4 provider factory", FAIL, f"agent '{agent_id}' not found")
        provider = None
    else:
        provider = check_factory(store, agent_id, report)

    check_keys(store, report)
    if provider is not None:
        check_live(provider, report, offline=offline, verbose=verbose)
    else:
        report.add("6 live chat call", SKIP, "no provider instance")
    check_extraction(report, verbose=verbose)
    return _summary(report)


def _summary(report: Report) -> int:
    total = len(report.rows)
    failed = report.failed
    print("\n" + "-" * 72)
    for name, status, _detail in report.rows:
        print(f"{status:<5s} {name}")
    if failed:
        print(f"RESULT: {len(failed)}/{total} FAILED -> fix the failures above before module 2")
        return 1
    print(f"RESULT: {total - sum(1 for row in report.rows if row[1] == SKIP)}/{total} passed")
    print("NEXT  : module 2 (script agent) - novel chapters in, structured script out")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Module 1 check: config + text model wiring")
    parser.add_argument("--agent", default="script", help="borrow provider/model from this agent")
    parser.add_argument("--offline", action="store_true", help="skip the live network call")
    parser.add_argument("--verbose", action="store_true", help="print raw provider output")
    args = parser.parse_args(argv)
    return run(agent_id=args.agent, offline=args.offline, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
