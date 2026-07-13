#!/usr/bin/env python3
"""Persistent rules store for the retro loop.

NOT a standalone hook — imported by hooks and scripts/rules.py.
Reads/writes <proj_dir>/.claude/sessions/rules.json:

    {"version": 1, "rules": [
        {"id": str, "text": str,
         "status": "candidate"|"watch"|"important"|"critical"|"archived",
         "hits": int, "sessions_since_hit": int,
         "last_hit_ts": str, "created_ts": str,
         "source": "auto"|"retro"|"manual"}
    ]}
"""
import json
import os

# Default rule text per known pattern key.
RULE_TEXTS = {
    "edit_without_read": "Never edit or overwrite a file without reading it first.",
    "commit_without_test": "Never commit without running the relevant tests after the last edit.",
    "destructive_cmd": "Never run destructive commands (rm -rf, force push, hard reset) without explicit user approval.",
    "breakage": "When the user reports breakage, revert first, then diagnose.",
    "context_ignored": "Check earlier instructions in the conversation before acting; do not re-ask for information already given.",
    "overengineering": "Prefer the simplest implementation that satisfies the request; add nothing that was not asked for.",
    "wrong_direction": "When a request is ambiguous, confirm the intended approach before making large changes.",
    "approach_change": "When the user changes direction, drop the old plan entirely instead of blending both.",
}

# Escalation order for non-archived statuses (higher = more severe).
STATUS_RANK = {"candidate": 0, "watch": 1, "important": 2, "critical": 3}

# Archive thresholds: sessions without a hit before a rule is retired.
ARCHIVE_AFTER = {"candidate": 10, "watch": 10, "important": 20, "critical": 20}


def _rules_path(proj_dir):
    return os.path.join(proj_dir, ".claude", "sessions", "rules.json")


def _empty_store():
    return {"version": 1, "rules": []}


def load_rules(proj_dir):
    """Load the rules store. Missing/corrupt file returns an empty store."""
    path = _rules_path(proj_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _empty_store()
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        return _empty_store()
    return data


def save_rules(proj_dir, data):
    """Write the rules store. Best-effort atomic: temp file + os.replace."""
    path = _rules_path(proj_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def status_for_hits(hits):
    """Derive status from hit count: <2 candidate, >=2 watch, >=4 important, >=8 critical."""
    if hits >= 8:
        return "critical"
    if hits >= 4:
        return "important"
    if hits >= 2:
        return "watch"
    return "candidate"


def _find_rule(data, rule_key):
    for rule in data["rules"]:
        if rule.get("id") == rule_key:
            return rule
    return None


def record_hit(proj_dir, rule_key, ts, count=1, text=None):
    """Record hit(s) on a rule, creating it if absent. Returns the updated rule.

    Status is derived from hits but never demotes an existing higher status.
    A hit on an archived rule revives it at the status its hits imply.
    """
    data = load_rules(proj_dir)
    rule = _find_rule(data, rule_key)
    if rule is None:
        rule = {
            "id": rule_key,
            "text": text or RULE_TEXTS.get(rule_key, "Avoid repeating pattern: {}.".format(rule_key)),
            "status": "candidate",
            "hits": 0,
            "sessions_since_hit": 0,
            "last_hit_ts": "",
            "created_ts": ts,
            "source": "auto",
        }
        data["rules"].append(rule)

    rule["hits"] = rule.get("hits", 0) + count
    rule["last_hit_ts"] = ts
    rule["sessions_since_hit"] = 0

    derived = status_for_hits(rule["hits"])
    current = rule.get("status", "candidate")
    if current == "archived":
        rule["status"] = derived
    elif STATUS_RANK.get(derived, 0) > STATUS_RANK.get(current, 0):
        rule["status"] = derived

    save_rules(proj_dir, data)
    return rule


def record_clean_sessions(proj_dir, hit_keys):
    """Bump sessions_since_hit on every non-archived rule not in hit_keys.

    Archives candidate/watch rules at 10 clean sessions, important/critical
    at 20. Returns the list of newly archived rule ids.
    """
    data = load_rules(proj_dir)
    hit_keys = set(hit_keys)
    archived = []
    for rule in data["rules"]:
        status = rule.get("status", "candidate")
        if status == "archived" or rule.get("id") in hit_keys:
            continue
        rule["sessions_since_hit"] = rule.get("sessions_since_hit", 0) + 1
        if rule["sessions_since_hit"] >= ARCHIVE_AFTER.get(status, 10):
            rule["status"] = "archived"
            archived.append(rule["id"])
    save_rules(proj_dir, data)
    return archived


def active_rules(proj_dir):
    """Rules with status watch/important/critical, critical first, ties by hits desc."""
    data = load_rules(proj_dir)
    rules = [r for r in data["rules"]
             if r.get("status") in ("watch", "important", "critical")]
    rules.sort(key=lambda r: (-STATUS_RANK.get(r.get("status"), 0), -r.get("hits", 0)))
    return rules


def format_rules_context(rules, max_rules=8):
    """Format rules as markdown bullets: '- [CRITICAL] Rule text. (7x)'."""
    lines = []
    for rule in rules[:max_rules]:
        lines.append("- [{}] {} ({}x)".format(
            rule.get("status", "").upper(), rule.get("text", ""), rule.get("hits", 0)))
    return "\n".join(lines)
