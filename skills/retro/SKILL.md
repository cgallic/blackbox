---
name: retro
description: Weekly development retrospective. Mines session compliance data for repeating failure patterns, proposes CLAUDE.md rule updates, and auto-manages a strict rules section. Rules are max 1 line, directive, max 10 active (5 Critical + 5 Important). Use when user says "retro", "weekly retro", "retro-dev", "analyze sessions", "what mistakes do I keep making", or "update rules".
---

# Development Retrospective

Mine compliance data, find repeating patterns, update CLAUDE.md rules.

## Process

### 1. Load Data

Read `.claude/sessions/compliance.jsonl`. Aggregate:
- All `edit_compliance` events (group violations by file/pattern)
- All `commit_compliance` events
- All `safety_trigger` events
- All `session_summary` events (score trends)
- All `override_granted` events

If no data exists, tell the user and stop.

### 2. Find Patterns

Group violations by type. For each type, count:
- **frequency**: total occurrences across all sessions
- **severity**: did it cause a block? was it overridden?
- **recency**: when was the last occurrence?

Deduplicate similar corrections before proposing rules.

### 3. Propose Rules

For patterns with 2+ occurrences, propose rules.

**Rule format** (strict):
```
- Never/Always [directive]. (Nx)
```

Rules must be:
- Max 1 line
- Directive (imperative verb)
- No explanations, no examples
- Include hit count in parentheses

### 4. Update CLAUDE.md

Find or create the `## Rules (auto-updated by /retro)` section.

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

**Tier rules**:
- **Critical**: caused a block/revert OR 6+ occurrences
- **Important**: 3+ occurrences OR promoted from Watch
- **Watch**: 2 occurrences — DO NOT add to CLAUDE.md, archive only

When over the limit, archive the lowest-frequency rule.

### 5. Archive

Write demoted/Watch rules to `.claude/sessions/archived-rules.jsonl`:
```json
{"rule": "...", "hits": 2, "tier": "watch", "last_seen": "...", "archived_at": "..."}
```

### 6. Report

```
Development Retrospective -- YYYY-MM-DD
Sessions analyzed: N | Score trend: improving/declining/stable
Avg score: X.X

Rules Updated:
+ Added: "Never X" [Critical] (Nx)
^ Promoted: "Always Y" Important -> Critical (Nx)
- Archived: "Check Z" (not triggered in 30 days)
```

## Rules

- Never delete session data -- archive only
- Show proposed changes before writing to CLAUDE.md
- Rules must be actionable and specific
- Deduplicate before proposing (merge "check tests" and "run tests" into one)
- If same rule appears and mistake still happens, it needs a hook not a rule
