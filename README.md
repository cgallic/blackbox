# retro-loop

A self-improving feedback loop for [Claude Code](https://claude.ai/code). Makes Claude learn from its mistakes across sessions by capturing what went wrong, mining patterns, and automatically updating rules.

## The Problem

Claude Code is powerful but repeats the same mistakes across sessions:
- **Overengineers** when you wanted something simple
- **Breaks things** and doesn't verify before committing
- **Forgets context** — makes the same errors you corrected last week
- **Scores itself generously** with no accountability

## The Solution

Three layers that compound over time:

```
LAYER 1: GOVERNANCE          LAYER 2: CAPTURE           LAYER 3: LEARNING
(prevent mistakes)           (record what happens)      (extract rules)

Safety hooks block           /retro-session scores      /retro-dev mines
destructive commands         each session and logs      session logs for
                             corrections + errors       repeating patterns
Compliance hooks track                                  and updates CLAUDE.md
read-before-edit and         Backfill script mines      rules automatically
test-before-commit           historical transcripts
                                                        Rules lifecycle:
Ground-truth signals         audit_sessions.py shows    Watch -> Important
can't be faked by            human-readable report      -> Critical -> Archive
the agent                    with calibration checks
```

## Quick Start

### 1. Install Skills (global, once)

```bash
git clone https://github.com/cgallic/retro-loop.git ~/.claude/skills/retro-loop
cd ~/.claude/skills/retro-loop && ./setup
```

This gives you two new slash commands in Claude Code:
- `/retro-session` — self-score at the end of any session
- `/retro-dev` — weekly retrospective to mine patterns and update rules

### 2. Set Up a Project (per project)

```bash
cd /path/to/your/project
~/.claude/skills/retro-loop/setup-project
```

This installs:
- Compliance hooks in `.claude/hooks/`
- Audit/backfill scripts in `scripts/`
- Session log directory at `.claude/sessions/` (gitignored)
- Hook configuration in `.claude/settings.local.json`

### 3. Backfill Historical Data (optional)

Mine your past Claude Code sessions for failure patterns:

```bash
# See all available projects
python scripts/backfill_sessions.py

# Backfill a specific project
python scripts/backfill_sessions.py <project-key>
```

### 4. View the Audit Report

```bash
python scripts/audit_sessions.py              # Full report
python scripts/audit_sessions.py --last 7     # Last 7 days
python scripts/audit_sessions.py --worst 5    # 5 worst sessions
python scripts/audit_sessions.py --product X  # Filter by product
```

## How It Works

### Session Capture (`/retro-session`)

Run at the end of any dev session. Claude self-scores on three dimensions:

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| **Accuracy** | 40% | Did it break things? Were there regressions? |
| **Efficiency** | 30% | Was the approach right? Or did it overengineer? |
| **Context** | 30% | Did it follow known rules? Or repeat past mistakes? |

Writes structured JSONL to `.claude/sessions/` with corrections, errors, learnings, and scores.

### Weekly Retrospective (`/retro-dev`)

Mines all session logs and:
1. Identifies repeating failure patterns
2. Counts how many sessions each mistake appears in
3. Proposes rule updates with hit counts
4. Updates the "Top Mistakes to Avoid" section of CLAUDE.md

Rules have a lifecycle:
```
New pattern (2+ hits) -> Watch
Hit 4+ times          -> Important
Caused revert/breakage -> Critical
Not triggered 30 days -> Archived
```

### Ground-Truth Hooks

Seven hooks that track objective signals Claude can't fake:

| Hook | Event | What It Tracks |
|------|-------|---------------|
| `session_init.py` | SessionStart | Resets tracking for new session |
| `track_read.py` | PostToolUse(Read) | Which files were read |
| `check_edit.py` | PostToolUse(Edit) | Was file read before editing? |
| `track_test.py` | PostToolUse(Bash) | Were tests run this session? |
| `check_commit.py` | PreToolUse(Bash) | Were tests run before commit? |
| `track_safety.py` | PostToolUse(Bash) | Destructive commands caught |
| `session_end.py` | Stop | Aggregates into session summary |

All hooks write to `.claude/sessions/compliance.jsonl` — separate from Claude's self-reported scores.

### Audit Report

```
================================================================
  Session Audit Report
================================================================

--- SCORES ----------------------------------------------------
  Composite:  8.2 avg  (min: 5.1, max: 10.0)
  Accuracy:   7.8 avg
  Efficiency: 8.5 avg
  Context:    8.4 avg

--- CALIBRATION CHECK ------------------------------------------
  WARNING: 3 sessions may have inflated scores:
    2026-03-15-session.jsonl [MyApp]
      - composite=9.5 but 4 corrections

--- USER CORRECTIONS -------------------------------------------
  just_do                     12x (28%)
  simpler                      8x (19%)
  i_said                       6x (14%)
  you_broke                    3x (7%)

--- RULE COMPLIANCE --------------------------------------------
  Edits read first:       42/45 (93%) ##################
    WARNING: 3 edit(s) without reading the file first
  Commits with tests:     8/10 (80%) ################
    WARNING: 2 commit(s) without running tests first
  Safety triggers:        1 destructive command(s) caught
```

### Backfill Script

Mines historical Claude Code transcripts (stored in `~/.claude/projects/`) for:
- User corrections ("no", "wrong", "stop", "undo", "just do", "simpler")
- Tool errors and test failures
- Approach changes and interruptions

Generates retro-session JSONL logs from the patterns found.

## Architecture

```
~/.claude/skills/retro-loop/          # Installed globally
├── skills/
│   ├── retro-session/SKILL.md        # Post-session scoring
│   └── retro-dev/SKILL.md            # Weekly retrospective
├── hooks/                            # Source hooks (copied to projects)
├── scripts/                          # Source scripts (copied to projects)
├── hooks.json                        # Hook config template
├── setup                             # Global installer
└── setup-project                     # Per-project installer

your-project/                         # Any project using retro-loop
├── .claude/
│   ├── hooks/                        # Compliance tracking hooks
│   ├── sessions/                     # Session logs + compliance.jsonl
│   └── settings.local.json           # Hook configuration
├── scripts/
│   ├── audit_sessions.py             # Audit dashboard
│   └── backfill_sessions.py          # Historical data mining
└── CLAUDE.md                         # Rules auto-updated by /retro-dev
```

## CLAUDE.md Integration

Add this to your project's CLAUDE.md to seed the rules section:

```markdown
## Investigation Before Action

- NEVER modify code you haven't read in this session
- NEVER propose a new function without searching if one already exists
- For bug fixes: reproduce first, form hypothesis, verify, then fix
- For features: read existing patterns before writing new code
- Run tests/build before committing, not after

## Top Mistakes to Avoid (Auto-Updated by /retro-dev)
Last updated: N/A | Sessions analyzed: 0 | Avg score: N/A

### Critical (caused reverts or breakage)
_No patterns yet._

### Important (caused rework)
_No patterns yet._

### Watch (emerging patterns)
_Run /retro-session at end of sessions to start collecting data._
```

## Requirements

- [Claude Code](https://claude.ai/code)
- Python 3.8+
- Git

## Inspiration

- [gstack](https://github.com/garrytan/gstack) — Garry Tan's Claude Code workflow governance
- [claude-reflect-system](https://github.com/haddock-development/claude-reflect-system) — Continual learning for Claude Code
- [CIPHER pattern](https://arxiv.org/html/2407.10944v1) — Implicit preference extraction from user edits

## License

MIT
