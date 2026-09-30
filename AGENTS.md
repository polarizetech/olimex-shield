<!-- kit_ap:start -->
<!-- Managed by KIT Adaptive Preregistration (https://github.com/polarizetech/adaptive-preregistration.git). Don't edit between these markers: change the kit, then run `.agents/bin/kit_ap update`. -->

# Agent protocols

This repo uses **KIT Adaptive Preregistration**: agent protocols that are maintained in one central repo and vendored into `.agents/`. Every agent follows them, whatever the tool (Claude Code, Codex, Copilot, Cursor, Gemini, ChatGPT…).

- The rules in this block and the documents in `.agents/protocols/` are binding. If a task conflicts with one, stop and say so before doing the task.
- Project-specific instructions (outside these markers, or in nested `AGENTS.md` files) may add to the protocols. If one contradicts a protocol, ask the user which wins.
- Don't edit files in `.agents/` or text between the `kit_ap` markers. Updates overwrite them. To change a protocol, propose the change to the user as an edit to the kit repo.
- If a session-start message says the protocols are out of date, tell the user once. Don't update without their go-ahead. If your tool has no hooks, run `.agents/bin/kit_ap check` once at the start of a session.

## Preregistration

Read and obey `.agents/protocols/PREREG_PROTOCOL.md` before running, modifying, or reporting any experiment.

<!-- kit_ap:end -->

<!-- scaffold:start -->
## Agents and coordination

Maintained by scientific-research-scaffold from scientific-research-agents (`scaffold update` keeps this section current; edits here are
replaced). The full rules are the [coordination protocol](https://github.com/polarizetech/scientific-research-agents/blob/v0.1.1/COORDINATION.md).

This repo has specialist roles, each briefed in a file under `.claude/agents/`. Claude Code delegates to
them as subagents. **Other assistants (Codex and the rest): before a task of one of these kinds, read
that file and follow it as your brief.**

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
- **Codex:** use `gpt-5.6-sol`. Reasoning effort low for finding and summarising, medium by default, high or xhigh when escalating.
- **Scaffold version.** At the start of a session, run `scaffold version .` (or `../scientific-research-scaffold/bin/scaffold version .`). If it reports a newer release, tell the person and offer to upgrade, following the steps it prints (Claude Code runs this by itself).
<!-- scaffold:end -->
