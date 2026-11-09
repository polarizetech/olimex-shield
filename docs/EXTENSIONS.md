# Extensions

An **extension** is a layer built on olimex-shield: its own package, adding one job on top of the
bridge. It can live in this repository (`extensions/<name>/`) or in any other. The model is
Neurodata Without Borders' extension system (Rübel et al. 2022, *eLife* 11:e78362,
[doi:10.7554/eLife.78362](https://doi.org/10.7554/eLife.78362)): a small core, extensions
versioned apart, each declaring the core releases it was tested against, and one catalogue.

The experimental analysis routes are the first one: [`extensions/experimental/`](../extensions/experimental/)
(see [`experimental.md`](experimental.md)).

## The contract

1. **It is its own package**, with a distribution name starting `olimex-shield-ext-`, an import
   name starting `olimex_shield_ext_`, its own `__version__` and its own `CHANGELOG.md`.
2. **It declares itself** in its `__init__.py`:

   ```python
   __version__ = "0.1.0"
   REQUIRES = ">=0.3.0,<0.4"

   from extensions import declare as _declare

   EXTENSION = _declare(name="olimex-shield-ext-thing", module=__name__, version=__version__,
                        requires=REQUIRES, job="One line: the one job it adds.", uses=(), extends={})
   ```

   `extensions` is the kit, `apps/server/extensions.py`; the bridge has `apps/server` on its path.
   `requires` is enforced on import: outside it, `IncompatibleTool` is raised, naming the version
   found and where it was read. The same range is `[tool.olimex-shield] requires` in the
   extension's `pyproject.toml` (olimex-shield runs from a checkout and is not a pip distribution,
   so it is not a dependency line).
3. **It is findable.** `extensions.discover()` looks in three places, in order, and reports every
   extension it finds as `ok`, `incompatible`, `undeclared` or `error`, never dropping one:
   - installed distributions registering the entry point
     `[project.entry-points."olimex_shield.extensions"]`;
   - [`extensions/catalog.json`](../extensions/catalog.json) entries with a `path` (no install
     needed);
   - every `olimex_shield_ext_*` package in the directories named by `$OLIMEX_EXTENSIONS`
     (separated like `PATH`).
4. **It serves routes through one small contract.** The bridge reads these attributes of an `ok`
   extension, and nothing else:

   | Attribute | Required | What it is |
   |---|---|---|
   | `ROUTES` | to serve routes | `{("GET" or "POST", "/path"): handler}` |
   | `handler(body, ctx)` | | returns `(status, obj)`. `body` is the JSON body of a POST, or the query parameters of a GET. `ctx.samples_for(body)`, `ctx.rate_for(body)` and `ctx.default_rate` are the bridge's own helpers: supplied samples or the tail of the live ring, and the rate with its basis. |
   | `mark(obj)` | no | applied to every response from its routes, errors included |
   | `FIREWALL_ERRORS` | no | exception classes the bridge answers with 400 and `"firewall": true` |
   | `health()` | no | a dict shown under the extension's row in `/health` |

   Core routes always win: an extension's route is consulted only when no core route matched. A
   POST handler's exception becomes a 400 (`KeyError`, `ValueError`, `TypeError`) or a 500; a
   GET handler's, a 500. Either is passed through `mark`. An experimental extension marks every answer `"experimental": true` with a
   `note`, as [`experimental.md`](experimental.md) requires.
5. **The ones in this repo are catalogued**, with `name`, `import`, `version`, `requires`, `job`,
   `path` and `routes` (and `experimental: true` when they are). From `routes` the bridge answers
   503 with the extension's status when it is absent or refused, instead of 404. A folder with no
   entry fails `tests/test_contract.py`, and so does an entry with no folder, or a `routes` list
   that differs from `ROUTES`.
6. **The arrow runs one way.** No core file (`apps/server`, `apps/web`, `scripts`) imports an
   extension; the bridge reaches them only through `discover()`. An extension imports the
   standard library, the kit, itself and any extension it names in `extends` (the experimental
   extension also imports the companion analysis tools, each import guarded). Asserted by AST in
   `tests/test_contract.py`.
7. **Anything on the recording path stays stdlib-only.** An extension is never on it, but a heavy
   dependency is still a lazy import that reports its absence instead of raising.

## Versioning rule

An extension declares `>=<the release it was tested on>,<next minor>`, never an open upper bound.
A minor release of olimex-shield therefore refuses every extension (status `incompatible`, routes
503) until its gate is re-run against the new release and its range widened in a new release of
the extension. That refusal is the prompt to re-test. Widen `extensions/_template/` with the rest.
The rules are `.agents/protocols/TOOL_VERSIONING.md` §6.

## Adding one

1. Copy [`extensions/_template/`](../extensions/_template/) to `extensions/<name>/` (or into your
   own repository), and rename `olimex_shield_ext_template` and `olimex-shield-ext-template`.
2. Write its job in one line, its `ROUTES`, and a gate (a `dev_check.py` or tests) that exercises
   them.
3. Here: add a catalogue entry, add its gate to `scripts/check.py`, and run
   `python3 scripts/check.py`. Elsewhere: `pip install -e .` registers the entry point, or put its
   parent directory in `$OLIMEX_EXTENSIONS`. An extension in another repository may be listed in
   the catalogue with `repo` instead of `path`; only that repository can check it.
4. Start the bridge and read `GET /health`: your extension should be listed as `ok`.

## What this does not do

- The specifier grammar is a subset: comma-separated `>=`, `>`, `<=`, `<`, `==`, `!=` over dotted
  integers. No `~=`, no pre-releases.
- Discovery runs once, when the bridge starts. Restart it after adding an extension.
- An extension runs in the bridge's process. The kit reports one that fails to import, but it
  cannot stop one that misbehaves after loading; install only extensions you trust.
