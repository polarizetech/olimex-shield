"""olimex_shield_ext_template: one line saying the ONE job this adds on top of olimex-shield.

An example extension. See docs/EXTENSIONS.md.
"""

__version__ = "0.1.0"
#: The olimex-shield releases this was built and tested against. Enforced on import; must equal
#: `[tool.olimex-shield] requires` in pyproject.toml.
REQUIRES = ">=0.3.0,<0.4"

# If this builds on another extension, import that package FIRST, so a checkout (not only an
# install) satisfies `extends`.

from extensions import declare as _declare  # noqa: E402

EXTENSION = _declare(
    name="olimex-shield-ext-template",
    module=__name__,
    version=__version__,
    requires=REQUIRES,
    job="One line: the one job this adds on top of olimex-shield.",
    uses=(),  # what of the bridge this depends on, e.g. ("extensions.Context.samples_for",)
    extends={},  # e.g. {"olimex-shield-ext-other": ">=0.1.0,<0.2"}
)


def _hello(query, ctx):
    """A route handler: (body or query, ctx) -> (status, obj). `ctx.samples_for(body)` and
    `ctx.rate_for(body)` are the bridge's own helpers; nothing else of the daemon is reachable."""
    return 200, mark({"extension": EXTENSION.name, "default_rate": ctx.default_rate})


def mark(obj):
    """Optional: applied by the bridge to every response from these routes, errors included.
    An experimental extension stamps `"experimental": true` and a `note` here."""
    return dict(obj, experimental=True, note="Template extension; see docs/EXTENSIONS.md.")


#: The bridge contract: {(method, path): handler}. Core routes always win over these.
ROUTES = {("GET", "/template/hello"): _hello}
