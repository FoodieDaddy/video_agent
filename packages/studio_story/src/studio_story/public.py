"""story 模块公开接口。

惰性导出避免启动时加载无关能力；内部实现仍由架构测试约束依赖方向。
"""

from importlib import import_module

_EXPORTS = {
    "latest_script_snapshot": ("studio_story.application.queries", "latest_script_snapshot"),
    "get_script_snapshot": ("studio_story.application.queries", "get_script_snapshot"),
    "assert_script_baseline_snapshot": (
        "studio_story.application.queries",
        "assert_script_baseline_snapshot",
    ),
    "generate_script_snapshot": ("studio_story.application.use_cases", "generate_script_snapshot"),
    "parse_project_document": ("studio_story.application.commands", "parse_project_document"),
    "latest_script": ("studio_story.application.queries", "latest_script"),
    "script_payload": ("studio_story.application.queries", "script_payload"),
    "script_text_of": ("studio_story.application.queries", "script_text_of"),
    "script_fingerprint": ("studio_story.application.queries", "script_fingerprint"),
    "assert_script_baseline": ("studio_story.application.queries", "assert_script_baseline"),
    "assert_script_baseline_reference": (
        "studio_story.application.queries",
        "assert_script_baseline_reference",
    ),
    "get_project_script": ("studio_story.application.queries", "get_project_script"),
    "list_script_versions": ("studio_story.application.queries", "list_script_versions"),
    "create_script_version": ("studio_story.application.workspace", "create_script_version"),
    "import_script_version": ("studio_story.application.workspace", "import_script_version"),
    "restore_script_version": ("studio_story.application.workspace", "restore_script_version"),
    "revise_script": ("studio_story.application.workspace", "revise_script"),
    "update_script": ("studio_story.application.use_cases", "update_script"),
    "generate_script": ("studio_story.application.use_cases", "generate_script"),
    "decode_text": ("studio_story.application.documents", "decode_text"),
    "extract_text": ("studio_story.application.documents", "extract_text"),
    "store_document": ("studio_story.application.documents", "store_document"),
    "parse_document": ("studio_story.application.documents", "parse_document"),
    "ingest_bytes": ("studio_story.application.documents", "ingest_bytes"),
    "ingest_sample": ("studio_story.application.documents", "ingest_sample"),
    "list_documents": ("studio_story.application.documents", "list_documents"),
    "chapters": ("studio_story.application.documents", "chapters"),
    "chapter_payloads": ("studio_story.application.documents", "chapter_payloads"),
    "chapter_public": ("studio_story.application.documents", "chapter_public"),
    "document_public": ("studio_story.application.documents", "document_public"),
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
