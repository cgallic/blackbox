---
name: retro-session
description: End-of-session self-review and scoring. Run at the end of any development session to capture what went well, what went wrong, and score the session on accuracy, efficiency, and context-awareness. Writes structured JSONL to .claude/sessions/ for the feedback loop. Use when user says "retro", "session review", "score this session", "how did you do", "end of session", or when wrapping up a significant work session.
---

# Session Retrospective

Run this at the end of a development session to capture learnings and score performance.

## Process

### 1. Gather Session Facts

Collect objective data about the session:

- List files created, modified, or deleted (use `git diff --stat` if available)
- List commands that errored
- List user corrections ("no", "wrong", "stop", "not that", "undo", approach changes)
- List rules from CLAUDE.md or memory files that were relevant but potentially missed
- Note the product/area worked on

### 2. Self-Score (Be Honest)

Score 1-10 on three dimensions. Be brutally honest — inflated scores defeat the purpose.

**Accuracy** (weight: 0.4)
- 1-3: Broke things, user had to revert, introduced regressions
- 4-6: Minor issues caught in review, some things needed fixing
- 7-9: Clean execution, everything worked
- 10: Zero issues, production-ready on first attempt

**Efficiency** (weight: 0.3)
- 1-3: Wrong approach, rebuilt multiple times, massive overengineering
- 4-6: Some exploration but found the right path eventually
- 7-9: Direct path to solution with minimal waste
- 10: Optimal approach, no wasted effort

**Context** (weight: 0.3)
- 1-3: Forgot known rules, repeated past mistakes, ignored CLAUDE.md
- 4-6: Followed most rules, missed some relevant context
- 7-9: Applied all relevant rules and conventions
- 10: Proactively used context to avoid potential issues

**Composite** = `(accuracy * 0.4) + (efficiency * 0.3) + (context * 0.3)`

### 3. Identify Failure Patterns

For each thing that went wrong, categorize:

| Category | Examples |
|----------|----------|
| `wrong_approach` | Started building before understanding, overengineered |
| `regression` | Broke existing functionality, failed tests |
| `forgotten_rule` | Ignored CLAUDE.md rule, repeated known mistake |
| `missing_verification` | Didn't test, didn't run build, didn't check |
| `scope_creep` | Added unrequested features, unnecessary refactoring |
| `context_loss` | Forgot project-specific conventions, wrong patterns |

### 4. Extract Learnings

For each failure, write a candidate rule:
```
[PRODUCT] When doing X, always Y because Z
```

Check if this rule already exists in CLAUDE.md or memory files. If it does, flag it as "forgotten" (higher priority for /retro-dev).

### 5. Write Session Log

Write a JSONL file to the project's `.claude/sessions/` directory.

**File**: `.claude/sessions/YYYY-MM-DD-HHMMSS.jsonl`

Each line is a JSON object:

```json
{"type":"session_start","ts":"ISO8601","product":"MyApp","branch":"feature-x","task_summary":"Fixed image rendering"}
{"type":"user_correction","ts":"ISO8601","what":"User said to stop overengineering","context":"Was adding abstraction for one-time operation"}
{"type":"error","ts":"ISO8601","command":"npm test","error":"TypeError: Cannot read property...","was_my_fault":true}
{"type":"forgotten_rule","ts":"ISO8601","rule":"Scope string search to target endpoint first","source":"CLAUDE.md"}
{"type":"regression","ts":"ISO8601","what":"Broke carousel by changing shared CSS class","files":["index.html"]}
{"type":"learning","ts":"ISO8601","category":"wrong_approach","rule":"[ALL] Check if endpoint already handles case before adding new route","is_new":true}
{"type":"session_end","ts":"ISO8601","scores":{"accuracy":6,"efficiency":7,"context":5,"composite":6.0},"files_changed":3,"user_corrections":1,"errors":1,"new_learnings":1,"forgotten_rules":1}
```

### 6. Report to User

After writing the log, display a brief summary:

```
Session Score: 6.0/10 (Accuracy: 6, Efficiency: 7, Context: 5)

Issues:
- Forgot: "Scope string search to target endpoint first"
- New learning: "[ALL] Check if endpoint already handles case before adding new route"

Session logged to .claude/sessions/2026-03-22-154500.jsonl
```

## Rules

- Be honest in scoring. A session where the user corrected you twice is NOT a 9.
- If no `.claude/sessions/` directory exists, create it.
- If the session was trivial (quick question, no code changes), skip the log and say so.
- Every user correction is a signal — capture it even if it seems minor.
- Don't ask the user to validate scores — score yourself and let the weekly retro catch drift.
