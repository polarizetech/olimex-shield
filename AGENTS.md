<!-- kit_ap:start -->
<!-- Managed by KIT Adaptive Preregistration (https://github.com/polarizetech/adaptive-preregistration.git). Don't edit between these markers: change the kit, then run `.agents/bin/kit_ap update`. -->

# Agent protocols

This repo uses **KIT Adaptive Preregistration**: agent protocols that are maintained in one central repo and vendored into `.agents/`. Every agent follows them, whatever the tool (Claude Code, Codex, Copilot, Cursor, Gemini, ChatGPT…).

- The rules in this block and the documents in `.agents/protocols/` are binding. If a task conflicts with one, stop and say so before doing the task.
- Project-specific instructions (outside these markers, or in nested `AGENTS.md` files) may add to the protocols. If one contradicts a protocol, ask the user which wins.
- Don't edit files in `.agents/` or text between the `kit_ap` markers. Updates overwrite them. To change a protocol, propose the change to the user as an edit to the kit repo.
- If a session-start message says the protocols are out of date, tell the user once. Don't update without their go-ahead. If your tool has no hooks, run `.agents/bin/kit_ap check` once at the start of a session.

## Preregistration

Read and obey `.agents/protocols/PREREG_PROTOCOL.md` before running, modifying, or reporting any experiment, and `.agents/protocols/SCOPE_PROTOCOL.md` before building anything in a unit (an app, sim, tool, calculator, …; a folder with `preregistrations/`, or the repository itself).

- **A claim, or an exploratory label.** A unit starts with a falsifiable claim in the user's own words and what would count against it, recorded in its `SCOPE.toml`: one question, and the rest of the claim is stated when its first experiment is preregistered. If the user says a unit is exploratory, don't ask for a claim: record what is being built (`stage = "exploratory"`), label the unit exploratory, and build. Nothing an exploratory unit shows is a finding, and it gets its claim before its first experiment.
- Propose; never substitute. The user's claim, design and decisions are recorded as they give them.
- Infrastructure is yours to decide, following the organisation's conventions. Anything that implements a research concept, or presents a result in a way that changes what someone would conclude, is science: once the unit has a claim, build it only after it has an evidence basis and the user's recorded decision. A gap blocks that feature only.
- Ask one decision at a time. If you disagree, say so once, with evidence; then record and follow the user's choice.
- Never count a source you couldn't verify. `.agents/tools/scope-status` shows unscoped units and what is open.

<!-- kit_ap:end -->

<!-- scaffold:start -->
# olimex-shield

**Kind:** tool (`TOOL.toml`). Acquires, checks, records and exports EEG/ECG/EMG from an Arduino + Olimex SHIELD-EKG-EMG

- **No research here.** No questions, preregistrations, results or findings, no `RESEARCH.md`,
  `EXPERIMENTS.md`, `experiments/` or `preregistrations/`. A measurement made with this tool belongs to the study that made it.
- **Scope before science.** The claim, then the features, then an evidence basis and the person's recorded
  decision for every scientific feature, in `SCOPE.toml` (`.agents/protocols/SCOPE_PROTOCOL.md`). Infrastructure
  is yours to decide; nothing scientific is built before it is scoped. An override's experiment is
  preregistered in the research corpus, not here. A tool the person calls exploratory skips this until it
  gets its claim (`stage = "exploratory"` in `SCOPE.toml`); nothing it shows is a finding.
- **Releases** follow `.agents/protocols/TOOL_VERSIONING.md`; run `python3 .agents/tools/release-check` before
  tagging.
- **One version.** `version` in `TOOL.toml`, `pyproject.toml` and `CITATION.cff`, and a `CHANGELOG.md`
  heading, all agree; `scaffold check` fails when they drift. Releases are tagged `vX.Y.Z`.
- **Consumers.** Each repo that depends on this tool is listed in `TOOL.toml` with what it `uses`. A change
  to any of those is a change for that consumer even when every test here passes: name it under
  `### Outputs changed` in `CHANGELOG.md`.
- **No absolute home-directory paths.**


## Agents and coordination

Maintained by scientific-research-scaffold from scientific-research-agents (`scaffold update` keeps this section current; edits here are
replaced). The full rules are the [coordination protocol](https://github.com/polarizetech/scientific-research-agents/blob/v0.2.0/COORDINATION.md).

## Specialist roles

This repo has specialist roles, each briefed in a file under `.claude/agents/`. Claude Code delegates to
them as subagents. **Other assistants (ChatGPT, Codex and the rest): before a task of one of these kinds,
read that file and follow it as your brief.** When the environment supports and the user has authorized
subagents, the lead may delegate; otherwise apply the relevant brief in the current session.

| role | takes | brief |
|---|---|---|
| `scout` | finding and summarising; read-only | `.claude/agents/scout.md` |
| `computational-engineer` | simulators, models, numerical code, pipelines | `.claude/agents/computational-engineer.md` |
| `mathematician` | equations, constants, units and valid ranges; specifies calculators | `.claude/agents/mathematician.md` |
| `designer` | layout and visual design on the design system | `.claude/agents/designer.md` |
| `frontend-developer` | interfaces built from the designer's mockups | `.claude/agents/frontend-developer.md` |
| `researcher` | literature, evidence and evidence tiers | `.claude/agents/researcher.md` |
| `analyst` | data analysis and statistics | `.claude/agents/analyst.md` |
| `science-writer` | papers and blog posts | `.claude/agents/science-writer.md` |

- **Hand back briefly.** Each piece of work ends with a handoff of at most 150 words: Done, Files, Open,
  Next. Pass handoffs between roles, not transcripts.
- **The science gate.** A scientific feature goes researcher, then the person's decision, then engineer.
  Nothing skips the person's decision.
- **Parallel only when independent**: different files, at most three at a time, each in its own worktree.
- **Start cheap, escalate on a signal**: two failed attempts, a design decision across many files, or
  subtle scientific or statistical judgment. Escalate the task, not the session.
- **Codex:** use `gpt-5.6-sol`. Use low reasoning effort for finding and summarising, medium by default, and a higher effort supported by the selected model when escalating.
- **Scaffold version.** At the start of a session, run `scaffold version .` (or `../scientific-research-scaffold/bin/scaffold version .`). If it reports a newer release, tell the person and offer to upgrade, following the steps it prints (Claude Code runs this by itself).
<!-- scaffold:end -->
