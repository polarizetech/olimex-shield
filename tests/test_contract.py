"""The contract: one version said four ways, a catalogue that matches its packages, imports that
run one way, and no research in the tool.

Each test checks that two declarations of one fact have not drifted. See CLAUDE.md and
docs/EXTENSIONS.md. Standard library only and Python 3.9-compatible (no tomllib): runs as
`python3 -m unittest tests/test_contract.py`, and from scripts/check.py.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "apps" / "server"
WEB = ROOT / "apps" / "web"
if str(SERVER) not in sys.path:
    sys.path.insert(0, str(SERVER))

import sessions  # noqa: E402

import extensions as ext  # noqa: E402  the kit (core)

TEMPLATE_IMPORT = "olimex_shield_ext_template"
#: What an extension may import besides the standard library, itself and what it `extends`: the
#: kit, and (for the experimental extension) the companion analysis tools found via
#: $OLIMEX_TOOLS, each import guarded.
ALLOWED_IMPORTS = {"extensions"}
COMPANION_IMPORTS = {
    "olimex_shield_ext_experimental": {
        "auditory",
        "electrodes",
        "forward",
        "montage",
        "extract",
        "noise_budget",
    }
}
_STDLIB = set(getattr(sys, "stdlib_module_names", ())) or None  # 3.10+


# ------------------------------------------------------------------------------ helpers --


def toml_value(text: str, section: str, key: str):
    """A `key = "string"` value under `[section]` in a TOML file, or None. Enough for the flat
    tables checked here; tomllib is 3.11+ and these tests run on 3.9."""
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]") and not line.startswith("[["):
            current = line[1:-1].strip()
            continue
        if line.startswith("[["):
            current = None
            continue
        if current != section or "=" not in line or line.startswith("#"):
            continue
        k, _, v = line.partition("=")
        if k.strip().strip("\"'") == key:
            v = v.split("#", 1)[0].strip() if not v.strip().startswith('"') else v.strip()
            m = re.match(r"""^["']([^"']*)["']""", v)
            return m.group(1) if m else v
    return None


def toml_table(text: str, section: str) -> dict:
    """Every `key = "string"` pair under `[section]`."""
    out, current = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            current = line.strip("[]").strip()
            continue
        if current == section and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            m = re.match(r"""^\s*["']([^"']*)["']""", v)
            if m:
                out[k.strip().strip("\"'")] = m.group(1)
    return out


def _imports(py: Path):
    """Top-level names of every absolute import in a file."""
    for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


def _is_stdlib(name: str) -> bool:
    if _STDLIB is not None:
        return name in _STDLIB
    spec = importlib.util.find_spec(name)  # 3.9 fallback: not under site-packages
    return spec is not None and "site-packages" not in str(spec.origin or "")


def _import_from(d: Path, name: str):
    if name in sys.modules:
        return sys.modules[name]
    sys.path.insert(0, str(d))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(d))


TOOL_TOML = (ROOT / "TOOL.toml").read_text(encoding="utf-8")
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
EXT_CONF = toml_table(TOOL_TOML, "extensions")
CATALOG_PATH = ROOT / EXT_CONF.get("catalog", "extensions/catalog.json")
CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
ENTRIES = CATALOG["extensions"]
_repo = re.search(
    r"""^repository-code:\s*["']?https?://[^/]+/([^/\s"']+/[^/\s"']+?)["']?\s*$""",
    (ROOT / "CITATION.cff").read_text(encoding="utf-8"),
    re.M,
)
OWN_REPO = _repo.group(1) if _repo else ""
IN_REPO = [
    e for e in ENTRIES if e.get("path") and e.get("repo", OWN_REPO).lower() == OWN_REPO.lower()
]
TEMPLATE = CATALOG_PATH.parent / "_template"


# ------------------------------------------------------------------------------ version --


class Version(unittest.TestCase):
    def test_one_version_said_four_ways(self):
        v = toml_value(PYPROJECT, "project", "version")
        self.assertRegex(v or "", r"^\d+\.\d+\.\d+$", "pyproject.toml [project] version")
        self.assertEqual(sessions.software_version(), v, "the bridge reads the same version")
        self.assertEqual(ext.tool_version(), v, "the extension kit reads the same version")
        self.assertEqual(_top(TOOL_TOML, "version"), v, "TOOL.toml version")
        cff = re.search(
            r"""^version:\s*["']?([^"'\s]+)""",
            (ROOT / "CITATION.cff").read_text(encoding="utf-8"),
            re.M,
        )
        self.assertIsNotNone(cff, "CITATION.cff has no version")
        self.assertEqual(cff.group(1), v, "CITATION.cff version")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertTrue(
            re.search(rf"(?m)^##\s*\[{re.escape(v)}\]", changelog), f"CHANGELOG has no ## [{v}]"
        )

    def test_the_kit_is_configured_as_the_manifest_says(self):
        self.assertEqual(ext.TOOL, toml_value(PYPROJECT, "project", "name"))
        self.assertEqual(ext.TOOL, _top(TOOL_TOML, "name"))
        self.assertEqual(ext.PREFIX, EXT_CONF.get("prefix"))
        self.assertEqual(ext.ENTRY_POINT_GROUP, EXT_CONF.get("group"))
        self.assertEqual(CATALOG_PATH.resolve(), ext.CATALOG_PATH.resolve())

    def test_a_tool_holds_no_research(self):
        for f in ("EXPERIMENTS.md", "experiments", "RESEARCH.md"):
            self.assertFalse((ROOT / f).exists(), f"{f}: findings belong in the consuming repo")
        self.assertIsNone(_top(TOOL_TOML, "question"))
        self.assertIsNone(re.search(r"(?m)^\s*\[corpus\]", TOOL_TOML), "TOOL.toml has [corpus]")


def _top(text: str, key: str):
    """A top-level (before any table) `key = "value"` in a TOML file."""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            return None
        k, sep, v = line.partition("=")
        if sep and k.strip() == key:
            m = re.match(r"""^\s*["']([^"']*)["']""", v)
            return m.group(1) if m else None
    return None


# ---------------------------------------------------------------------------------- kit --


class Kit(unittest.TestCase):
    def test_specifier_arithmetic(self):
        self.assertTrue(ext.satisfies("0.3.0", ">=0.3.0,<0.4"))
        self.assertTrue(ext.satisfies("0.3.9", ">=0.3.0,<0.4"))
        self.assertFalse(ext.satisfies("0.4.0", ">=0.3.0,<0.4"))
        self.assertFalse(ext.satisfies("0.2.9", ">=0.3.0,<0.4"))
        self.assertTrue(ext.satisfies("1.0", "==1.0.0"))
        self.assertFalse(ext.satisfies("1.0.1", "!=1.0.1"))

    def test_specifier_refuses_what_it_cannot_read(self):
        for bad in ("", "~=0.1", ">=0.1.0rc1", "0.1"):
            with self.assertRaises(ValueError, msg=bad):
                ext.satisfies("0.1.0", bad)

    def test_require_refuses_an_incompatible_tool(self):
        v = ext.tool_version()
        with self.assertRaisesRegex(ext.IncompatibleTool, re.escape(v)):
            ext.require(ext.PREFIX + "test", ">=99")
        self.assertEqual(ext.require(ext.PREFIX + "test", f"=={v}"), v)

    def test_declare_refuses_a_nameless_or_jobless_extension(self):
        with self.assertRaises(ValueError):
            ext.declare(name="thing", module="m", version="0.1.0", requires=">=0", job="x")
        with self.assertRaises(ValueError):
            ext.declare(
                name=ext.PREFIX + "thing", module="m", version="0.1.0", requires=">=0", job=" "
            )
        with self.assertRaises(ext.IncompatibleTool):
            ext.declare(
                name=ext.PREFIX + "future", module="m", version="0.1.0", requires=">=99", job="x"
            )

    def test_an_extension_can_extend_an_extension_and_is_refused_when_the_base_is_wrong(self):
        v = ext.tool_version()
        base = ext.declare(
            name=ext.PREFIX + "test-base",
            module="test_base",
            version="0.3.0",
            requires=f">={v}",
            job="a base",
        )
        child = ext.declare(
            name=ext.PREFIX + "test-child",
            module="test_child",
            version="0.1.0",
            requires=f">={v}",
            job="builds on the base",
            extends={base.name: ">=0.3.0,<0.4"},
        )
        self.assertIn(child, ext.loaded())
        with self.assertRaisesRegex(ext.MissingExtension, "found .*test-base 0.3.0"):
            ext.declare(
                name=ext.PREFIX + "test-child2",
                module="c2",
                version="0.1.0",
                requires=f">={v}",
                job="x",
                extends={base.name: ">=0.4"},
            )
        with self.assertRaisesRegex(ext.MissingExtension, "neither imported nor installed"):
            ext.declare(
                name=ext.PREFIX + "test-child3",
                module="c3",
                version="0.1.0",
                requires=f">={v}",
                job="x",
                extends={ext.PREFIX + "nonexistent": ">=0"},
            )

    def test_two_packages_cannot_claim_one_extension_name(self):
        ext.declare(
            name=ext.PREFIX + "test-dup", module="a", version="0.1.0", requires=">=0", job="x"
        )
        with self.assertRaisesRegex(ValueError, "two packages"):
            ext.declare(
                name=ext.PREFIX + "test-dup", module="b", version="0.1.0", requires=">=0", job="x"
            )

    def test_discover_reports_every_extension_with_a_status(self):
        rows = ext.discover(refresh=True)
        names = {r.get("name") for r in rows}
        for e in IN_REPO:
            self.assertIn(e["name"], names, "an in-repo extension is always reported")
        for r in rows:
            self.assertIn(r["status"], ("ok", "incompatible", "undeclared", "error"), r)
            if r["status"] != "ok":
                self.assertTrue(r.get("reason"), r)


# ----------------------------------------------------------------------------- contract --


class Contract(unittest.TestCase):
    def check_package(self, d: Path, imp: str, entry: dict | None = None):
        """An extension's pyproject, its declare() and (if catalogued) its catalogue entry agree."""
        text = (d / "pyproject.toml").read_text(encoding="utf-8")
        name = toml_value(text, "project", "name")
        self.assertTrue(name.startswith(ext.PREFIX), name)
        eps = toml_table(text, f'project.entry-points."{ext.ENTRY_POINT_GROUP}"')
        self.assertEqual(eps, {name: imp}, f"{d.name}: one entry point in {ext.ENTRY_POINT_GROUP}")
        self.assertEqual(toml_value(text, "tool.hatch.version", "path"), f"{imp}/__init__.py")
        mod = _import_from(d, imp)
        self.assertEqual(
            toml_value(text, "tool.olimex-shield", "requires"),
            mod.REQUIRES,
            f"{d.name}: pyproject range must equal REQUIRES",
        )
        self.assertEqual(
            (
                mod.EXTENSION.name,
                mod.EXTENSION.version,
                mod.EXTENSION.requires,
                mod.EXTENSION.module,
            ),
            (name, mod.__version__, mod.REQUIRES, imp),
        )
        self.assertTrue(
            ext.satisfies(ext.tool_version(), mod.REQUIRES),
            f"{d.name} does not accept {ext.TOOL} {ext.tool_version()}: re-run its gate and widen "
            f"its range",
        )
        self.assertIsInstance(getattr(mod, "ROUTES", {}), dict)
        for key, handler in getattr(mod, "ROUTES", {}).items():
            self.assertIn(key[0], ext.METHODS, key)
            self.assertTrue(key[1].startswith("/") and callable(handler), key)
        if entry is not None:
            self.assertEqual(
                (entry["name"], entry["import"], entry["version"], entry["requires"], entry["job"]),
                (name, imp, mod.__version__, mod.REQUIRES, mod.EXTENSION.job),
            )
            self.assertEqual(
                sorted(entry.get("routes", [])),
                sorted(f"{m} {p}" for (m, p) in getattr(mod, "ROUTES", {})),
                f"{d.name}: catalogue routes must equal ROUTES",
            )
        return mod

    def check_imports(self, d: Path, imp: str, extends=()):
        allowed = set(ALLOWED_IMPORTS) | {imp} | set(extends) | COMPANION_IMPORTS.get(imp, set())
        bad = sorted(
            f"{f.relative_to(ROOT)}: {n}"
            for f in (d / imp).rglob("*.py")
            for n in _imports(f)
            if n not in allowed and not _is_stdlib(n)
        )
        self.assertFalse(bad, bad)

    def test_core_never_imports_an_extension(self):
        exts = {e["import"] for e in ENTRIES if e.get("import")} | {TEMPLATE_IMPORT}
        core = [p for p in SERVER.rglob("*.py") if "recordings" not in p.parts]
        core += [p for p in WEB.rglob("*.py") if "vendor" not in p.parts]
        core += list((ROOT / "scripts").glob("*.py"))
        bad = sorted(
            f"{f.relative_to(ROOT)}: {n}"
            for f in core
            for n in _imports(f)
            if n in exts or n.startswith("olimex_shield_ext_")
        )
        self.assertFalse(bad, bad)
        self.assertFalse((SERVER / "experimental.py").exists(), "moved to extensions/experimental")

    def test_catalogue_and_directories_agree_both_ways(self):
        dirs = {
            p.resolve()
            for p in CATALOG_PATH.parent.iterdir()
            if p.is_dir() and not p.name.startswith(("_", ".")) and (p / "pyproject.toml").exists()
        }
        catalogued = {(ROOT / e["path"]).resolve() for e in IN_REPO}
        self.assertEqual(dirs, catalogued)

    def test_catalogue_names_are_unique_prefixed_and_ranges_parse(self):
        self.assertEqual(CATALOG["schema"], "olimex-shield-extension-catalog/1")
        self.assertEqual(len({e["name"] for e in ENTRIES}), len(ENTRIES))
        for e in ENTRIES:
            self.assertTrue(e["name"].startswith(ext.PREFIX), e["name"])
            ext.parse_version(e["version"])
            ext.satisfies("0.0.0", e["requires"])  # parses

    def test_each_in_repo_extension_matches_its_catalogue_entry_and_imports_one_way(self):
        imports = {e["name"]: e.get("import") for e in ENTRIES}
        for e in IN_REPO:
            with self.subTest(e["name"]):
                d = ROOT / e["path"]
                mod = self.check_package(d, e["import"], e)
                self.assertEqual(dict(mod.EXTENSION.extends), dict(e.get("extends", {})))
                self.assertTrue((d / "CHANGELOG.md").is_file(), "an extension keeps a changelog")
                self.assertRegex(
                    (d / "CHANGELOG.md").read_text(encoding="utf-8"),
                    rf"(?m)^##\s*\[{re.escape(mod.__version__)}\]",
                )
                self.check_imports(
                    d, e["import"], extends={imports.get(b) for b in mod.EXTENSION.extends}
                )

    def test_the_template_extension_is_valid(self):
        mod = self.check_package(TEMPLATE, TEMPLATE_IMPORT)
        self.check_imports(TEMPLATE, TEMPLATE_IMPORT)
        ctx = ext.Context(samples_for=lambda b: [], rate_for=lambda b: (250.0, "declared"))
        status, body = mod.ROUTES[("GET", "/template/hello")]({}, ctx)
        self.assertEqual(status, 200)
        self.assertTrue(body["experimental"])

    def test_the_template_accepts_the_same_tool_range_as_the_catalogued_extensions(self):
        mod = _import_from(TEMPLATE, TEMPLATE_IMPORT)
        for e in IN_REPO:
            self.assertEqual(mod.REQUIRES, e["requires"], "widen the template with the rest")


if __name__ == "__main__":
    unittest.main()
