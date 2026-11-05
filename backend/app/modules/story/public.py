"""story 模块公开接口。

惰性导出避免启动时加载无关能力；内部实现仍由架构测试约束依赖方向。
"""

from importlib import import_module

_EXPORTS = {
    "latest_script_snapshot": ("app.modules.story.application.queries", "latest_script_snapshot"),
    "get_script_snapshot": ("app.modules.story.application.queries", "get_script_snapshot"),
    "assert_script_baseline_snapshot": (
        "app.modules.story.application.queries",
        "assert_script_baseline_snapshot",
    ),
    "generate_script_snapshot": ("app.modules.story.application.use_cases", "generate_script_snapshot"),
    "parse_project_document": ("app.modules.story.application.commands", "parse_project_document"),
    "latest_script": ("app.modules.story.application.queries", "latest_script"),
    "script_payload": ("app.modules.story.application.queries", "script_payload"),
    "script_text_of": ("app.modules.story.application.queries", "script_text_of"),
    "script_fingerprint": ("app.modules.story.application.queries", "script_fingerprint"),
    "assert_script_baseline": ("app.modules.story.application.queries", "assert_script_baseline"),
    "assert_script_baseline_reference": (
        "app.modules.story.application.queries",
        "assert_script_baseline_reference",
    ),
    "get_project_script": ("app.modules.story.application.queries", "get_project_script"),
    "list_script_versions": ("app.modules.story.application.queries", "list_script_versions"),
    "create_script_version": ("app.modules.story.application.workspace", "create_script_version"),
    "import_script_version": ("app.modules.story.application.workspace", "import_script_version"),
    "restore_script_version": ("app.modules.story.application.workspace", "restore_script_version"),
    "revise_script": ("app.modules.story.application.workspace", "revise_script"),
    "update_script": ("app.modules.story.application.use_cases", "update_script"),
    "generate_script": ("app.modules.story.application.use_cases", "generate_script"),
    "decode_text": ("app.modules.story.application.documents", "decode_text"),
    "extract_text": ("app.modules.story.application.documents", "extract_text"),
    "store_document": ("app.modules.story.application.documents", "store_document"),
    "parse_document": ("app.modules.story.application.documents", "parse_document"),
    "ingest_bytes": ("app.modules.story.application.documents", "ingest_bytes"),
    "ingest_sample": ("app.modules.story.application.documents", "ingest_sample"),
    "list_documents": ("app.modules.story.application.documents", "list_documents"),
    "chapters": ("app.modules.story.application.documents", "chapters"),
    "chapter_payloads": ("app.modules.story.application.documents", "chapter_payloads"),
    "chapter_public": ("app.modules.story.application.documents", "chapter_public"),
    "document_public": ("app.modules.story.application.documents", "document_public"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name):
    try:
        module, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(name) from None
    return getattr(import_module(module), attribute)


def __dir__():
    return sorted(set(globals()) | set(__all__))
