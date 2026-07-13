---
name: retro
description: Weekly development retrospective. Mines session compliance data for repeating failure patterns, proposes CLAUDE.md rule updates, and auto-manages a strict rules section. Rules are max 1 line, directive, max 10 active (5 Critical + 5 Important). Use when user says "retro", "weekly retro", "retro-dev", "analyze sessions", "what mistakes do I keep making", or "update rules".
---

# Development Retrospective

Mine compliance data and the rules store, find repeating patterns, update CLAUDE.md rules.

## Process

### 1. Load Data

Read `.claude/sessions/rules.json` first. It is the source of truth. The Stop hook already maintains lifecycle state (`hits`, `sessions_since_hit`, `status`, auto-promotion at 2/4/8 hits, auto-archive after 10 clean sessions — 20 for important/critical). Do NOT recount hits or recompute status from raw events.

Then read `.claude/sessions/compliance.jsonl`. Aggregate:
- All `user_correction` events (group by `rule_key`, then `category`; read `snippet` for context)
- All `edit_compliance` events (group violations by file/pattern)
- All `commit_compliance` events
- All `safety_trigger` events
- All `session_summary` events (score trends)
- All `override_granted` events

If neither file has data, tell the user and stop.

### 2. Mine New Patterns

Find recurring patterns in compliance.jsonl that are NOT yet in the rules store. Compare `user_correction` rule_keys (`context_ignored`, `overengineering`, `breakage`, `wrong_direction`, `approach_change`) and violation groups against existing rule ids and text. Skip anything the store already tracks — the Stop hook counts those hits automatically.

For each new pattern with 2+ occurrences, propose adding it:

```
blackbox rules add "Never/Always [directive]." --key <rule_key>
```

Rules must be:
- Max 1 line
- Directive (imperative verb)
- No explanations, no examples

Deduplicate similar corrections before proposing rules.

### 3. Curate the Store

Recommend lifecycle changes via the CLI — never hand-edit counters or statuses in rules.json:

- **Archive stale**: `blackbox rules archive <id>` for rules that clearly no longer apply. The auto-archive (10 clean sessions; 20 for important/critical) handles the normal decay path — only intervene early with a reason.
- **Promote hot**: `blackbox rules promote <id> <status>` when a rule is running hotter than its auto-thresholds suggest (hits >=2 -> watch, >=4 -> important, >=8 -> critical) — e.g., a candidate that caused a block or revert deserves early promotion.

Trust the auto-lifecycle by default; intervene only when the evidence says a rule is hotter or colder than its counters.

### 4. Update CLAUDE.md

Regenerate the `## Rules (auto-updated by /retro)` section FROM the rules store — never from raw event counts. Include only `critical` and `important` rules; `candidate`, `watch`, and `archived` rules stay in the store.

**Rule format** (strict):
```
- Never/Always [directive]. (Nx)
```

Hit counts come straight from each rule's `hits` field.

```markdown
## Rules (auto-updated by /retro)
### Critical
- Never edit a file without reading it first. (12x)
- Never commit without running tests. (5x)

### Important
- Prefer direct implementation when user says "just do X". (7x)
- Always check exit codes after running commands. (3x)
```

**Max 10 active rules in CLAUDE.md** (5 Critical + 5 Important).

When over the limit, keep the highest-hit rules and archive the lowest-frequency rule with `blackbox rules archive <id>`.

### 5. Report

```
Development Retrospective -- YYYY-MM-DD
Sessions analyzed: N | Score trend: improving/declining/stable
Avg score: X.X

Rules Updated:
+ Added: "Never X" [candidate] (via blackbox rules add)
^ Promoted: "Always Y" important -> critical (Nx)
- Archived: "Check Z" (10 clean sessions)
```

## Rules

- Never delete session data -- archive only, and archive via `blackbox rules archive`
- Never hand-edit `hits`, `status`, or timestamps in rules.json -- always use the `blackbox rules` CLI
- Show proposed CLI commands and CLAUDE.md changes before running/writing them
- Rules must be actionable and specific
- Deduplicate before proposing (merge "check tests" and "run tests" into one)
- If same rule appears and mistake still happens, it needs a hook not a rule
