"""Enforce the dependency rule from ADR 0018 and docs/source-layout.md.

Every ``.py`` file under ``src/avianki/`` is parsed with ``ast``; nothing is imported or
executed. Each module is matched to the most specific entry in ``RULES`` and every
``avianki`` import it makes must fall inside that entry's allowed set.

Later milestones should only need to edit the data tables below, and must keep them in
sync with the "dependency rule" section of docs/source-layout.md.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "src" / "avianki"
WEB_DIR = REPO_ROOT / "web"

PKG = "avianki"

# Placeholder in an allowed list meaning "the importer's own package under the rule's
# ``.*``", e.g. for ``avianki.sources.gbif.parse`` it is ``avianki.sources.gbif``.
OWN = "<own>"

# Rule keys:
#   "a.b"   matches a.b and everything below it
#   "a.b.*" matches everything strictly below a.b (more specific than "a.b")
# The most specific (deepest) matching key wins. Allowed entries use the same syntax.
# A rule lists its own slice explicitly; there is no implicit "may import itself",
# because a package __init__ importing its own submodules is exactly how catalog/__init__
# could smuggle catalog.build downstream.
#
# Allowed entries are compared against the *imported name*: ``from avianki.x import y``
# is recorded as ``avianki.x.y``, so an entry can grant a single name (see cli below).
RULES: dict[str, tuple[str, ...]] = {
    # The package root runs whenever anything in avianki is imported, so it may pull in
    # nothing that could smuggle upstream code downstream.
    # (Handled as an exact match; see ROOT_ALLOWED.)
    #
    # core/ imports nothing from avianki.
    "avianki.core": ("avianki.core",),
    # taxonomy/ -> core.
    "avianki.taxonomy": ("avianki.core", "avianki.taxonomy"),
    # sources/__init__ runs before any concrete source, so it may re-export the
    # contract (which is core-only) but never the registry or a concrete source.
    "avianki.sources": ("avianki.core", "avianki.taxonomy", "avianki.sources.contract"),
    "avianki.sources.contract": (
        "avianki.core",
        "avianki.taxonomy",
        "avianki.sources.contract",
    ),
    # The registry's job is to import the concrete sources and register them.
    "avianki.sources.registry": (
        "avianki.core",
        "avianki.taxonomy",
        "avianki.sources.contract",
        "avianki.sources.registry",
        "avianki.sources.*",
    ),
    # A concrete source: core, taxonomy, the contract and itself. Never the registry,
    # another source, catalog/ or deck/.
    "avianki.sources.*": (
        "avianki.core",
        "avianki.taxonomy",
        "avianki.sources.contract",
        OWN,
    ),
    # media/ -> core.
    "avianki.media": ("avianki.core", "avianki.media"),
    # catalog/__init__ runs whenever deck/ or cli imports catalog.format or catalog.client,
    # so it must be as downstream-safe as they are.
    "avianki.catalog": (
        "avianki.core",
        "avianki.catalog.format",
        "avianki.catalog.client",
    ),
    # The rest of catalog/ is the upstream pipeline.
    "avianki.catalog.*": (
        "avianki.core",
        "avianki.taxonomy",
        "avianki.sources",
        "avianki.media",
        "avianki.catalog",
    ),
    # format and client are the boundary the downstream side depends on; importing
    # sources/ or media/ from them would smuggle upstream code into deck/ and cli.
    "avianki.catalog.format": ("avianki.core", "avianki.catalog.format"),
    "avianki.catalog.client": (
        "avianki.core",
        "avianki.catalog.format",
        "avianki.catalog.client",
    ),
    # deck/ is downstream: never sources/, media/ or taxonomy/.
    "avianki.deck": (
        "avianki.core",
        "avianki.catalog.format",
        "avianki.catalog.client",
        "avianki.deck",
    ),
    # cli is downstream. The single crossing is --ebird calling build_ebird_species(), the one
    # public function of catalog/adhoc.py, which holds the upstream work (eBird, live media
    # building) so cli itself imports no source, media or pipeline code. Amended in M5: the
    # crossing was build_species() before adhoc.py existed.
    "avianki.cli": (
        "avianki.core",
        "avianki.catalog.format",
        "avianki.catalog.client",
        "avianki.deck",
        "avianki.catalog.adhoc",
    ),
    "avianki.catalog_cli": (
        "avianki.core",
        "avianki.taxonomy",
        "avianki.sources",
        "avianki.media",
        "avianki.catalog",
    ),
    # CLI-only helper, until Description->Name returns.
    "avianki.redact": ("avianki.core", "avianki.redact"),
}

ROOT_ALLOWED: tuple[str, ...] = ("avianki.core",)

@dataclass(frozen=True)
class Module:
    name: str
    is_package: bool


def _matches(pattern: str, name: str) -> bool:
    if pattern.endswith(".*"):
        return name.startswith(pattern[:-1])
    return name == pattern or name.startswith(pattern + ".")


def _specificity(pattern: str) -> int:
    if pattern.endswith(".*"):
        return 2 * pattern.count(".") + 1  # between its base and a named child
    return 2 * (pattern.count(".") + 1)


def rule_for(module: str) -> str | None:
    """Return the most specific RULES key covering ``module``, or None."""
    if module == PKG:
        return PKG
    keys = [k for k in RULES if _matches(k, module)]
    return max(keys, key=_specificity) if keys else None


def _allowed_for(module: str, key: str) -> list[str]:
    if key == PKG:
        return list(ROOT_ALLOWED)
    allowed = []
    for entry in RULES[key]:
        if entry == OWN:
            depth = key.count(".")  # "a.b.*" -> own package is the first 3 components
            allowed.append(".".join(module.split(".")[: depth + 1]))
        else:
            allowed.append(entry)
    return allowed


def _resolve_relative(module: Module, level: int, target: str | None) -> str | None:
    package = module.name if module.is_package else module.name.rpartition(".")[0]
    parts = package.split(".")
    if level - 1 >= len(parts):
        return None
    base = parts[: len(parts) - (level - 1)]
    return ".".join(base + ([target] if target else []))


def imported_names(module: Module, source: str) -> list[tuple[int, str]]:
    """Every absolute module name ``source`` imports, with line numbers.

    Walks the whole tree, so imports inside functions and inside ``if TYPE_CHECKING:``
    blocks count too: types can smuggle coupling just as well as runtime imports.
    ``from x import y`` is recorded as ``x.y`` (y may be a submodule or a name; the rule
    tables match by prefix, so either works). Constant-string ``importlib.import_module``
    and ``__import__`` calls count as well.
    """
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _resolve_relative(module, node.level, node.module)
                if base is None:
                    found.append(
                        (node.lineno, "<relative import beyond top-level package>")
                    )
                    continue
            else:
                base = node.module or ""
            for alias in node.names:
                found.append(
                    (node.lineno, base if alias.name == "*" else f"{base}.{alias.name}")
                )
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            fname = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", None)
            )
            arg = node.args[0]
            if (
                fname in {"import_module", "__import__"}
                and isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and not arg.value.startswith(".")
            ):
                found.append((node.lineno, arg.value))
    return found


def check_module(module: Module, source: str, where: str = "") -> list[str]:
    """Return one human-readable line per dependency-rule violation in ``source``."""
    where = where or module.name
    key = rule_for(module.name)
    if key is None:
        return [
            f"{where}: no layer rule for {module.name!r}. "
            f"Add a rule for {module.name} in tests/test_layout.py and docs/source-layout.md."
        ]
    allowed = _allowed_for(module.name, key)
    problems = []
    for lineno, target in imported_names(module, source):
        if target.startswith("<"):
            problems.append(f"{where}:{lineno}: {target}")
            continue
        if not _matches(PKG, target):
            continue
        if any(_matches(a, target) for a in allowed):
            continue
        problems.append(
            f"{where}:{lineno}: {module.name} (rule {key!r}) may not import {target}"
        )
    return problems


def module_name(path: Path, package_dir: Path) -> Module:
    rel = path.relative_to(package_dir.parent).with_suffix("")
    parts = list(rel.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return Module(".".join(parts), is_package)


def check_tree(package_dir: Path) -> list[str]:
    files = sorted(package_dir.rglob("*.py"))
    modules = {path: module_name(path, package_dir) for path in files}
    problems = []

    seen: dict[str, Path] = {}
    for path, mod in modules.items():
        if mod.name in seen:
            problems.append(
                f"{mod.name} is defined twice: {seen[mod.name].relative_to(REPO_ROOT)} "
                f"and {path.relative_to(REPO_ROOT)} (the package shadows the flat module)"
            )
        seen[mod.name] = path

    for path, mod in modules.items():
        where = path.relative_to(REPO_ROOT).as_posix()
        problems.extend(check_module(mod, path.read_text(encoding="utf-8"), where))
    return problems


# --- the real tree -----------------------------------------------------------------


def test_source_tree_follows_dependency_rule() -> None:
    problems = check_tree(PACKAGE_DIR)
    assert not problems, "Dependency rule violations (ADR 0018):\n  " + "\n  ".join(
        problems
    )


def test_web_contains_no_python() -> None:
    if not WEB_DIR.exists():
        pytest.skip("web/ doesn't exist yet")
    py_files = [p.relative_to(REPO_ROOT).as_posix() for p in WEB_DIR.rglob("*.py")]
    assert not py_files, f"web/ imports no Python (ADR 0018), but contains: {py_files}"


# --- the checker itself ------------------------------------------------------------


def _check(name: str, source: str, *, package: bool = False):
    return check_module(Module(name, package), source)


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("avianki.core.http", "avianki.core"),
        ("avianki.sources", "avianki.sources"),
        ("avianki.sources.contract", "avianki.sources.contract"),
        ("avianki.sources.gbif", "avianki.sources.*"),
        ("avianki.sources.gbif.parse", "avianki.sources.*"),
        ("avianki.catalog", "avianki.catalog"),
        ("avianki.catalog.build", "avianki.catalog.*"),
        ("avianki.catalog.format", "avianki.catalog.format"),
        ("avianki.catalog_cli", "avianki.catalog_cli"),
        ("avianki", "avianki"),
        ("avianki.shiny_new_thing", None),
    ],
)
def test_rule_for_picks_most_specific(module: str, expected: str | None) -> None:
    assert rule_for(module) == expected


def test_deck_importing_a_source_is_a_violation() -> None:
    problems = _check("avianki.deck.x", "import avianki.sources.gbif\n")
    assert len(problems) == 1
    assert "may not import avianki.sources.gbif" in problems[0]


def test_deck_may_import_catalog_format() -> None:
    assert (
        _check("avianki.deck.x", "from avianki.catalog.format import Species\n") == []
    )


def test_deck_may_not_import_taxonomy() -> None:
    assert _check("avianki.deck.x", "from avianki.taxonomy import species\n")


def test_from_package_import_counts_as_the_submodule() -> None:
    problems = _check("avianki.deck.x", "from avianki import sources\n")
    assert problems and "avianki.sources" in problems[0]


def test_relative_import_is_resolved() -> None:
    # avianki/deck/x.py: ..sources -> avianki.sources
    assert _check("avianki.deck.x", "from ..sources import gbif\n")
    # avianki/deck/__init__.py: . is avianki.deck itself
    assert _check("avianki.deck", "from . import build\n", package=True) == []
    # avianki/sources/gbif/__init__.py: ..contract -> avianki.sources.contract
    assert (
        _check(
            "avianki.sources.gbif", "from ..contract import Candidate\n", package=True
        )
        == []
    )


def test_relative_import_beyond_top_level_is_reported() -> None:
    assert _check("avianki.core.http", "from .... import x\n")


def test_type_checking_import_counts() -> None:
    source = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from avianki.media.images import Image\n"
    )
    problems = _check("avianki.deck.build", source)
    assert problems and ":3:" in problems[0]


def test_import_inside_function_counts() -> None:
    assert _check("avianki.core.http", "def f():\n    import avianki.taxonomy\n")


def test_import_module_string_counts() -> None:
    assert _check(
        "avianki.deck.x", "import importlib\nimportlib.import_module('avianki.media')\n"
    )


def test_sources_may_not_import_each_other_or_the_registry() -> None:
    assert _check("avianki.sources.gbif.api", "from avianki.sources.commons import x\n")
    assert _check("avianki.sources.gbif.api", "from avianki.sources import registry\n")
    assert _check("avianki.sources.gbif.api", "from avianki.catalog import format\n")
    ok = "from avianki.sources.contract import Candidate\nfrom avianki.sources.gbif import parse\n"
    assert _check("avianki.sources.gbif.api", ok) == []


def test_registry_may_import_concrete_sources() -> None:
    assert (
        _check(
            "avianki.sources.registry", "from avianki.sources.gbif import GbifSpeciesSource\n"
        )
        == []
    )


def test_catalog_boundary_is_downstream_safe() -> None:
    assert (
        _check("avianki.catalog.build", "from avianki.sources import registry\n") == []
    )
    assert _check("avianki.catalog.format", "from avianki.sources import registry\n")
    assert _check("avianki.catalog.client", "from avianki.media import images\n")
    assert _check("avianki.catalog", "from . import build\n", package=True)


def test_client_may_only_import_format_and_core() -> None:
    ok = (
        "from avianki.catalog.format import Manifest\n"
        "from avianki.core.http import default_user_agent\n"
    )
    assert _check("avianki.catalog.client", ok) == []
    for bad in (
        "from avianki.catalog import build\n",
        "from avianki.catalog.credit import render_credit\n",
        "from avianki.sources import registry\n",
        "from avianki.taxonomy import species\n",
        "from avianki.media import images\n",
        "from avianki.deck import build\n",
    ):
        assert _check("avianki.catalog.client", bad), bad


def test_cli_may_only_reach_the_adhoc_module() -> None:
    # The one crossing (ADR 0017/0018, amended in M5): --ebird calls build_ebird_species().
    assert (
        _check("avianki.cli", "from avianki.catalog.adhoc import build_ebird_species\n") == []
    )
    assert _check("avianki.cli", "from avianki.catalog.build import build_species\n")
    assert _check("avianki.cli", "import avianki.catalog.build\n")
    assert _check("avianki.cli", "from avianki.catalog import validate\n")
    assert _check("avianki.cli", "from avianki.sources.ebird import EbirdSpeciesSource\n")
    assert _check("avianki.cli", "from avianki.taxonomy import species\n")


def test_cli_may_not_import_the_media_package() -> None:
    assert _check("avianki.cli", "from avianki import media\n")
    assert _check("avianki.cli", "from avianki.media import images\n")
    assert _check("avianki.cli", "import avianki.media.audio\n")


def test_legacy_flat_modules_are_gone() -> None:
    for name in ("allaboutbirds.py", "ebird.py", "anki_model.py", "card.css"):
        assert not (PACKAGE_DIR / name).exists(), name
    assert (PACKAGE_DIR / "sources" / "ebird").is_dir()
    assert (PACKAGE_DIR / "sources" / "allaboutbirds").is_dir()


def test_allaboutbirds_is_not_registered() -> None:
    # The scraper is kept but dormant (ADR 0002): nothing may import it.
    importers = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in PACKAGE_DIR.rglob("*.py")
        if "sources/allaboutbirds" not in p.as_posix()
        and "allaboutbirds" in p.read_text(encoding="utf-8")
        and any("allaboutbirds" in name for _, name in imported_names(module_name(p, PACKAGE_DIR), p.read_text(encoding="utf-8")))
    ]
    assert not importers, importers


def test_non_avianki_imports_are_ignored() -> None:
    assert (
        _check("avianki.core.http", "import requests\nfrom pathlib import Path\n") == []
    )


def test_unknown_module_asks_for_a_rule() -> None:
    (problem,) = _check("avianki.shiny", "")
    assert "add a rule for avianki.shiny in tests/test_layout.py" in problem.lower()
