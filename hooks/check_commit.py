#!/usr/bin/env python3
"""PreToolUse hook for Bash: BLOCK git commits with diff-aware test enforcement.

1. Runs git diff --cached --name-only to get changed files
2. Maps changed files to expected test files
3. Checks if relevant tests ran AND passed
4. Blocks with specific message showing what's missing
"""
import sys
import json
import os
import re
import subprocess
import hashlib
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _violations import get_override, increment_violation, log_compliance


# Maps source file patterns to test file patterns
# Given "src/auth.ts", looks for "auth.test.ts", "auth.spec.ts", "test_auth.py", etc.
def find_expected_tests(changed_files):
    """Map changed source files to expected test files.

    Returns dict: {source_file: [expected_test_patterns]}
    Only includes files that SHOULD have tests (skips configs, assets, etc).
    """
    skip_patterns = [
        r'\.md$', r'\.json$', r'\.ya?ml$', r'\.toml$', r'\.ini$',
        r'\.css$', r'\.scss$', r'\.less$', r'\.svg$', r'\.png$', r'\.jpg$',
        r'\.lock$', r'\.gitignore$', r'\.env',
        r'__pycache__', r'node_modules',
        r'\.test\.', r'\.spec\.', r'test_', r'_test\.',  # already a test file
    ]
    expected = {}
    for f in changed_files:
        if any(re.search(p, f, re.I) for p in skip_patterns):
            continue
        basename = os.path.basename(f)
        name, ext = os.path.splitext(basename)
        # Generate expected test file patterns
        patterns = []
        if ext in ('.ts', '.tsx', '.js', '.jsx'):
            patterns.append(f"{name}.test{ext}")
            patterns.append(f"{name}.spec{ext}")
        elif ext == '.py':
            patterns.append(f"test_{name}.py")
            patterns.append(f"{name}_test.py")
        elif ext == '.go':
            patterns.append(f"{name}_test.go")
        elif ext == '.rs':
            patterns.append(f"{name}_test.rs")
        if patterns:
            expected[f] = patterns
    return expected


def get_staged_files(proj_dir):
    """Get list of files staged for commit."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, timeout=5,
            cwd=proj_dir,
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]
    except Exception:
        pass

    # Fallback: try unstaged diff
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=proj_dir,
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]
    except Exception:
        pass
    return []


def get_tested_files(project_hash):
    """Read list of test files that ran this session."""
    path = os.path.join(tempfile.gettempdir(), f"claude-tested-files-{project_hash}.txt")
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except Exception:
        return set()


def check_test_coverage(expected_tests, tested_files):
    """Check which expected tests were actually run.

    Returns (covered, missing) where each is a list of (source, test_pattern) tuples.
    """
    covered = []
    missing = []
    tested_basenames = {os.path.basename(f) for f in tested_files}

    for source, patterns in expected_tests.items():
        found = False
        for pattern in patterns:
            if pattern in tested_basenames:
                covered.append((source, pattern))
                found = True
                break
        if not found:
            missing.append((source, patterns))
    return covered, missing


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd or not re.search(r'\bgit\s+commit\b', cmd):
        return

    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
    tested_file = os.path.join(tempfile.gettempdir(), f"claude-tested-{h}.txt")

    # Check basic test pass
    tests_passed = False
    if os.path.exists(tested_file):
        try:
            with open(tested_file, "r") as f:
                tests_passed = f.read().strip() == "passed"
        except Exception:
            pass

    # Diff-aware: check which changed files have test coverage
    staged_files = get_staged_files(proj_dir)
    expected_tests = find_expected_tests(staged_files)
    tested_files = get_tested_files(h)
    covered, missing = check_test_coverage(expected_tests, tested_files)

    was_overridden = False
    if not tests_passed or missing:
        override_reason = get_override(h, "commit")
        if override_reason:
            was_overridden = True

    # Log to compliance
    log_compliance(proj_dir, {
        "type": "commit_compliance",
        "ts": datetime.now(timezone.utc).isoformat(),
        "command": cmd[:200],
        "tests_passed_first": tests_passed,
        "was_overridden": was_overridden,
        "staged_files": staged_files[:20],
        "tests_covered": [s for s, _ in covered],
        "tests_missing": [s for s, _ in missing],
    })

    # Build block reason
    if not tests_passed and not was_overridden:
        count = increment_violation(h, "commit_without_test")
        reason = "BLOCKED: Cannot commit without passing tests first."
        if staged_files:
            reason += f"\n\nChanged files ({len(staged_files)}):"
            for f in staged_files[:10]:
                reason += f"\n  - {f}"
        reason += f"\n\n(violation #{count})"

        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
        return

    if missing and not was_overridden:
        count = increment_violation(h, "commit_missing_tests")

        reason = "BLOCKED: Changed files have no matching test coverage.\n"
        reason += "\nUntested changes:"
        for source, patterns in missing[:5]:
            reason += f"\n  x {source}"
            reason += f"\n    expected: {' or '.join(patterns)}"
        if covered:
            reason += f"\n\nCovered ({len(covered)}):"
            for source, test in covered[:5]:
                reason += f"\n  + {source} -> {test}"
        reason += f"\n\nRun the relevant tests, or: blackbox override commit --reason \"...\""
        reason += f"\n(violation #{count})"

        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
        return


if __name__ == "__main__":
    main()
