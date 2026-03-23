# Blackbox Transformation Spec

## 1. REPOSITIONING

**One-line pitch:**
> Claude Code breaks things. Blackbox catches it.

**Two-line subheadline:**
> Every file edit, every commit, every destructive command — logged and scored.
> You see exactly where your agent screwed up, every session, automatically.

**What pain this solves RIGHT NOW:**

Claude Code edits files it never read. It commits without running tests. It makes the same mistake you corrected last Tuesday. It tells you everything went great when it broke three things. You have no way to know until you find the damage.

Blackbox creates an objective record of what actually happened — not what Claude claims happened. After every session, you get a scorecard showing: files edited without reading (compliance failure), commits without tests (compliance failure), destructive commands caught, and a severity-weighted score. It's a dashcam for your AI agent.

**Why Claude Code users install this immediately:**

Because they've had a session where Claude said "Done!" and the build was broken. Because they've corrected the same behavior three times across three sessions and it keeps coming back. Because they can't audit what Claude actually did vs what it said it did. Blackbox gives them the receipts.

**What category this becomes:**

Agent observability. Same category as Datadog for servers or Sentry for errors — but for AI agent behavior. The dashcam, not the engine.

**What it is NOT:**
- Not a prompt optimizer
- Not an agent framework
- Not a model fine-tuning pipeline
- Not a workflow orchestrator
- It does not make Claude smarter. It makes Claude accountable.

---

## 2. THE INSTALL WEDGE

**Name: Agent Scorecard**

The scorecard is the single artifact that makes this spread. It's a terminal-rendered report card for your AI agent's last session. It shows compliance metrics, caught mistakes, and a blunt score. It looks slightly embarrassing — which is why people screenshot it.

**Exact user flow:**

1. User installs Blackbox (one command, 10 seconds)
2. User works with Claude Code normally
3. Session ends (user exits or types `/done`)
4. Terminal prints the Agent Scorecard automatically
5. User sees exactly what Claude got wrong
6. User shares screenshot because the score is either impressively bad or impressively good

**Exact CLI commands:**

```bash
git clone https://github.com/cgallic/blackbox.git ~/.claude/skills/blackbox
cd ~/.claude/skills/blackbox && ./setup
```

That's it. No `setup-project`. No second step. Setup detects the current project, installs hooks, creates directories. One command.

**Exact output (mock terminal — printed automatically when session ends):**

```
+----------------------------------------------------------+
|  AGENT SCORECARD -- session 2026-03-23                   |
+----------------------------------------------------------+
|                                                          |
|  Score: 6.2 / 10                           ######....   |
|                                                          |
|  Edits without reading first:  3 / 11          x 73%    |
|  Commits without tests:        1 / 2           x 50%    |
|  Destructive commands caught:  1                         |
|  User corrections:             4                         |
|                                                          |
|  Worst violations:                                       |
|  x Edited src/auth.ts without reading it                 |
|  x Edited utils/db.ts without reading it                 |
|  x Committed to main without running tests               |
|  x Attempted: rm -rf node_modules (blocked)              |
|                                                          |
|  Top corrections from user:                              |
|  - "just do it, stop overengineering" (efficiency)       |
|  - "I already told you that" (context)                   |
|                                                          |
|  Run: blackbox report        Full audit dashboard        |
|  Run: blackbox history       Score trend over time       |
+----------------------------------------------------------+
```

**What the user learns instantly:**

Their agent edited 3 files it never read. It committed once without testing. It tried to `rm -rf` something. It had to be corrected 4 times. This is not abstract — it's a list of specific violations with file names.

**Why this spreads:**

1. **Screenshots.** The scorecard is visually distinct. Score of 4/10 is funny. Score of 10/10 is bragging rights. Both get posted.
2. **Ego.** Developers compare scores. "My agent scored 8.7 today." It becomes a metric people track.
3. **Fear.** "My agent edited 5 files without reading them" is alarming. That alarm is productive — it drives installs.
4. **Proof.** When someone says "Claude Code is unreliable," you can now show data instead of anecdotes.

---

## 3. README REWRITE

See `README.md` in the repo root. Key principles:
- Hook in first 3 seconds (pain + scorecard)
- Show value before explaining architecture
- Install is one copy-paste command
- First result is automatic (no manual step)
- Cut architecture diagrams, academic framing, anything that delays value

---

## 4. FIRST-RUN EXPERIENCE

**Exact install command:**
```bash
git clone https://github.com/cgallic/blackbox.git ~/.claude/skills/blackbox
cd ~/.claude/skills/blackbox && ./setup
```

**What happens automatically during `./setup`:**

1. Symlinks `/scorecard` and `/retro` skills into `~/.claude/skills/`
2. Detects current working directory — if it's a git repo, runs project setup automatically
3. Copies hooks to `.claude/hooks/`
4. Creates `.claude/sessions/` (gitignored)
5. Merges hook config into `.claude/settings.local.json`
6. Prints confirmation:

```
blackbox installed.

Hooks active in: /home/user/my-project
  + Track file reads
  + Verify read-before-edit
  + Track test runs
  + Verify test-before-commit
  + Block destructive commands
  + Session scorecard on exit

Next: use Claude Code normally. Scorecard prints when you exit.
```

**What the user sees after first session ends:**

The Stop hook fires, aggregates compliance.jsonl, and prints the scorecard to the terminal. No manual step. The user just worked normally and got accountability for free.

**The first scorecard must:**
- Call out mistakes clearly (file names, commands)
- Show compliance percentages (73% is worse than it sounds)
- Feel slightly uncomfortable (in a good way)
- Make the user want to run it again

---

## 5. CLAUDE CODE INTEGRATION

**`.claude/` structure after install:**

```
.claude/
+-- hooks/
|   +-- session_init.py        # SessionStart: reset tracking
|   +-- track_read.py          # PostToolUse(Read): log reads
|   +-- check_edit.py          # PostToolUse(Edit): verify read-before-edit
|   +-- track_test.py          # PostToolUse(Bash): detect test runs
|   +-- check_commit.py        # PreToolUse(Bash): verify test-before-commit
|   +-- track_safety.py        # PostToolUse(Bash): log destructive cmds
|   +-- session_end.py         # Stop: aggregate + print scorecard
+-- sessions/
|   +-- 2026-03-23-141500.jsonl
|   +-- compliance.jsonl
+-- settings.local.json        # Hook config (auto-merged)
```

**What runs automatically vs manually:**

| Automatic (zero effort) | Manual (opt-in) |
|------------------------|----------------|
| All 7 hooks | `/retro` weekly retrospective |
| Scorecard on session end | `blackbox report` full audit |
| Compliance logging | `blackbox backfill` historical mining |
| Safety command blocking | CLAUDE.md rule updates |

**3 concrete use cases Claude Code users care about:**

**1. "Claude keeps editing files without understanding them"**
Before: You notice Claude changed a file it clearly didn't read. You're annoyed but move on.
After: Scorecard shows "Edits without reading: 4/12 (67%)". You see which files. You add a rule. Next session, the number drops.

**2. "Claude committed broken code"**
Before: You pull, build fails, spend 20 minutes debugging Claude's commit.
After: check_commit.py verifies tests ran first. Scorecard shows "Commits without tests: 0/3 (100%)". Broken commits stop happening.

**3. "Claude makes the same mistake every session"**
Before: You correct the same behavior across 5 sessions. It never sticks.
After: `/retro` mines all 5 sessions, finds the pattern, proposes a CLAUDE.md rule: "[ALL] When user says 'just do X', do exactly X (hit 7x)". The rule compounds.

---

## 6. TRUST + CREDIBILITY FIXES

**What needs to exist in the repo:**

| Item | Priority |
|------|----------|
| Test suite (57 tests) | Done |
| CI via GitHub Actions | Ship with rename |
| Tagged release (v0.1.0) | Ship with rename |
| `blackbox` CLI wrapper | Ship with rename |
| CHANGELOG.md | Create at v0.1.0 |

**Final repo structure:**

```
blackbox/
+-- bin/
|   +-- blackbox              # CLI: report, history, backfill
+-- skills/
|   +-- scorecard/SKILL.md    # /scorecard (was /retro-session)
|   +-- retro/SKILL.md        # /retro (was /retro-dev)
+-- hooks/
|   +-- *.py                  # 7 compliance hooks
+-- scripts/
|   +-- report.py             # Full audit dashboard
|   +-- backfill.py           # Historical transcript mining
+-- tests/
|   +-- test_hooks.py         # 57 tests
+-- .github/
|   +-- workflows/
|       +-- test.yml          # CI on push
+-- setup                     # One-command installer
+-- LICENSE
+-- CHANGELOG.md
+-- README.md
```

**CLI commands:**

```bash
blackbox report              # Full audit dashboard
blackbox history             # Score trend over sessions
blackbox backfill            # Interactive project selector
blackbox backfill <key>      # Mine specific project
blackbox version             # Print version
```

**What makes someone trust this enough to install:**
- Tests pass in CI (green badge)
- Tagged release with version number
- MIT license
- No dependencies beyond Python 3.8 stdlib
- No network calls, no telemetry, no data leaving the machine
- All data stored in `.claude/sessions/` (local, gitignored)

---

## 7. NAMING

**Recommendation: `blackbox`**

One word. Everyone knows what a black box is. It records what happened. "I installed blackbox on my Claude Code" — instantly clear.

**Rename map:**

| Current | New | Why |
|---------|-----|-----|
| retro-loop | blackbox | Flight recorder, not a feedback loop |
| `/retro-session` | `/scorecard` | Users know what a scorecard is |
| `/retro-dev` | `/retro` | Shorter. Weekly retro is already dev vocabulary |
| `audit_sessions.py` | `report.py` | "Run the report" is simpler |
| `backfill_sessions.py` | `backfill.py` | Drop the `_sessions` |
| `compliance.jsonl` | Keep | Correct term. Don't soften it |

**Alternative names considered:**

| Name | Feel |
|------|------|
| blackbox | Flight recorder. Install before the crash. |
| guardrail | Safety infrastructure. Prevents falls. |
| dashcam | Recording device. Proves what happened. |
| tripwire | Catches intrusions. Alerts on violations. |
| flightlog | Aviation recorder. Post-incident analysis. |

---

## 8. WHAT TO DELETE OR SIMPLIFY

**Delete:**

| Item | Why |
|------|-----|
| `setup-project` (separate script) | Merge into `setup`. One command, not two. |
| `hooks.json` (separate template) | Inline into setup script. Users never touch this. |
| Architecture diagram in README | Delays value. Move to docs/ if needed. |
| "Inspiration" section in README | Nobody cares what inspired it. They care what it does. |
| "CLAUDE.md Integration" section in README | Move to separate guide. |
| Verbose scoring rubric in SKILL.md | Simplify to 3 dimensions + weights. |

**Hide (move out of README, keep in repo):**

| Item | Move to |
|------|---------|
| Backfill script details | `blackbox backfill --help` |
| Rule lifecycle details | `/retro` SKILL.md only |
| Hook implementation details | `docs/hooks.md` |
| Session JSONL schema | `docs/schema.md` |

**Simplify:**

| Current | Simplified |
|---------|-----------|
| Two setup commands (global + per-project) | One `./setup` that does both |
| 7 hook files explained individually | "7 hooks run automatically" |
| Three-layer architecture explanation | "Hooks track. Scorecard reports. Rules learn." |

**Goal: README fits on one screen. Install is one command. First value is automatic.**

---

## 9. IMPLEMENTATION CHECKLIST

- [ ] Rename GitHub repo: cgallic/retro-loop -> cgallic/blackbox
- [ ] Rename skills: retro-session -> scorecard, retro-dev -> retro
- [ ] Rename scripts: audit_sessions.py -> report.py, backfill_sessions.py -> backfill.py
- [ ] Create bin/blackbox CLI wrapper
- [ ] Merge setup + setup-project into single setup
- [ ] Rewrite README with new copy
- [ ] Update SKILL.md files with new names/descriptions
- [ ] Add scorecard rendering to session_end.py (Stop hook)
- [ ] Add GitHub Actions CI (.github/workflows/test.yml)
- [ ] Update test suite for renamed files
- [ ] Create CHANGELOG.md
- [ ] Tag v0.1.0 release
- [ ] Push
