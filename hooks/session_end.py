#!/usr/bin/env python3
"""Stop hook: build session timeline, calculate score, print scorecard."""
import json
import os
import re
import hashlib
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _violations import get_violations

# Files that don't need tests — config, docs, assets, settings
NON_TESTABLE = re.compile(
    r'\.(md|json|ya?ml|toml|ini|txt|css|scss|less|svg|png|jpg|gif|ico|lock|env|sh|bash)$'
    r'|\.gitignore$|settings\.local|CLAUDE\.md|README|LICENSE|CHANGELOG|setup$',
    re.I,
)


def is_config_only_commit(staged_files):
    """Return True if ALL staged files are non-testable (config/docs/assets)."""
    if not staged_files:
        return False  # Unknown = assume testable, enforce the rule
    return all(NON_TESTABLE.search(f) for f in staged_files)


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

    # Read all events, filter to THIS session only
    all_events = []
    with open(compliance, "r", encoding="utf-8") as f:
        for line in f:
            try:
                all_events.append(json.loads(line.strip()))
            except Exception:
                continue

    if current_sid:
        # Filter to events matching this session_id
        session_events = [e for e in all_events
                          if e.get("session_id") == current_sid
                          and e.get("type") != "session_start"]
        # If no matching events, fall back (session started before fix)
        if not session_events:
            current_sid = ""

    if not current_sid:
        # Fallback: find last UNCLOSED session_start
        # Walk backward — skip session_starts that already have a summary after them
        last_start_idx = -1
        for i in range(len(all_events) - 1, -1, -1):
            if all_events[i].get("type") == "session_start":
                # Check if there's a session_summary after this start
                has_summary = any(
                    all_events[j].get("type") == "session_summary"
                    for j in range(i + 1, len(all_events))
                )
                if not has_summary:
                    last_start_idx = i
                    break
        if last_start_idx < 0:
            # All sessions are closed — use the very last start
            for i in range(len(all_events) - 1, -1, -1):
                if all_events[i].get("type") == "session_start":
                    last_start_idx = i
                    break
        if last_start_idx < 0:
            return
        session_events = [e for e in all_events[last_start_idx + 1:]
                          if e.get("type") not in ("session_summary", "session_start")]

    edits_total = 0
    edits_no_read = 0
    edits_overridden = 0
    commits_total = 0
    commits_no_test = 0        # testable code committed without tests
    commits_config_only = 0    # config-only commits (not penalized)
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
            fname = os.path.basename(e.get("file", "?"))
            if not read_first:
                edits_no_read += 1
                if overridden:
                    edits_overridden += 1
                    timeline.append(f"  EDIT {fname} (override)")
                else:
                    timeline.append(f"  EDIT {fname} ** NO READ **")
            else:
                timeline.append(f"  EDIT {fname}")

        elif t == "commit_compliance":
            commits_total += 1
            tested = e.get("tests_passed_first", e.get("tests_ran_first", False))
            overridden = e.get("was_overridden", False)
            missing_tests = e.get("tests_missing", [])
            covered_tests = e.get("tests_covered", [])
            staged = e.get("staged_files", [])

            config_only = is_config_only_commit(staged)

            if config_only:
                commits_config_only += 1
                timeline.append(f"  COMMIT (config only, no tests needed)")
            elif not tested and not missing_tests:
                # No tests ran but also no specific missing tests identified
                # Could be a project without a test suite — mild penalty only
                if overridden:
                    commits_overridden += 1
                    timeline.append(f"  COMMIT (override: no tests)")
                else:
                    commits_no_test += 1
                    timeline.append(f"  COMMIT ** NO TESTS **")
            elif missing_tests:
                if overridden:
                    commits_overridden += 1
                    timeline.append(f"  COMMIT (override: untested files)")
                else:
                    commits_no_test += 1
                    for src in missing_tests[:2]:
                        timeline.append(f"  COMMIT ** UNTESTED: {src} **")
            else:
                cov = f", {len(covered_tests)} covered" if covered_tests else ""
                timeline.append(f"  COMMIT (tests passed{cov})")

        elif t == "safety_trigger":
            safety_total += 1
            timeline.append(f"  SAFETY {e.get('pattern', '?')}")

        elif t == "override_granted":
            overrides_total += 1
            timeline.append(f"  OVERRIDE {e.get('action', '?')}")

    violations = get_violations(h)
    total_violations = sum(violations.values())

    # --- SCORING ---
    # Ratio-based, not raw count. 1 miss in 20 edits != 1 miss in 2 edits.
    score = 10.0

    # Edit compliance: penalize by miss RATE
    if edits_total > 0:
        miss_rate = (edits_no_read - edits_overridden) / edits_total
        score -= miss_rate * 4.0  # 100% miss rate = -4, 50% = -2, 10% = -0.4
        score -= edits_overridden / edits_total * 1.0  # overrides = mild penalty

    # Commit compliance: only penalize testable commits
    testable_commits = commits_total - commits_config_only
    if testable_commits > 0:
        bad_commits = commits_no_test - commits_overridden
        miss_rate = bad_commits / testable_commits
        score -= miss_rate * 4.0
        score -= commits_overridden / testable_commits * 1.0

    # Safety: -0.5 each
    score -= safety_total * 0.5

    # Escalation: repeated violations compound
    if total_violations > 3:
        score -= (total_violations - 3) * 0.25

    score = max(0.0, min(10.0, round(score, 1)))

    # --- SCORECARD ---
    edit_pct = round((edits_total - edits_no_read) / edits_total * 100) if edits_total else 100
    testable = commits_total - commits_config_only
    commit_pct = round((testable - commits_no_test) / testable * 100) if testable > 0 else 100

    bar_len = int(score)
    bar = "#" * bar_len + "." * (10 - bar_len)

    lines = []
    lines.append("+----------------------------------------------------------+")
    lines.append(f"|  AGENT SCORECARD -- {datetime.now().strftime('%Y-%m-%d')}                           |")
    lines.append("+----------------------------------------------------------+")
    lines.append(f"|  Score: {score:4.1f} / 10                           {bar}   |")
    lines.append("|                                                          |")

    if edits_total > 0:
        mark = "x" if edits_no_read > 0 else "+"
        lines.append(f"|  {mark} Edits read first:     {edits_total - edits_no_read:>2} / {edits_total:>2}          {edit_pct:>3}%    |")

    if testable > 0:
        mark = "x" if commits_no_test > 0 else "+"
        lines.append(f"|  {mark} Commits with tests:   {testable - commits_no_test:>2} / {testable:>2}          {commit_pct:>3}%    |")

    if commits_config_only > 0:
        lines.append(f"|    ({commits_config_only} config-only commit(s) -- no tests needed)    |")

    if safety_total > 0:
        lines.append(f"|  x Destructive cmds:    {safety_total}                               |")
    if overrides_total > 0:
        lines.append(f"|    Overrides used:      {overrides_total}                               |")

    if timeline:
        lines.append("|                                                          |")
        for tl in timeline[-10:]:
            entry = tl[:56]
            lines.append(f"|  {entry:<56s}|")

    lines.append("+----------------------------------------------------------+")

    scorecard_text = "\n".join(lines)

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
        "commits_config_only": commits_config_only,
        "commits_without_test": commits_no_test,
        "commits_overridden": commits_overridden,
        "commit_compliance_pct": round((testable - commits_no_test) / testable * 100, 1) if testable else None,
        "safety_triggers": safety_total,
        "overrides_used": overrides_total,
        "total_violations": total_violations,
    }

    with open(compliance, "a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")

    output = {"systemMessage": scorecard_text}
    print(json.dumps(output))


if __name__ == "__main__":
    main()
