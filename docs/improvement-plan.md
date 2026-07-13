# Blackbox Improvement Plan

Goal: evolve blackbox from a promising v0.1.0 demo into a tool people keep
installed. The ordering principle: **make every existing claim true first**,
then make the tool configurable, then make it smarter, then make it easier
to distribute. An observability tool that reports wrong numbers is worse than
no tool at all — trust is the product.

---

## Phase 1 — Correctness: make the current claims true

These are verified gaps between what the README/scorecard say and what the
code does. Each one erodes trust the moment a user notices it.

### 1.1 `Write` and `NotebookEdit` bypass read-before-edit entirely

`check_edit.py` is only registered with `matcher: "Edit"` (setup, line 91).
Overwriting a file with `Write` — strictly worse than editing unread — is
never checked and never logged. Fix:

- Register `check_edit.py` for `Edit|Write|NotebookEdit`.
- Track `Write` in `track_read.py` as "content known": after Claude writes a
  file, it knows the contents. Today, Write-then-Edit is **falsely blocked**
  because the written file was never `Read`.
- Exempt files that don't exist yet (new-file creation is not an unread edit).

### 1.2 "Destructive commands caught" isn't blocking anything

`track_safety.py` is a **PostToolUse** hook — by the time it fires, the
`rm -rf` already ran. The README's "Attempted: rm -rf node_modules (blocked)"
is currently impossible. Fix:

- Move destructive-command detection to a **PreToolUse** hook returning
  `permissionDecision: "ask"` (surface to user) or `"deny"` per pattern
  severity. Keep the PostToolUse variant only as a logger for patterns that
  slipped through (e.g. inside scripts).
- Reword scorecard lines to distinguish `blocked` / `asked` / `logged` —
  never claim a block that didn't happen.

### 1.3 Setup silently destroys the user's existing hooks

`setup` does `existing["hooks"] = hooks_config` — a user with their own
hooks in `settings.local.json` loses them all on install. Fix: merge
per-event, append blackbox entries only if absent (idempotent re-runs),
and print what was preserved vs added.

### 1.4 Session state model is racy and collision-prone

All tracking state lives in `$TMPDIR/claude-*-{md5(project)[:8]}.txt`, keyed
by project only. Two concurrent sessions in the same repo (very common:
main session + subagents, or two terminals) share and clobber each other's
state — `session_init.py` **deletes** the other session's read-tracking, and
every edit gets falsely blocked. Fix:

- Key all state by `session_id` (every hook receives it on stdin), stored
  under `.claude/sessions/state/<session_id>/` instead of tempdir.
- Garbage-collect state dirs older than N days in `session_init.py`.
- Decide explicit subagent policy: reads by a subagent count for the parent
  session or not (recommend: count them — the agent system did read the file).

### 1.5 Stale test-pass marker

`track_test.py` writes a `"passed"` marker once; editing ten more files
afterwards leaves the marker valid, so `check_commit.py` waves the commit
through. Fix: record the timestamp of the last passing test run and the
timestamp of the last edit; a commit requires *tests after the last edit*.
This single change makes test-before-commit enforcement honest.

### 1.6 Fragile test-outcome detection

Pass/fail is inferred by regexing tool output for `Error:` / `FAIL` — a
passing suite that logs `error:` counts as failed; `python .*test`
overmatches unrelated commands. Fix:

- Prefer exit codes: PostToolUse for Bash receives the tool response which
  includes exit status in current Claude Code — use it, fall back to regex.
- Narrow `TEST_PATTERNS` (e.g. `python -m pytest`, `python -m unittest`)
  and make them configurable (see Phase 2).

### 1.7 Scorecard rendering and naming polish

- Box-drawing widths are hand-padded and already overflow (session_end.py
  lines 183–184). Build rows with a helper that pads/truncates to width.
- One canonical pair of skill names. Today: README says `/scorecard`,
  setup links `blackbox-scorecard`, session_end prints `/blackbox-scorecard`.
  Pick `/blackbox-scorecard` + `/blackbox-retro` (namespaced, no clashes)
  and use them everywhere.

**Exit criteria for Phase 1:** every number on the scorecard is reproducibly
true, concurrent sessions don't corrupt each other, and a fresh install on a
repo with existing hooks changes nothing it didn't announce.

---

## Phase 2 — Configuration and enforcement modes

Enforcement-always-on is the #1 reason users will uninstall. One blocked
legitimate commit (monorepo with integration tests only, docs-only change
mis-detected, generated code) and the tool is gone.

### 2.1 `blackbox.json` project config

Single config file at `.claude/blackbox.json`, read by every hook:

```json
{
  "mode": "enforce",            // "observe" | "warn" | "enforce"
  "read_before_edit": true,
  "test_before_commit": true,
  "test_commands": ["make test", "npm test"],
  "test_scope": "session",      // "session" | "diff-aware"
  "safety": {
    "deny": ["rm -rf /", "DROP TABLE"],
    "ask":  ["git push --force", "git reset --hard"]
  },
  "exempt_paths": ["dist/**", "*.generated.*"]
}
```

- **observe** logs everything, blocks nothing — this should be the
  **default for new installs**. Users graduate to `warn`/`enforce` after
  seeing a week of scorecards. Observability first, enforcement opt-in.
- `blackbox config set mode enforce` CLI for editing without hand-JSON.
- Diff-aware test mapping (basename matching in `check_commit.py`) becomes
  opt-in — it's clever but wrong for most repo layouts; the session-level
  "did fresh tests pass" check is the robust default.

### 2.2 Replace the override tempfile with something inspectable

`blackbox override edit --reason ...` works, but overrides should be logged
into `compliance.jsonl` at grant time and consumed per-use, with the reason
shown on the scorecard ("1 override used: emergency hotfix"). Overrides are
signal, not a bypass valve to hide.

---

## Phase 3 — Richer signals (the moat)

The current signals are edit/commit/safety. The advertised killer feature —
"user corrections: 4" — only exists in backfill, not live.

### 3.1 Live user-correction tracking

Add a `UserPromptSubmit` hook that classifies incoming prompts with the same
heuristics `backfill.py` already has (correction phrases: "no, I said",
"again", "I already told you", "stop", "undo"). Log
`{"type": "user_correction", "category": ...}`. This makes the README's
headline scorecard real for live sessions and is mostly code reuse.

### 3.2 Failure/retry signals

- Tool errors: PostToolUse sees failed Bash commands — count command
  failures and consecutive-retry loops ("agent thrashing" metric).
- Edit churn: same file edited 4+ times in one session is a strong
  proxy for flailing; cheap to compute from existing events.

### 3.3 Positive signals and a defensible score

The score today only subtracts. Add the denominators that already exist
(clean edits, tested commits) and publish the formula in `docs/scoring.md`
so a screenshot of "8.7/10" is explainable. Keep it simple:
`accuracy (blocked actions avoided) × hygiene (read/test rates) × learning
(no repeats from prior sessions)`.

---

## Phase 4 — Reporting & CLI UX

- `blackbox report --json` and `--md` output for piping into other tools;
  the terminal dashboard stays the default.
- `blackbox doctor` — verify hooks installed, settings merged, state dir
  writable, Python found, versions match. Half of all support issues for
  hook-based tools are "it silently isn't running"; doctor makes that a
  10-second self-check.
- `blackbox uninstall` — remove hooks + settings entries cleanly (mirror of
  the Phase 1.3 merge logic). A tool that blocks commits **must** have a
  clean exit.
- `blackbox update` — re-copy hooks into the project after `git pull` of the
  blackbox repo; print old→new version. (Superseded by Phase 5 if plugin
  packaging lands first.)
- Weekly digest: `blackbox report --week` summarizing trend, top violations,
  and rules proposed by `/blackbox-retro` — feeds the retro habit the README
  already sells.

---

## Phase 5 — Distribution

### 5.1 Package as a Claude Code plugin (recommended endgame)

Claude Code plugins bundle hooks + skills + commands with marketplace
install (`/plugin install blackbox`). This replaces the entire custom
`setup` script, the settings.local.json merging, the per-project hook
copying (and its version-skew problem), and the PATH suggestion. The
`.claude-plugin/plugin.json` + `hooks/hooks.json` layout maps 1:1 onto the
existing repo structure. Keep `./setup` as the non-plugin fallback.

### 5.2 Windows reality check

README claims Windows (python fallback) but `bin/blackbox` and `setup` are
bash. Either port the CLI to Python (`python -m blackbox ...` — the CLI is
54 lines of dispatch, trivial to port) or scope the README claim to
WSL/Git-Bash. Recommend the Python port: it also unlocks `pipx install
blackbox-claude` as a second distribution channel.

### 5.3 CI hardening

Extend `test.yml` to a matrix (ubuntu/macos/windows × Python 3.8/3.12) and
add an integration test that runs `./setup` in a scratch repo and asserts
the settings merge preserved pre-existing hooks (regression test for 1.3).

---

## Sequencing and effort

| Order | Item | Size | Impact |
|-------|------|------|--------|
| 1 | 1.3 settings merge fix | S | Stops destroying user config — ship immediately |
| 2 | 1.1 Write/NotebookEdit coverage + new-file exemption | S | Closes the biggest enforcement hole + worst false positive |
| 3 | 1.5 stale test marker | S | Makes commit enforcement honest |
| 4 | 1.2 real safety blocking (PreToolUse) | M | Makes the headline claim true |
| 5 | 1.4 session-scoped state | M | Fixes concurrent-session corruption |
| 6 | 2.1 config + observe mode default | M | Retention: stops rage-uninstalls |
| 7 | 1.6, 1.7 detection + rendering polish | S | Trust polish |
| 8 | 3.1 live user corrections | M | Delivers the advertised metric |
| 9 | 4.x doctor / uninstall / json output | M | Supportability |
| 10 | 5.1 plugin packaging | M | Install friction → near zero |
| 11 | 3.2–3.3 richer signals + scoring doc | M | Differentiation |

Phases 1–2 (items 1–7) are a coherent v0.2.0. Phase 3+4 make v0.3.0.
Plugin packaging is v0.4.0 or whenever the plugin marketplace timing is
right.
