#!/usr/bin/env python3
"""Stop hook: aggregate compliance events into a session summary."""
import json
import os
import hashlib
from datetime import datetime, timezone

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
    commits_total = 0
    commits_no_test = 0
    safety_total = 0

    for e in session_events:
        t = e.get("type")
        if t == "edit_compliance":
            edits_total += 1
            if not e.get("was_read_first"):
                edits_no_read += 1
        elif t == "commit_compliance":
            commits_total += 1
            if not e.get("tests_ran_first"):
                commits_no_test += 1
        elif t == "safety_trigger":
            safety_total += 1

    summary = {
        "type": "session_summary",
        "ts": datetime.now(timezone.utc).isoformat(),
        "project_hash": h,
        "edits_total": edits_total,
        "edits_without_read": edits_no_read,
        "edit_compliance_pct": round((edits_total - edits_no_read) / edits_total * 100, 1) if edits_total else None,
        "commits_total": commits_total,
        "commits_without_test": commits_no_test,
        "commit_compliance_pct": round((commits_total - commits_no_test) / commits_total * 100, 1) if commits_total else None,
        "safety_triggers": safety_total,
    }

    with open(compliance, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")

if __name__ == "__main__":
    main()
