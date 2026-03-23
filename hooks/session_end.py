#!/usr/bin/env python3
"""Stop hook: build session summary, print scorecard with meaningful signals."""
import json
import os
import hashlib
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _violations import get_violations


def find_repeated_patterns(all_events, current_guardrails):
    """Check prior session_summary entries for patterns that recur this session.

    Returns list of pattern strings like "edit_blocked" that appeared in a
    previous session AND this session.
    """
    prior_summaries = [e for e in all_events if e.get("type") == "session_summary"]
    if not prior_summaries or not current_guardrails:
        return []

    repeated = []
    # Build set of guardrail types triggered this session
    current_types = set()
    if current_guardrails.get("edit_blocked", 0) > 0:
        current_types.add("edit_blocked")
    if current_guardrails.get("commit_blocked", 0) > 0:
        current_types.add("commit_blocked")
    if current_guardrails.get("destructive_cmd_caught", 0) > 0:
        current_types.add("destructive_cmd_caught")

    for summary in prior_summaries:
        prior_g = summary.get("guardrails_triggered", {})
        if isinstance(prior_g, dict):
            for gtype in current_types:
                if prior_g.get(gtype, 0) > 0 and gtype not in repeated:
                    repeated.append(gtype)
        # Also check old-format summaries for backward compat
        if summary.get("edits_without_read", 0) > 0 and "edit_blocked" in current_types:
            if "edit_blocked" not in repeated:
                repeated.append("edit_blocked")
        if summary.get("commits_without_test", 0) > 0 and "commit_blocked" in current_types:
            if "commit_blocked" not in repeated:
                repeated.append("commit_blocked")
        if summary.get("safety_triggers", 0) > 0 and "destructive_cmd_caught" in current_types:
            if "destructive_cmd_caught" not in repeated:
                repeated.append("destructive_cmd_caught")

    return repeated


def main():
    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
    compliance = os.path.join(proj_dir, ".claude", "sessions", "compliance.jsonl")

    if not os.path.exists(compliance):
        return

    # Read session_id from stdin (Stop hook receives it)
    current_sid = ""
    try:
        data = json.load(sys.stdin)
        current_sid = data.get("session_id", "")
    except Exception:
        pass

    # Fallback: read from temp file
    if not current_sid:
        sid_file = os.path.join(__import__('tempfile').gettempdir(), f"claude-session-{h}.txt")
        try:
            with open(sid_file, "r") as f:
                current_sid = f.read().strip()
        except Exception:
            pass

    # Read all events
    all_events = []
    with open(compliance, "r", encoding="utf-8") as f:
        for line in f:
            try:
                all_events.append(json.loads(line.strip()))
            except Exception:
                continue

    if current_sid:
        session_events = [e for e in all_events
                          if e.get("session_id") == current_sid
                          and e.get("type") != "session_start"]
        if not session_events:
            current_sid = ""

    if not current_sid:
        # Fallback: find last UNCLOSED session_start
        last_start_idx = -1
        for i in range(len(all_events) - 1, -1, -1):
            if all_events[i].get("type") == "session_start":
                has_summary = any(
                    all_events[j].get("type") == "session_summary"
                    for j in range(i + 1, len(all_events))
                )
                if not has_summary:
                    last_start_idx = i
                    break
        if last_start_idx < 0:
            for i in range(len(all_events) - 1, -1, -1):
                if all_events[i].get("type") == "session_start":
                    last_start_idx = i
                    break
        if last_start_idx < 0:
            return
        session_events = [e for e in all_events[last_start_idx + 1:]
                          if e.get("type") not in ("session_summary", "session_start")]

    # --- COUNT SESSION SIGNALS ---
    edits_total = 0
    edits_no_read = 0
    commits_total = 0
    commits_no_test = 0
    safety_total = 0

    for e in session_events:
        t = e.get("type")

        if t == "edit_compliance":
            edits_total += 1
            if not e.get("was_read_first", False):
                edits_no_read += 1

        elif t == "commit_compliance":
            commits_total += 1
            tested = e.get("tests_passed_first", e.get("tests_ran_first", False))
            if not tested:
                commits_no_test += 1

        elif t == "safety_trigger":
            safety_total += 1

    # Build guardrails dict
    guardrails = {
        "edit_blocked": edits_no_read,
        "commit_blocked": commits_no_test,
        "destructive_cmd_caught": safety_total,
    }
    guardrails_total = edits_no_read + commits_no_test + safety_total

    # Find repeated patterns from prior sessions
    repeated_patterns = find_repeated_patterns(all_events, guardrails)

    # --- SCORING ---
    # Simple formula: start at 10, deduct for guardrail triggers and repeats
    score = 10.0
    # Each guardrail trigger: -0.5
    score -= guardrails_total * 0.5
    # Repeated pattern from previous session: -1.5 per pattern
    score -= len(repeated_patterns) * 1.5
    score = max(0.0, round(score, 1))

    # --- SCORECARD ---
    lines = []
    lines.append("+----------------------------------------------------------+")
    lines.append(f"|  SESSION SUMMARY -- {datetime.now().strftime('%Y-%m-%d'):<38s}|")
    lines.append("+----------------------------------------------------------+")
    lines.append("|                                                          |")
    lines.append("|  Guardrails triggered:                                   |")
    lines.append(f"|    Edit blocked (no read):   {edits_no_read:>2}                          |")
    lines.append(f"|    Commit blocked (no test): {commits_no_test:>2}                          |")
    lines.append(f"|    Destructive cmd caught:   {safety_total:>2}                          |")
    lines.append("|                                                          |")
    lines.append(f"|  Session totals:                                         |")
    lines.append(f"|    Files edited: {edits_total:>3}                                        |")
    lines.append(f"|    Commits:      {commits_total:>3}                                        |")

    if repeated_patterns:
        lines.append("|                                                          |")
        lines.append("|  Repeated from prior sessions:                           |")
        for pat in repeated_patterns:
            label = pat.replace("_", " ")
            lines.append(f"|    - {label:<53s}|")

    lines.append("|                                                          |")
    lines.append("|  Run /blackbox-scorecard for full scoring + corrections.      |")
    lines.append("|  Run /blackbox-retro weekly to mine patterns and update rules.    |")
    lines.append("|                                                          |")
    lines.append("+----------------------------------------------------------+")

    scorecard_text = "\n".join(lines)

    # --- WRITE SUMMARY ---
    summary = {
        "type": "session_summary",
        "ts": datetime.now(timezone.utc).isoformat(),
        "project_hash": h,
        "score": score,
        "edits_total": edits_total,
        "edits_without_read": edits_no_read,
        "commits_total": commits_total,
        "commits_without_test": commits_no_test,
        "safety_triggers": safety_total,
        "guardrails_triggered": guardrails,
        "repeated_patterns": repeated_patterns,
    }

    with open(compliance, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")

    output = {"systemMessage": scorecard_text}
    print(json.dumps(output))


if __name__ == "__main__":
    main()
