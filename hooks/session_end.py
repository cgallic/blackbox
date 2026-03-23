#!/usr/bin/env python3
"""Stop hook: build session timeline, calculate score, print scorecard.

Major upgrade: reads compliance events, builds ordered timeline,
calculates score with override/violation penalties, and outputs
the scorecard as a systemMessage.
"""
import json
import os
import hashlib
import tempfile
from datetime import datetime, timezone

# Allow importing _violations from same directory
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _violations import get_violations


def main():
    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
    compliance = os.path.join(proj_dir, ".claude", "sessions", "compliance.jsonl")

    if not os.path.exists(compliance):
        return

    # Read events since last session_start
    events = []
    last_start_idx = -1
    with open(compliance, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            try:
                events.append(json.loads(line.strip()))
                if events[-1].get("type") == "session_start":
                    last_start_idx = len(events) - 1
            except Exception:
                continue

    if last_start_idx < 0:
        return

    # Only count events from this session
    session_events = events[last_start_idx + 1:]

    edits_total = 0
    edits_no_read = 0
    edits_overridden = 0
    commits_total = 0
    commits_no_test = 0
    commits_overridden = 0
    safety_total = 0
    overrides_total = 0
    timeline = []

    for e in session_events:
        t = e.get("type")
        ts_short = e.get("ts", "")[:19]

        if t == "edit_compliance":
            edits_total += 1
            read_first = e.get("was_read_first", False)
            overridden = e.get("was_overridden", False)
            if not read_first:
                edits_no_read += 1
                if overridden:
                    edits_overridden += 1
                    timeline.append(f"  {ts_short}  EDIT {e.get('file', '?')} (override: not read)")
                else:
                    timeline.append(f"  {ts_short}  EDIT {e.get('file', '?')} ** NOT READ **")
            else:
                timeline.append(f"  {ts_short}  EDIT {e.get('file', '?')} (read first)")

        elif t == "commit_compliance":
            commits_total += 1
            tested = e.get("tests_passed_first", e.get("tests_ran_first", False))
            overridden = e.get("was_overridden", False)
            if not tested:
                commits_no_test += 1
                if overridden:
                    commits_overridden += 1
                    timeline.append(f"  {ts_short}  COMMIT (override: no tests)")
                else:
                    timeline.append(f"  {ts_short}  COMMIT ** NO TESTS **")
            else:
                timeline.append(f"  {ts_short}  COMMIT (tests passed)")

        elif t == "safety_trigger":
            safety_total += 1
            severity = e.get("severity", "warning")
            timeline.append(f"  {ts_short}  SAFETY [{severity}] {e.get('pattern', '?')}: {e.get('command', '?')[:60]}")

        elif t == "override_granted":
            overrides_total += 1
            timeline.append(f"  {ts_short}  OVERRIDE {e.get('action', '?')}: {e.get('reason', '?')}")

    # Get violation counts from temp file
    violations = get_violations(h)
    total_violations = sum(violations.values())

    # Calculate score (start at 10, deduct for issues)
    score = 10.0

    # Edits without reading: -1 per violation, -0.5 if overridden
    score -= (edits_no_read - edits_overridden) * 1.0
    score -= edits_overridden * 0.5

    # Commits without tests: -1.5 per violation, -0.75 if overridden
    score -= (commits_no_test - commits_overridden) * 1.5
    score -= commits_overridden * 0.75

    # Safety triggers: -0.5 per occurrence
    score -= safety_total * 0.5

    # Repeated violations penalize more (escalation penalty)
    if total_violations > 5:
        score -= (total_violations - 5) * 0.25

    score = max(0.0, min(10.0, round(score, 1)))

    # Build scorecard text
    edit_pct = round((edits_total - edits_no_read) / edits_total * 100) if edits_total else 100
    commit_pct = round((commits_total - commits_no_test) / commits_total * 100) if commits_total else 100

    bar_len = int(score)
    bar = "#" * bar_len + "." * (10 - bar_len)

    lines = []
    lines.append("+----------------------------------------------------------+")
    lines.append(f"|  AGENT SCORECARD -- {datetime.now().strftime('%Y-%m-%d')}                           |")
    lines.append("+----------------------------------------------------------+")
    lines.append("|                                                          |")
    lines.append(f"|  Score: {score:4.1f} / 10                           {bar}   |")
    lines.append("|                                                          |")

    if edits_total > 0:
        lines.append(f"|  Edits without reading first:  {edits_no_read} / {edits_total:>2}          {edit_pct:>3}%    |")
    if commits_total > 0:
        lines.append(f"|  Commits without tests:        {commits_no_test} / {commits_total:>2}          {commit_pct:>3}%    |")
    if safety_total > 0:
        lines.append(f"|  Destructive commands caught:  {safety_total}                         |")
    if overrides_total > 0:
        lines.append(f"|  Overrides used:               {overrides_total}                         |")

    lines.append("|                                                          |")

    if timeline:
        lines.append("|  Timeline:                                               |")
        for tl in timeline[-8:]:  # Show last 8 events
            entry = tl[:56]
            lines.append(f"|  {entry:<56s}|")

    lines.append("|                                                          |")
    lines.append("+----------------------------------------------------------+")

    scorecard_text = "\n".join(lines)

    # Write session summary to compliance
    summary = {
        "type": "session_summary",
        "ts": datetime.now(timezone.utc).isoformat(),
        "project_hash": h,
        "score": score,
        "edits_total": edits_total,
        "edits_without_read": edits_no_read,
        "edits_overridden": edits_overridden,
        "edit_compliance_pct": round((edits_total - edits_no_read) / edits_total * 100, 1) if edits_total else None,
        "commits_total": commits_total,
        "commits_without_test": commits_no_test,
        "commits_overridden": commits_overridden,
        "commit_compliance_pct": round((commits_total - commits_no_test) / commits_total * 100, 1) if commits_total else None,
        "safety_triggers": safety_total,
        "overrides_used": overrides_total,
        "total_violations": total_violations,
        "timeline_events": len(timeline),
    }

    with open(compliance, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")

    # Output scorecard as systemMessage
    output = {
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "systemMessage": scorecard_text,
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
