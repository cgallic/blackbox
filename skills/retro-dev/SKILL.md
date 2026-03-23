---
name: retro-dev
description: Weekly development retrospective that mines session logs for repeating failure patterns and proposes CLAUDE.md rule updates. Analyzes .claude/sessions/*.jsonl files, identifies patterns across sessions, extracts rules, and updates the "Top Mistakes to Avoid" section of CLAUDE.md. Use when user says "weekly retro", "retro-dev", "analyze sessions", "what mistakes do I keep making", "update rules", or at the start of each week to process accumulated session data.
---

# Development Retrospective

Mine accumulated session logs to find repeating patterns, extract rules, and update CLAUDE.md.

## Process

### 1. Load Session Data

Read all `.claude/sessions/*.jsonl` files. If no session files exist, inform the user that `/retro-session` needs to be run at the end of sessions first.

Aggregate across all sessions:
- Total sessions, date range
- Average composite score and trend (improving/declining?)
- All `learning` events grouped by category
- All `forgotten_rule` events grouped by rule
- All `user_correction` events
- All `error` events where `was_my_fault: true`
- All `regression` events

### 2. Pattern Detection

**Repeating mistakes** (highest priority):
- Count how many sessions each `learning` rule appears in
- Count how many times each `forgotten_rule` fires
- Group by product tag

**Score trends**:
- Are accuracy/efficiency/context improving or declining?
- Which dimension is weakest?

**Failure categories**:
- Rank by frequency: wrong_approach, regression, forgotten_rule, missing_verification, scope_creep, context_loss

### 3. Propose Rule Updates

For each pattern with 2+ occurrences:

**New rules** (pattern not in CLAUDE.md):
```
PROPOSE ADD [Critical/Important/Watch]: Rule text (hit Nx in N sessions)
```

**Promotions** (existing rule being forgotten):
```
PROPOSE PROMOTE: "Rule text" from Watch -> Important (forgotten Nx)
```

**Demotions** (rule not triggered in 30+ days):
```
PROPOSE ARCHIVE: "Rule text" (last triggered YYYY-MM-DD)
```

### 4. Update CLAUDE.md

Find or create the `## Top Mistakes to Avoid` section:

```markdown
## Top Mistakes to Avoid (Auto-Updated by /retro-dev)
Last updated: YYYY-MM-DD | Sessions analyzed: N | Avg score: X.X

### Critical (caused reverts or breakage)
1. Rule text (hit Nx)

### Important (caused rework)
1. Rule text (hit Nx)

### Watch (emerging patterns)
1. Rule text (hit Nx in last week)
```

**Tier rules**:
- **Critical**: Caused a revert/regression OR hit 6+ times
- **Important**: Hit 4+ times OR promoted from Watch
- **Watch**: Hit 2-3 times in recent sessions
- **Archive**: Not triggered in 30+ days — remove from section

Max 15 rules total (5 per tier). If over limit, archive oldest low-hit rules.

### 5. Report Summary

```
Development Retrospective -- YYYY-MM-DD
Sessions: N (date range)
Avg Score: X.X (trend: improving/declining/stable)
Weakest: [dimension] at X.X avg

Top Failure Mode: [category] (N occurrences)

Rules Updated:
+ Added: "Rule text" [Important]
^ Promoted: "Rule text" Watch -> Critical
- Archived: "Rule text" (not triggered in 45 days)
```

## Rules

- Never delete session log files — archive only
- Show proposed changes to user before writing to CLAUDE.md
- Rules must be actionable and specific — "be more careful" is not a rule
- Include the hit count so the user can see which rules matter most
- If a rule exists and the same mistake still happens, the rule needs to be stronger (move to a hook)
