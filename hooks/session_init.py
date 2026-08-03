#!/usr/bin/env python3
"""SessionStart hook: reset tracking files, tag session ID."""
import os
import sys
import json
import hashlib
import tempfile
from datetime import datetime, timezone


def main():
    # Read session_id from stdin
    session_id = ""
    try:
        data = json.load(sys.stdin)
        session_id = data.get("session_id", "")
    except Exception:
        pass

    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
    tmp = tempfile.gettempdir()

    # Store session_id so other hooks can read it
    sid_file = os.path.join(tmp, f"claude-session-{h}.txt")
    with open(sid_file, "w") as f:
        f.write(session_id)

    # Clear stale tracking files
    for name in [
        f"claude-reads-{h}.txt",
        f"claude-tested-{h}.txt",
        f"claude-tested-files-{h}.txt",
        f"claude-violations-{h}.json",
        f"claude-override-{h}.json",
    ]:
        path = os.path.join(tmp, name)
        if os.path.exists(path):
            os.remove(path)

    # Log session start
    sessions_dir = os.path.join(proj_dir, ".claude", "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    compliance = os.path.join(sessions_dir, "compliance.jsonl")

    entry = {
        "type": "session_start",
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "project_hash": h,
    }
    with open(compliance, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    # --- Learning loop: inject learned rules + last-session recap ---
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _rules import active_rules, format_rules_context

        rules = active_rules(proj_dir)

        # Most recent session_summary event, if any
        last_summary = None
        if os.path.exists(compliance):
            with open(compliance, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        e = json.loads(line.strip())
                    except Exception:
                        continue
                    if e.get("type") == "session_summary":
                        last_summary = e

        guardrail_total = 0
        breakdown_parts = []
        corrections = 0
        if last_summary:
            g = last_summary.get("guardrails_triggered", {})
            if isinstance(g, dict):
                for key, noun in [
                    ("edit_blocked", "edit block"),
                    ("commit_blocked", "untested commit"),
                    ("destructive_cmd_caught", "destructive cmd"),
                ]:
                    n = g.get(key, 0)
                    if isinstance(n, (int, float)) and n > 0:
                        n = int(n)
                        guardrail_total += n
                        breakdown_parts.append(
                            "{} {}{}".format(n, noun, "s" if n != 1 else ""))
            c = last_summary.get("user_corrections", 0)
            if isinstance(c, (int, float)):
                corrections = int(c)

        if rules or guardrail_total > 0 or corrections > 0:
            text = "## Blackbox: learned rules from past sessions\n"
            text += format_rules_context(rules)
            if guardrail_total > 0 or corrections > 0:
                line = "\nLast session: {} guardrail trigger(s)".format(guardrail_total)
                if breakdown_parts:
                    line += " ({})".format(", ".join(breakdown_parts))
                line += ", {} user correction(s). Do not repeat these.".format(corrections)
                text += line
            text = text[:1200]
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": text,
            }}))
    except Exception:
        pass


if __name__ == "__main__":
    main()
