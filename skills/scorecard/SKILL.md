---
name: scorecard
description: Show the agent compliance scorecard for the current session. Displays ground-truth metrics from hooks — edits without reading, commits without testing, destructive commands, overrides used, and a session timeline. Use when user says "scorecard", "how am I doing", "show compliance", "session score", or "agent score".
---

# Agent Scorecard

Display the current session's compliance scorecard based on ground-truth hook data.

## Process

1. Read `.claude/sessions/compliance.jsonl`
2. Find the most recent `session_start` event
3. Aggregate all events since that start:
   - `edit_compliance` events (was_read_first, was_overridden)
   - `commit_compliance` events (tests_passed_first, was_overridden)
   - `safety_trigger` events (pattern, severity, occurrence)
   - `override_granted` events (action, reason)
4. Calculate session score (start at 10, deductions for violations)
5. Build and display the scorecard

## Score Calculation

- Start at 10.0
- Each unread edit: -1.0 (overridden: -0.5)
- Each untested commit: -1.5 (overridden: -0.75)
- Each safety trigger: -0.5
- Repeated violations (>5 total): -0.25 per additional

## Output Format

```
+----------------------------------------------------------+
|  AGENT SCORECARD -- YYYY-MM-DD                           |
+----------------------------------------------------------+
|  Score: X.X / 10                           ######....    |
|  Edits without reading first:  N / M          XX%        |
|  Commits without tests:        N / M          XX%        |
|  Destructive commands caught:  N                         |
|  Timeline:                                               |
|    HH:MM  EDIT file.py (read first)                      |
|    HH:MM  EDIT other.py ** NOT READ **                   |
|    HH:MM  COMMIT (tests passed)                          |
+----------------------------------------------------------+
```

## Rules

- Only show data from the CURRENT session (since last session_start)
- Never fabricate data — if compliance.jsonl is empty, say so
- Show the timeline in chronological order
- Score is calculated, never estimated
