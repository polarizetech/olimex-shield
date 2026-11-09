"""extensions.py -- the extension kit: how a layer built ON olimex-shield plugs into the bridge.

The pattern is Neurodata Without Borders' extension system (Rübel et al. 2022, eLife 11:e78362,
doi:10.7554/eLife.78362): a small core, extensions as separately versioned packages that declare
the core version they were tested against, and one catalogue listing them. Here:

  * each extension is its own package (its own `pyproject.toml`, `__version__`, `REQUIRES`), with
    a distribution name starting `PREFIX`;
  * on import it calls `declare(...)`, which REFUSES an incompatible olimex-shield rather than
    running against it;
  * it is found by `discover()`, from three places, in this order: installed distributions that
    register the `ENTRY_POINT_GROUP` entry point; the in-repo extensions listed with a `path` in
    `extensions/catalog.json` (no install needed); and any directory named in `$OLIMEX_EXTENSIONS`
    (os.pathsep-separated), whose `olimex_shield_ext_*` packages are imported;
  * every extension found is REPORTED with a status (`ok`, `incompatible`, `undeclared`, `error`),
    never silently dropped: a missing row reads as "there is no such extension", which is a
    different statement from "it is here and refused to load".

THE BRIDGE CONTRACT. An extension module that adds bridge routes exposes

    ROUTES = {("GET", "/path"): handler, ("POST", "/other"): handler, ...}

where `handler(body, ctx) -> (status, obj)`. `body` is the parsed JSON body for a POST and the
query parameters for a GET; `ctx` is a `Context` holding the bridge's own helpers (`samples_for`,
`rate_for`, `default_rate`). Optionally it also exposes `mark(obj) -> obj` (applied to every
response from its routes, errors included), `FIREWALL_ERRORS` (exception classes the bridge answers
with 400 and `"firewall": true`) and `health() -> dict` (shown in `/health`). Core routes always
win: an extension's route is consulted only when no core route matched. Nothing else is reached
into.

THE ARROW RUNS ONE WAY. This module is core. It never imports an extension by name; it imports
what `discover()` finds, and `serve.py` only ever talks to `discover()` and `route_table()`.

The tool's version has ONE source, `version` in the repo's pyproject.toml, read by
`sessions.software_version()`. Standard library only, Python 3.9+. The specifier grammar is the
small subset extensions use (comma-separated `>=`, `>`, `<=`, `<`, `==`, `!=` over dotted
integers); anything outside it is refused rather than guessed at. Rules: docs/EXTENSIONS.md.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "ENTRY_POINT_GROUP",
    "ENV",
    "PREFIX",
    "TOOL",
    "Context",
    "Extension",
    "IncompatibleTool",
    "MissingExtension",
    "catalog_routes",
    "declare",
    "discover",
    "loaded",
    "parse_version",
    "require",
    "route_table",
    "satisfies",
    "tool_version",
]

#: The tool's distribution name.
TOOL = "olimex-shield"
#: Every extension's distribution name starts with this. Must equal TOOL.toml [extensions] prefix.
PREFIX = "olimex-shield-ext-"
#: Every extension's import name starts with this (used for $OLIMEX_EXTENSIONS directories).
IMPORT_PREFIX = "olimex_shield_ext_"
#: The entry-point group an extension registers under, from ANY repository. Must equal TOOL.toml
#: [extensions] group:
#:     [project.entry-points."olimex_shield.extensions"]
#:     olimex-shield-ext-something = "olimex_shield_ext_something"
ENTRY_POINT_GROUP = "olimex_shield.extensions"
#: Extra directories to look in, os.pathsep-separated.
ENV = "OLIMEX_EXTENSIONS"

REPO = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO / "extensions" / "catalog.json"

#: What a route of an unavailable experimental extension carries, so a client can never render
#: one of its answers as core.
EXPERIMENTAL_NOTE = (
    "Experimental: served by an extension, not an established method for this hardware; "
    "see docs/experimental.md."
)

_CLAUSE = re.compile(r"^\s*(>=|<=|==|!=|>|<)\s*([0-9]+(?:\.[0-9]+)*)\s*$")
METHODS = ("GET", "POST")


class IncompatibleTool(ImportError):
    """An extension was imported against a version of this tool outside the range it declares."""


class MissingExtension(ImportError):
    """An extension extends another extension that is not present, or not in the declared range."""


# ---------------------------------------------------------------------------------- versions --


def parse_version(v: str) -> tuple[int, ...]:
    """'0.1.0' -> (0, 1, 0). Pre-release or local suffixes are refused, not guessed at."""
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", v.strip()):
        raise ValueError(f"unsupported version string {v!r}: dotted integers only")
    return tuple(int(p) for p in v.strip().split("."))


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def satisfies(version: str, spec: str) -> bool:
    """True if `version` meets every clause of `spec` (e.g. '>=0.3.0,<0.4')."""
    if not spec.strip():
        raise ValueError("an empty specifier accepts every version; declare a range")
    v = parse_version(version)
    for clause in spec.split(","):
        m = _CLAUSE.match(clause)
        if not m:
            raise ValueError(f"unsupported specifier clause {clause!r} in {spec!r}")
        op, target = m.group(1), parse_version(m.group(2))
        c = _cmp(v, target)
        ok = {">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0, "==": c == 0, "!=": c != 0}[op]
        if not ok:
            return False
    return True


def tool_version() -> str:
    """This tool's version, from its one source (pyproject.toml, via sessions.software_version)."""
    import sessions

    return sessions.software_version()


def require(extension: str, spec: str) -> str:
    """Refuse to let `extension` load against a version of this tool outside `spec`. Returns the
    version found. The error names the version and WHERE it was read, because the usual cause is
    not a wrong release but a second copy of the bridge earlier on sys.path."""
    found = tool_version()
    where = REPO / "pyproject.toml"
    if found == "unknown":
        raise IncompatibleTool(
            f"{extension} requires {TOOL} {spec}, but no version could be read from {where}."
        )
    if not satisfies(found, spec):
        raise IncompatibleTool(
            f"{extension} requires {TOOL} {spec}, but this is {TOOL} {found} (from {where}). "
            f"Use a compatible release of the extension, or re-run its tests against {found} and "
            f"widen its range."
        )
    return found


# ------------------------------------------------------------------------------- declaration --


@dataclass(frozen=True)
class Extension:
    """What an extension says about itself. Declared once, in its package `__init__.py`."""

    name: str  # distribution name, PREFIX + <something>
    module: str  # the import name, usually __name__
    version: str
    requires: str  # the range of this tool it was built and tested against
    job: str  # one line: the ONE job it adds on top of the tool
    uses: tuple[str, ...] = ()  # what of the tool it depends on, so a change has a known consumer
    extends: dict = field(default_factory=dict)  # {PREFIX + "other": ">=0.1.0,<0.2"}
    tool_version: str = ""  # filled in by declare(): the version it actually loaded against


_REGISTRY: dict[str, Extension] = {}


def _installed_version(dist: str) -> str | None:
    from importlib import metadata

    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return None


def declare(*, name, module, version, requires, job, uses=(), extends=None) -> Extension:
    """Declare an extension, check it against this tool and anything it extends, and register it.

    Call at import. Refuses (raises) when:
      * `name` does not start with PREFIX, or `job` is empty or more than one line;
      * this tool is outside `requires` (IncompatibleTool);
      * a base in `extends` is neither declared nor installed, or is outside its range
        (MissingExtension). Import the base package first when working from a checkout;
      * a second package declares the same name.
    """
    if not name.startswith(PREFIX):
        raise ValueError(f"extension name {name!r} must start with {PREFIX!r}")
    if not job.strip() or "\n" in job:
        raise ValueError(f"{name}: declare the one job this extension adds, in one line")
    parse_version(version)
    found = require(name, requires)
    extends = dict(extends or {})
    for base, spec in extends.items():
        have = _REGISTRY[base].version if base in _REGISTRY else _installed_version(base)
        if have is None:
            raise MissingExtension(
                f"{name} extends {base} {spec}, which is neither imported nor installed. "
                f"Install it, or import its package before {module}."
            )
        if not satisfies(have, spec):
            raise MissingExtension(f"{name} extends {base} {spec}, but found {base} {have}.")
    prior = _REGISTRY.get(name)
    if prior is not None and prior.module != module:
        raise ValueError(f"two packages declare {name}: {prior.module} and {module}")
    ext = Extension(
        name=name,
        module=module,
        version=version,
        requires=requires,
        job=job,
        uses=tuple(uses),
        extends=extends,
        tool_version=found,
    )
    _REGISTRY[name] = ext
    return ext


def loaded() -> list[Extension]:
    """Extensions declared in this process so far."""
    return list(_REGISTRY.values())


# --------------------------------------------------------------------------------- discovery --


def load_catalog(path: Path | None = None) -> dict:
    """The catalogue, or an empty one when the file is missing or unreadable (never raises)."""
    try:
        cat = json.loads(Path(path or CATALOG_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": None, "extensions": []}
    if not isinstance(cat, dict) or not isinstance(cat.get("extensions"), list):
        return {"schema": cat.get("schema") if isinstance(cat, dict) else None, "extensions": []}
    return cat


def _entry_points():
    from importlib import metadata

    try:
        eps = metadata.entry_points()
    except Exception:  # noqa: BLE001 - a broken install must not break discovery
        return []
    if hasattr(eps, "select"):  # Python 3.10+
        return list(eps.select(group=ENTRY_POINT_GROUP))
    return list(eps.get(ENTRY_POINT_GROUP, []))


def _declared_by(module_name: str) -> Extension | None:
    return next((e for e in _REGISTRY.values() if e.module == module_name), None)


def _load(row: dict, module_name: str, loader: Callable[[], Any]) -> dict:
    """Import one extension and fill in its status. Never raises."""
    try:
        mod = loader()
        ext = _declared_by(module_name)
        if ext is None:
            row.update(
                status="undeclared",
                reason="module imported but never called extensions.declare()",
            )
        else:
            row.update(
                status="ok",
                name=ext.name,
                version=ext.version,
                requires=ext.requires,
                job=ext.job,
                extends=dict(ext.extends),
                routes=_route_names(getattr(mod, "ROUTES", None)),
            )
    except (IncompatibleTool, MissingExtension) as e:
        row.update(status="incompatible", reason=str(e))
    except Exception as e:  # noqa: BLE001 - report, never hide
        row.update(status="error", reason=f"{type(e).__name__}: {e}")
    return row


def _import_from(directory: Path, module_name: str):
    d = str(directory)
    if d not in sys.path:
        sys.path.append(d)  # appended, so it can never shadow a core module
    return importlib.import_module(module_name)


def _route_names(routes) -> list[str]:
    if not isinstance(routes, dict):
        return []
    return [f"{m} {p}" for (m, p) in routes]


_ROWS: list[dict] | None = None
_TABLE: dict | None = None


def discover(refresh: bool = False) -> list[dict]:
    """Every extension this bridge can see, each with a status. Cached; `refresh=True` re-runs.

    Sources, in order (the first to supply a module wins; later sources naming the same module
    are the same extension and are not reported twice):
      1. installed distributions registering the `ENTRY_POINT_GROUP` entry point;
      2. `extensions/catalog.json` entries with a `path` (in this repo, no install needed);
      3. `$OLIMEX_EXTENSIONS` directories: every `olimex_shield_ext_*` package in each.
    """
    global _ROWS, _TABLE
    if _ROWS is not None and not refresh:
        return _ROWS
    _TABLE = None
    rows: list[dict] = []
    seen: set[str] = set()

    for ep in _entry_points():
        mod_name = ep.value.split(":")[0].strip()
        if mod_name in seen:
            continue
        seen.add(mod_name)
        dist = getattr(ep, "dist", None)
        row = {
            "source": "entry-point",
            "name": ep.name,
            "entry_point": ep.name,
            "module": mod_name,
            "distribution": dist.name if dist is not None else None,
        }
        rows.append(_load(row, mod_name, ep.load))

    for entry in load_catalog().get("extensions", []):
        if not isinstance(entry, dict) or not entry.get("path") or not entry.get("import"):
            continue
        mod_name = entry["import"]
        if mod_name in seen:
            continue
        seen.add(mod_name)
        d = REPO / entry["path"]
        row = {
            "source": "catalog",
            "name": entry.get("name"),
            "module": mod_name,
            "path": entry["path"],
        }
        if not (d / mod_name).is_dir():
            row.update(
                name=entry.get("name"),
                status="error",
                reason=f"catalogued at {entry['path']}, but {entry['path']}/{mod_name} is missing",
            )
            rows.append(row)
            continue
        rows.append(_load(row, mod_name, lambda d=d, m=mod_name: _import_from(d, m)))

    for raw in os.environ.get(ENV, "").split(os.pathsep):
        if not raw.strip():
            continue
        d = Path(raw).expanduser()
        if not d.is_dir():
            rows.append(
                {
                    "source": "env",
                    "path": str(d),
                    "status": "error",
                    "reason": f"${ENV} names {d}, which is not a directory",
                }
            )
            continue
        for child in sorted(d.iterdir()):
            mod_name = child.stem if child.suffix == ".py" else child.name
            is_pkg = child.is_dir() and (child / "__init__.py").is_file()
            if not mod_name.startswith(IMPORT_PREFIX) or not (is_pkg or child.suffix == ".py"):
                continue
            if mod_name in seen:
                continue
            seen.add(mod_name)
            row = {"source": "env", "module": mod_name, "path": str(child)}
            rows.append(_load(row, mod_name, lambda d=d, m=mod_name: _import_from(d, m)))

    _ROWS = rows
    return rows


# ------------------------------------------------------------------------ the bridge contract --


@dataclass(frozen=True)
class Context:
    """What the bridge hands an extension's route handler. Nothing else of the daemon is reachable
    from an extension: it reads samples and the rate through these, and never the reverse."""

    samples_for: Callable[[dict], list]
    rate_for: Callable[[dict], tuple]
    default_rate: float = 250.0


def _ok_modules():
    for row in discover():
        if row.get("status") == "ok" and row.get("module") in sys.modules:
            yield row, sys.modules[row["module"]]


def route_table() -> dict[tuple[str, str], tuple[dict, Any, Callable]]:
    """{(METHOD, path): (row, module, handler)} for every route of every `ok` extension. When two
    extensions claim one route the first keeps it and the second's row records the conflict.
    Built once per discovery."""
    global _TABLE
    if _TABLE is not None:
        return _TABLE
    table: dict = {}
    for row, mod in _ok_modules():
        routes = getattr(mod, "ROUTES", None)
        if not isinstance(routes, dict):
            continue
        for key, handler in routes.items():
            method, path = key
            method = method.upper()
            if method not in METHODS or not callable(handler):
                row.setdefault("route_errors", []).append(f"{key!r} is not a callable GET/POST")
                continue
            if (method, path) in table:
                row.setdefault("route_conflicts", []).append(f"{method} {path}")
                continue
            table[(method, path)] = (row, mod, handler)
    _TABLE = table
    return table


def catalog_routes() -> dict[tuple[str, str], dict]:
    """{(METHOD, path): catalogue entry}: the routes the catalogue says an extension serves, so the
    bridge can answer 503 with the extension's status when it is absent or refused."""
    out = {}
    for entry in load_catalog().get("extensions", []):
        if not isinstance(entry, dict):
            continue
        for r in entry.get("routes", []) or []:
            method, _, path = str(r).partition(" ")
            if method.upper() in METHODS and path.startswith("/"):
                out.setdefault((method.upper(), path), entry)
    return out


def row_for(name: str | None, module: str | None = None) -> dict | None:
    """The discovery row for an extension, by distribution or import name."""
    for row in discover():
        if (name and row.get("name") == name) or (module and row.get("module") == module):
            return row
    return None


def unavailable(entry: dict) -> dict:
    """The body of a 503 for a catalogued route whose extension is not loaded here."""
    row = row_for(entry.get("name"), entry.get("import")) or {
        "name": entry.get("name"),
        "status": "missing",
        "reason": "not found by discover()",
    }
    out = {
        "error": f"the extension {entry.get('name')} is not loaded here ({row.get('status')})",
        "extension": {k: row.get(k) for k in ("name", "module", "status", "reason", "source")},
        "hint": "see /health for every extension and its status, and docs/EXTENSIONS.md",
    }
    if entry.get("experimental"):
        out.update(experimental=True, note=EXPERIMENTAL_NOTE)
    return out


def marker_for(path: str) -> Callable[[dict], dict] | None:
    """The `mark()` of whichever extension owns `path` (any method), so its errors are stamped
    like its answers; a generic experimental stamp for a catalogued experimental route whose
    extension is not loaded; None for a core path."""
    for (_m, p), (_row, mod, _h) in route_table().items():
        if p == path:
            fn = getattr(mod, "mark", None)
            return fn if callable(fn) else None
    for (_m, p), entry in catalog_routes().items():
        if p == path and entry.get("experimental"):
            return lambda obj: dict(obj, experimental=True, note=obj.get("note", EXPERIMENTAL_NOTE))
    return None


def firewall_errors() -> tuple:
    """Every `FIREWALL_ERRORS` class the loaded extensions declare."""
    out = set()
    for _row, mod in _ok_modules():
        for cls in getattr(mod, "FIREWALL_ERRORS", ()) or ():
            if isinstance(cls, type) and issubclass(cls, BaseException):
                out.add(cls)
    return tuple(out)


def health() -> list[dict]:
    """The discovery rows for /health, each with the extension's own `health()` when it has one."""
    out = []
    mods = {row.get("module"): mod for row, mod in _ok_modules()}
    for row in discover():
        r = dict(row)
        fn = getattr(mods.get(row.get("module")), "health", None)
        if callable(fn):
            try:
                r["health"] = fn()
            except Exception as e:  # noqa: BLE001 - report, never hide
                r["health"] = {"error": f"{type(e).__name__}: {e}"}
        out.append(r)
    return out
