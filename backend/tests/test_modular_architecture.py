"""逻辑多模块迁移的架构约束。

检查运行中的兼容身份以及源码导入边界，不启动应用、数据库或模型请求。
兼容 shim 位于旧目录，允许向新模块转发；新实现不能再借道旧入口执行。
"""

from __future__ import annotations

import ast
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "backend" / "app" / "modules"
TECHNICAL_MODULES = {"platform", "ai_runtime", "contracts"}
# 这些是有意开放的技术命名接口，不允许任意跨入其他内部文件。
TECHNICAL_INTERFACES = {
    "ai_runtime": {
        "public",
        "base",
        "registry",
        "providers.base",
        "providers.registry",
    },
    "platform": {
        "public",
        "constants",
        "exceptions",
        "ids",
        "resources",
        "security",
        "storage",
        "configuration.settings",
        "configuration.config_models",
        "configuration.config_store",
        "execution.runtime",
        "execution.task_runner",
        "media.ffmpeg",
        "text.narrative",
        "persistence.base",
        "persistence.session",
        "persistence.task_records",
        "persistence.versions",
    },
    "contracts": {"public"},
}
LEGACY_PREFIXES = (
    "app.services",
    "app.core",
    "app.agents",
    "app.providers",
    "app.utils",
    "app.db",
)
COMPATIBLE_MODULES = (
    ("app.core.settings", "app.modules.platform.configuration.settings"),
    ("app.core.config_models", "app.modules.platform.configuration.config_models"),
    ("app.core.config_store", "app.modules.platform.configuration.config_store"),
    ("app.db.session", "app.modules.platform.persistence.session"),
    ("app.models.base", "app.modules.platform.persistence.base"),
    ("app.models.character", "app.modules.characters.infrastructure.persistence.models"),
    ("app.models.scene", "app.modules.scenes.infrastructure.persistence.models"),
    ("app.models.production", "app.modules.production.infrastructure.persistence.models"),
    ("app.models.story", "app.modules.story.infrastructure.persistence.models"),
    ("app.services.agent_runner", "app.modules.ai_runtime.application.execution"),
    ("app.providers.registry", "app.modules.ai_runtime.providers.registry"),
    ("app.agents.registry", "app.modules.ai_runtime.registry"),
    ("app.services.workflow", "app.modules.workflow.application.engine"),
    ("app.services.reviews", "app.modules.reviews.application.service"),
    ("app.services.documents", "app.modules.story.application.documents"),
)


@dataclass(frozen=True)
class ImportReference:
    """同时保留基模块与具体名字，以识别 from package import public 的形式。"""

    source: Path
    lineno: int
    module: str
    member: str | None = None

    @property
    def target(self) -> str:
        return f"{self.module}.{self.member}" if self.member else self.module

    def explain(self) -> str:
        return f"{self.source.relative_to(ROOT)}:{self.lineno}: {self.target}"


def python_module(path: Path) -> str:
    parts = list(path.relative_to(ROOT / "backend").with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def import_references(path: Path) -> list[ImportReference]:
    """不只检查顶层 import：函数内和 TYPE_CHECKING 依赖同样进入边界约束。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    references = []
    package = python_module(path)
    if path.name != "__init__.py":
        package = package.rsplit(".", 1)[0]
    import_module_names = {"import_module"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            import_module_names.update(
                alias.asname or alias.name for alias in node.names if alias.name == "import_module"
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            references.extend(ImportReference(path, node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = importlib.util.resolve_name("." * node.level + base, package)
            references.extend(ImportReference(path, node.lineno, base, alias.name) for alias in node.names)
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if not isinstance(value, str):
                continue
            direct_loader = isinstance(node.func, ast.Name) and node.func.id in {
                *import_module_names,
                "__import__",
            }
            qualified_loader = (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib"
                and node.func.attr == "import_module"
            )
            if direct_loader or qualified_loader:
                references.append(ImportReference(path, node.lineno, value))
    return references


def module_sources() -> list[Path]:
    files = sorted(MODULES.rglob("*.py"))
    assert files, "模块源码不存在，架构检查不能空执行"
    return files


def owner_of(name: str) -> str | None:
    parts = name.split(".")
    return parts[2] if len(parts) >= 3 and parts[:2] == ["app", "modules"] else None


def is_public_target(reference: ImportReference, destination: str) -> bool:
    prefix = f"app.modules.{destination}."
    if reference.member and reference.member.startswith("_"):
        return False
    entries = []
    if reference.module.startswith(prefix):
        entry = reference.module[len(prefix) :]
        entries.append(entry)
        if reference.member and reference.member != "*":
            entries.append(f"{entry}.{reference.member}")
    elif reference.module == f"app.modules.{destination}" and reference.member:
        entries.append(reference.member)
    if destination in TECHNICAL_MODULES:
        return any(entry in TECHNICAL_INTERFACES[destination] for entry in entries)
    return any(
        entry == "public"
        or entry.startswith("public.")
        or entry == "contracts"
        or entry.startswith("contracts.")
        for entry in entries
    )


@pytest.mark.parametrize(("legacy", "canonical"), COMPATIBLE_MODULES)
def test_legacy_entrypoints_keep_the_same_module_object(legacy, canonical):
    """尤其保护配置根、Session工厂和执行拦截点，不产生两套全局状态。"""
    assert importlib.import_module(legacy) is importlib.import_module(canonical)


def test_orm_metadata_and_agent_catalog_have_single_sources():
    from app import models
    from app.bootstrap.agent_catalog import AGENT_FAMILIES, builtin_agent_classes
    from app.modules.ai_runtime.registry import AGENT_CLASSES, agent_ids
    from app.modules.platform.persistence.base import Base

    assert models.Base is Base
    mapped = {
        cls
        for cls in vars(models).values()
        if isinstance(cls, type) and hasattr(cls, "__table__") and issubclass(cls, Base)
    }
    assert len(mapped) >= 20, "没有完整注册业务映射，不能只验证一个空Base"
    assert {"projects", "scripts", "characters", "scenes", "reviews", "agent_runs"} <= set(
        Base.metadata.tables
    )
    assert len({cls.__table__.fullname for cls in mapped}) == len(mapped)
    assert all(cls.__table__.metadata is Base.metadata for cls in mapped)
    assert all(Base.metadata.tables[cls.__table__.fullname] is cls.__table__ for cls in mapped)
    assert all(cls.__module__.startswith("app.modules.") for cls in mapped)

    ids = agent_ids()
    flattened = [agent_id for family in AGENT_FAMILIES.values() for agent_id in family]
    assert len(AGENT_FAMILIES) == 13
    assert len(ids) == len(flattened) == len(set(flattened)) == 17
    assert set(flattened) == set(ids) == set(builtin_agent_classes())
    for agent_id, implementation in builtin_agent_classes().items():
        assert AGENT_CLASSES[agent_id] is implementation
        assert implementation.agent_id == agent_id
        assert implementation.__module__.startswith("app.modules.")


def test_legacy_model_aggregators_reexport_the_canonical_classes():
    from app.models.ops import (
        AgentRun,
        AssetVersion,
        ModelCallLog,
        Review,
        ReviewComment,
        Task,
        TaskEvent,
        WorkflowCheckpoint,
        WorkflowRun,
    )
    from app.models.project import (
        Asset,
        BudgetEvent,
        ConfigVersion,
        Project,
        ProjectMember,
        PromptVersion,
        User,
    )
    from app.modules.ai_runtime.infrastructure.persistence.models import AgentRun as CanonicalAgentRun
    from app.modules.ai_runtime.infrastructure.persistence.models import (
        BudgetEvent as CanonicalBudgetEvent,
    )
    from app.modules.ai_runtime.infrastructure.persistence.models import (
        ModelCallLog as CanonicalModelCallLog,
    )
    from app.modules.assets.infrastructure.persistence.models import Asset as CanonicalAsset
    from app.modules.assets.infrastructure.persistence.models import (
        AssetVersion as CanonicalAssetVersion,
    )
    from app.modules.configuration.infrastructure.persistence.models import (
        ConfigVersion as CanonicalConfigVersion,
    )
    from app.modules.configuration.infrastructure.persistence.models import (
        PromptVersion as CanonicalPromptVersion,
    )
    from app.modules.platform.persistence.models import Task as CanonicalTask
    from app.modules.platform.persistence.models import TaskEvent as CanonicalTaskEvent
    from app.modules.projects.infrastructure.persistence.models import Project as CanonicalProject
    from app.modules.projects.infrastructure.persistence.models import (
        ProjectMember as CanonicalProjectMember,
    )
    from app.modules.projects.infrastructure.persistence.models import User as CanonicalUser
    from app.modules.reviews.infrastructure.persistence.models import Review as CanonicalReview
    from app.modules.reviews.infrastructure.persistence.models import (
        ReviewComment as CanonicalReviewComment,
    )
    from app.modules.workflow.infrastructure.persistence.models import (
        WorkflowCheckpoint as CanonicalWorkflowCheckpoint,
    )
    from app.modules.workflow.infrastructure.persistence.models import WorkflowRun as CanonicalWorkflowRun

    pairs = (
        (AgentRun, CanonicalAgentRun),
        (AssetVersion, CanonicalAssetVersion),
        (ModelCallLog, CanonicalModelCallLog),
        (Review, CanonicalReview),
        (ReviewComment, CanonicalReviewComment),
        (Task, CanonicalTask),
        (TaskEvent, CanonicalTaskEvent),
        (WorkflowCheckpoint, CanonicalWorkflowCheckpoint),
        (WorkflowRun, CanonicalWorkflowRun),
        (Asset, CanonicalAsset),
        (BudgetEvent, CanonicalBudgetEvent),
        (ConfigVersion, CanonicalConfigVersion),
        (Project, CanonicalProject),
        (ProjectMember, CanonicalProjectMember),
        (PromptVersion, CanonicalPromptVersion),
        (User, CanonicalUser),
    )
    assert all(legacy is canonical for legacy, canonical in pairs)


def test_cross_module_imports_use_public_or_declared_technical_interfaces():
    violations = []
    owners = set()
    for path in module_sources():
        source = owner_of(python_module(path))
        if source is None:
            continue
        owners.add(source)
        for reference in import_references(path):
            destination = owner_of(reference.target)
            if destination and destination != source and not is_public_target(reference, destination):
                violations.append(reference.explain())
    assert {"story", "characters", "scenes", "production", "reviews", "workflow"} <= owners
    assert not violations, "跨模块导入越过公开边界：\n" + "\n".join(violations)


def test_module_dependencies_form_an_acyclic_graph():
    graph: dict[str, set[str]] = {}
    for path in module_sources():
        source = owner_of(python_module(path))
        if source is None:
            continue
        graph.setdefault(source, set())
        for reference in import_references(path):
            destination = owner_of(reference.target)
            if destination and destination != source:
                graph[source].add(destination)
    visiting: list[str] = []
    finished: set[str] = set()

    def visit(module: str) -> None:
        assert module not in visiting, "模块循环依赖：" + " -> ".join([*visiting, module])
        if module in finished:
            return
        visiting.append(module)
        for dependency in sorted(graph.get(module, ())):
            visit(dependency)
        visiting.pop()
        finished.add(module)

    for module in sorted(graph):
        visit(module)


def test_new_modules_do_not_import_legacy_implementation_entrypoints():
    violations = []
    for path in module_sources():
        for reference in import_references(path):
            if any(
                reference.target == prefix or reference.target.startswith(prefix + ".")
                for prefix in LEGACY_PREFIXES
            ):
                violations.append(reference.explain())
    assert not violations, "新实现反向依赖旧兼容入口：\n" + "\n".join(violations)


def test_domain_rules_use_only_standard_library_and_their_own_domain():
    domains = [path for path in module_sources() if "domain" in path.relative_to(MODULES).parts]
    assert domains, "尚未提取任何领域规则，不能空执行领域依赖检查"
    violations = []
    for path in domains:
        owner = owner_of(python_module(path))
        for reference in import_references(path):
            dependency = reference.module.split(".", 1)[0]
            own_domain = f"app.modules.{owner}.domain"
            if dependency in sys.stdlib_module_names or dependency == "__future__":
                continue
            if reference.target == own_domain or reference.target.startswith(own_domain + "."):
                continue
            violations.append(reference.explain())
    assert not violations, "领域规则依赖了技术框架或外部模块：\n" + "\n".join(violations)


def test_business_modules_follow_standard_layer_package_layout():
    """业务模块的分层目录保持一致；空层仅代表预留边界，不代表已实现功能。"""
    business_modules = (
        "projects",
        "story",
        "characters",
        "scenes",
        "production",
        "reviews",
        "workflow",
        "assets",
        "configuration",
    )
    for name in business_modules:
        module = MODULES / name
        for layer in ("domain", "application", "infrastructure", "interfaces"):
            assert (module / layer / "__init__.py").is_file(), f"{name} 缺少 {layer} 层"
        assert (module / "public.py").is_file(), f"{name} 缺少 public.py"
        assert (module / "README.md").is_file(), f"{name} 缺少模块说明"


def test_agent_catalogs_are_owned_by_business_modules():
    """具体 Agent 类由业务模块声明，bootstrap 只做汇总，不再集中维护实现映射。"""
    from app.bootstrap.agent_catalog import builtin_agent_classes
    from app.modules.characters.infrastructure.agents.catalog import AGENTS as characters
    from app.modules.production.infrastructure.agents.catalog import AGENTS as production
    from app.modules.scenes.infrastructure.agents.catalog import AGENTS as scenes
    from app.modules.story.infrastructure.agents.catalog import AGENTS as story
    from app.modules.workflow.infrastructure.agents.catalog import AGENTS as workflow

    catalogs = (characters, production, scenes, story, workflow)
    ids = [agent_id for catalog in catalogs for agent_id in catalog]
    assert len(ids) == len(set(ids)) == 17
    assert set(builtin_agent_classes()) == set(ids)
    for catalog in catalogs:
        for agent_id, agent_class in catalog.items():
            assert agent_class.agent_id == agent_id
            assert agent_class.__module__.startswith("app.modules.")
