"""olimex_shield_ext_experimental: the experimental analysis routes, off the core bridge.

Serves lock-in extraction, the integration check, the noise budget, detection curves, the rate
trade and the auditory atlas as bridge routes, backed by optional companion analysis tools
(`$OLIMEX_TOOLS`), plus the user-supplied rig profile (`$OLIMEX_RIG_PROFILE`). Every answer is
marked `"experimental": true` with a `note`. See docs/experimental.md and docs/EXTENSIONS.md.

The bridge finds this package through `extensions.discover()` (the catalogue lists it, so no
install is needed) and serves `ROUTES`. It imports only the standard library, the extension kit
(`extensions`, which the bridge puts on sys.path) and the companion tools, each import guarded.
"""

__version__ = "0.1.0"
#: The olimex-shield releases this was built and tested against. Enforced on import; must equal
#: `[tool.olimex-shield] requires` in pyproject.toml and the catalogue entry.
REQUIRES = ">=0.3.0,<0.4"

from extensions import declare as _declare  # noqa: E402

EXTENSION = _declare(
    name="olimex-shield-ext-experimental",
    module=__name__,
    version=__version__,
    requires=REQUIRES,
    job="Serves the experimental analysis routes (lock-in, noise budget, atlas) as bridge routes.",
    uses=("extensions.Context.samples_for", "extensions.Context.rate_for"),
)

from .routes import (  # noqa: E402
    FIREWALL_ERRORS,
    NOTE,
    ROUTE_NAMES,
    ROUTE_TABLE,
    NoRigProfile,
    health,
    mark,
    rig_profile_status,
)

#: The bridge contract: {(method, path): handler(body, ctx) -> (status, obj)}.
ROUTES = ROUTE_TABLE

__all__ = [
    "EXTENSION",
    "FIREWALL_ERRORS",
    "NOTE",
    "REQUIRES",
    "ROUTES",
    "ROUTE_NAMES",
    "NoRigProfile",
    "health",
    "mark",
    "rig_profile_status",
]
