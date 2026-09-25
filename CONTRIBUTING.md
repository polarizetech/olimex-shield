# Contributing

Thanks for looking. A few things matter more here than in most repos, because this software sits
next to a person's body and produces numbers people will believe.

## Before a pull request

```bash
python3 scripts/check.py        # every suite; needs node for the JS checks
```

Every suite must pass. A suite that cannot run (no node, no MNE) must **say so and skip**. It
must never pass quietly.

## Rules the tests enforce, and why

- **Safety text is never shortened.** The workbench shows the full safety list before any port
  opens. A condensed safety notice is a different notice.
- **Nothing connects without the hookup guide.** `beforeConnect` is awaited, and a failed fetch
  does not fall through to connecting.
- **Synthetic data never looks measured.** The source tier comes from the bridge's `status.demo`,
  not from the port name. It carries into every session and export.
- **Numbers come from the server.** The browser draws. A value computed in two places will
  eventually disagree with itself.
- **No colour or font literals in app CSS.** They come from `apps/web/vendor/design`.
- **Sessions never enter git.** `sessions/`, `recordings/` and `exports/` are ignored. Do not add
  example recordings of real people.
- **Uploads are private.** Nothing may write a public ACL, and an upload that a stranger can read
  is a failure.

## The design system

`apps/web/vendor/design` is a copy of the Polarize design system. Change it upstream, then run
`scripts/sync_design.py --from <path>`. Do not edit it here.

## Firmware

If you change `apps/olimex-shield/eeg_stream/eeg_stream.ino`:
- follow the versioning steps in its README;
- add a **Board** entry to `CHANGELOG.md`.
