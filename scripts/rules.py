#!/usr/bin/env python3
"""
Rules CLI — inspect and manage the learned rules store.

Usage:
    python scripts/rules.py                       # List non-archived rules
    python scripts/rules.py list --all            # Include archived rules
    python scripts/rules.py archive <id>          # Archive a rule
    python scripts/rules.py promote <id> <status> # Set status (watch|important|critical)
    python scripts/rules.py add "<text>" [--key <id>] [--hits <N>]  # Add a manual rule

Project dir comes from CLAUDE_PROJECT_DIR or the current directory.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks"))
import _rules  # noqa: E402

# Display order: critical first, archived last.
LIST_RANK = {"critical": 0, "important": 1, "watch": 2, "candidate": 3, "archived": 4}
PROMOTE_STATUSES = ("watch", "important", "critical")


def get_proj_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())


def now_ts():
    return datetime.now(timezone.utc).isoformat()


def cmd_list(proj_dir, show_all=False):
    data = _rules.load_rules(proj_dir)
    rules = data["rules"]
    archived_count = sum(1 for r in rules if r.get("status") == "archived")
    if not show_all:
        rules = [r for r in rules if r.get("status") != "archived"]
    rules = sorted(rules, key=lambda r: (LIST_RANK.get(r.get("status"), 5), -r.get("hits", 0)))

    if not rules:
        print("No rules learned yet.")
    else:
        id_width = max([len(r.get("id", "")) for r in rules] + [len("ID")])
        header = "{:<10} {:>4} {:>5}  {:<{idw}}  {}".format(
            "STATUS", "HITS", "CLEAN", "ID", "TEXT", idw=id_width)
        print(header)
        print("-" * len(header))
        for r in rules:
            print("{:<10} {:>4} {:>5}  {:<{idw}}  {}".format(
                r.get("status", ""), r.get("hits", 0), r.get("sessions_since_hit", 0),
                r.get("id", ""), r.get("text", ""), idw=id_width))

    if show_all:
        print("\n{} archived rule(s) shown above.".format(archived_count))
    else:
        print("\n{} archived rule(s) hidden. Use 'list --all' to show.".format(archived_count))


def cmd_archive(proj_dir, rule_id):
    data = _rules.load_rules(proj_dir)
    for r in data["rules"]:
        if r.get("id") == rule_id:
            r["status"] = "archived"
            _rules.save_rules(proj_dir, data)
            print("Archived rule: {}".format(rule_id))
            return
    print("Unknown rule id: {}".format(rule_id))
    sys.exit(1)


def cmd_promote(proj_dir, rule_id, status):
    if status not in PROMOTE_STATUSES:
        print("Invalid status: {} (expected one of: {})".format(
            status, ", ".join(PROMOTE_STATUSES)))
        sys.exit(1)
    data = _rules.load_rules(proj_dir)
    for r in data["rules"]:
        if r.get("id") == rule_id:
            r["status"] = status
            _rules.save_rules(proj_dir, data)
            print("Set rule {} to {}".format(rule_id, status))
            return
    print("Unknown rule id: {}".format(rule_id))
    sys.exit(1)


def cmd_add(proj_dir, text, key=None, hits=0):
    data = _rules.load_rules(proj_dir)
    existing = set(r.get("id") for r in data["rules"])
    if key is None:
        n = 1
        while "manual_{}".format(n) in existing:
            n += 1
        key = "manual_{}".format(n)
    elif key in existing:
        print("Rule id already exists: {}".format(key))
        sys.exit(1)
    # Manual adds start at least at watch; known hit counts can place higher.
    status = _rules.status_for_hits(hits)
    if _rules.STATUS_RANK.get(status, 0) < _rules.STATUS_RANK["watch"]:
        status = "watch"
    ts = now_ts()
    data["rules"].append({
        "id": key,
        "text": text,
        "status": status,
        "hits": hits,
        "sessions_since_hit": 0,
        "last_hit_ts": ts if hits else "",
        "created_ts": ts,
        "source": "manual",
    })
    _rules.save_rules(proj_dir, data)
    print("Added rule {} ({}): {}".format(key, status, text))


def main():
    proj_dir = get_proj_dir()
    args = sys.argv[1:]
    cmd = args[0] if args else "list"

    if cmd == "list":
        cmd_list(proj_dir, show_all="--all" in args[1:])
    elif cmd == "archive":
        if len(args) < 2:
            print("Usage: rules.py archive <id>")
            sys.exit(1)
        cmd_archive(proj_dir, args[1])
    elif cmd == "promote":
        if len(args) < 3:
            print("Usage: rules.py promote <id> <status>")
            sys.exit(1)
        cmd_promote(proj_dir, args[1], args[2])
    elif cmd == "add":
        if len(args) < 2:
            print("Usage: rules.py add \"<text>\" [--key <id>]")
            sys.exit(1)
        key = None
        hits = 0
        if "--key" in args:
            i = args.index("--key")
            if i + 1 >= len(args):
                print("--key requires a value")
                sys.exit(1)
            key = args[i + 1]
        if "--hits" in args:
            i = args.index("--hits")
            if i + 1 >= len(args) or not args[i + 1].isdigit():
                print("--hits requires a number")
                sys.exit(1)
            hits = int(args[i + 1])
        cmd_add(proj_dir, args[1], key, hits)
    else:
        print("Unknown command: {}".format(cmd))
        print("Commands: list [--all], archive <id>, promote <id> <status>, add \"<text>\" [--key <id>]")
        sys.exit(1)


if __name__ == "__main__":
    main()
