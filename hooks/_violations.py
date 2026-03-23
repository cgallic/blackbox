#!/usr/bin/env python3
"""Shared violation tracking for retro-loop hooks.

NOT a standalone hook — imported by check_edit.py, check_commit.py, track_safety.py.
Reads/writes violation counts and override state from temp files.
"""
import json
import os
import hashlib
import tempfile
from datetime import datetime, timezone


def get_project_hash(proj_dir=None):
    """Return first 8 chars of md5 hash of project directory."""
    if proj_dir is None:
        proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    return hashlib.md5(proj_dir.encode()).hexdigest()[:8]


def _violations_path(project_hash):
    return os.path.join(tempfile.gettempdir(), f"claude-violations-{project_hash}.json")


def get_violations(project_hash):
    """Read violation counts from temp file.

    Returns dict like {"edit_without_read": 3, "commit_without_test": 1}
    """
    path = _violations_path(project_hash)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def increment_violation(project_hash, violation_type):
    """Increment a violation counter and return new count."""
    violations = get_violations(project_hash)
    violations[violation_type] = violations.get(violation_type, 0) + 1
    path = _violations_path(project_hash)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(violations, f)
    return violations[violation_type]


def _override_path(project_hash):
    return os.path.join(tempfile.gettempdir(), f"claude-override-{project_hash}.json")


def get_override(project_hash, action):
    """Check override file for a given action.

    Returns the reason string if an override exists with uses>0, else None.
    Decrements uses on consumption.
    """
    path = _override_path(project_hash)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None

    if data.get("action") != action:
        return None
    if data.get("uses", 0) <= 0:
        return None

    reason = data.get("reason", "no reason given")
    data["uses"] = data["uses"] - 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return reason


def log_compliance(proj_dir, entry):
    """Append a compliance entry to .claude/sessions/compliance.jsonl."""
    sessions_dir = os.path.join(proj_dir, ".claude", "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    compliance = os.path.join(sessions_dir, "compliance.jsonl")
    with open(compliance, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
