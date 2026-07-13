# blackbox

Your AI agent edits files it never read. Commits code it never tested. Makes the same mistake you corrected yesterday. And tells you everything went great.

**Blackbox catches all of it.**

## What You Get

After every Claude Code session, you see this:

```
+----------------------------------------------------------+
|  AGENT SCORECARD -- 2026-03-23                           |
+----------------------------------------------------------+
|                                                          |
|  Score: 6.2 / 10                           ######....   |
|                                                          |
|  Edits without reading first:  3 / 11          x 73%    |
|  Commits without tests:        1 / 2           x 50%    |
|  Destructive commands caught:  1                         |
|  User corrections:             4                         |
|                                                          |
|  Violations:                                             |
|  x Edited src/auth.ts without reading it                 |
|  x Edited utils/db.ts without reading it                 |
|  x Committed to main without running tests               |
|  x Attempted: rm -rf node_modules (blocked)              |
|                                                          |
|  Top corrections from user:                              |
|  - "just do it, stop overengineering" (efficiency)       |
|  - "I already told you that" (context)                   |
|                                                          |
+----------------------------------------------------------+
```

Not what Claude *says* happened. What *actually* happened.

## Install (10 seconds)

```bash
git clone https://github.com/cgallic/blackbox.git ~/.claude/skills/blackbox
cd ~/.claude/skills/blackbox && ./setup
```

Done. Works immediately. No config needed.

## What It Tracks

Eight hooks run silently during every Claude Code session:

| Signal | What It Proves |
|--------|---------------|
| Read before Edit | Did Claude read the file before changing it? |
| Test before Commit | Did Claude run tests before committing? |
| Destructive commands | Did Claude try `rm -rf`, `DROP TABLE`, force push? |
| User corrections | How many times did you redirect Claude? Logged live, as you type them |
| Session score | Weighted composite of accuracy, efficiency, context |

All signals are **ground-truth** — logged by hooks Claude cannot manipulate. Separate from Claude's self-reporting.

## Commands

```bash
blackbox report              # Full audit dashboard
blackbox history             # Score trend over sessions
blackbox backfill            # Mine past Claude Code sessions for patterns
blackbox rules               # List and manage learned rules
```

Inside Claude Code:
```
/scorecard                   # Show scorecard for current session
/retro                       # Weekly retrospective -- mine patterns, update rules
```

## How It Works

**Hooks track.** Eight Python scripts fire on every Read, Edit, Bash command, user prompt, and session lifecycle event. They write ground-truth signals to `.claude/sessions/compliance.jsonl`. You never touch them. When you correct Claude ("no, that's wrong", "I already told you", "simpler"), that's logged live too.

**Scorecard reports.** When your session ends, the Stop hook aggregates compliance data and prints the scorecard. No manual step required.

**Rules learn — automatically.** Every session end, blackbox converts what went wrong (blocked edits, untested commits, your corrections) into rules in a persistent store (`.claude/sessions/rules.json`). Rules have a lifecycle: Watch (2+ hits) → Important (4+) → Critical (8+). Rules that stop triggering get archived automatically. At the start of your next session, the active rules — plus what failed last session — are injected into Claude's context, so the lesson is in front of the agent *before* it can repeat the mistake. Inspect or curate with `blackbox rules`. Run `/retro` weekly for deeper pattern mining and CLAUDE.md updates.

## Backfill Past Sessions

Already have hundreds of Claude Code sessions? Mine them:

```bash
blackbox backfill                    # Lists all projects with session counts
blackbox backfill my-project-key     # Analyzes transcripts, generates scorecards
```

Extracts user corrections, errors, and approach changes from your historical Claude Code transcripts.

## Three Things That Change Immediately

**1. "Claude keeps editing files without understanding them"**
Before: You notice Claude changed a file it clearly didn't read. You're annoyed but move on.
After: Scorecard shows "Edits without reading: 4/12 (67%)". You see which files. You add a rule. Next session, the number drops.

**2. "Claude committed broken code"**
Before: You pull, build fails, spend 20 minutes debugging Claude's commit.
After: Scorecard shows "Commits without tests: 0/3 (100%)". The compliance hook caught it. Broken commits stop happening.

**3. "Claude makes the same mistake every session"**
Before: You correct the same behavior across 5 sessions. It never sticks.
After: Each correction is logged the moment you type it. By the second session the pattern is a Watch rule; by the fourth it's Important — and every new session starts with that rule injected into Claude's context. `/retro` handles the deeper weekly curation. The lesson compounds instead of evaporating.

## What Gets Installed

```
.claude/
├── hooks/              # 8 compliance tracking hooks (automatic)
├── sessions/           # Session logs, compliance data, learned rules (gitignored)
└── settings.local.json # Hook configuration (auto-merged)

~/.claude/skills/
├── blackbox/scorecard/ # /scorecard command
└── blackbox/retro/     # /retro command
```

No dependencies beyond Python 3.8 standard library. No network calls. No telemetry. All data stays on your machine.

## Requirements

- [Claude Code](https://claude.ai/code)
- Python 3.8+
- Git

## License

MIT

## Related links

- [MeetKai](https://meetkai.xyz) — the operator layer behind Kai CMO workflows.
- [KaiCalls](https://kaicalls.com) — AI voice agents for small-business phone answering and lead capture.
- [Connor Gallic](https://connorgallic.com) — founder building Kai, KaiCalls, and AI automation systems.
