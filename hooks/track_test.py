#!/usr/bin/env python3
"""PostToolUse hook for Bash: detect test commands, verify they PASSED, track which files were tested.

Writes two things:
1. "passed" marker to temp file (for check_commit.py)
2. List of test files that ran to temp file (for diff-aware enforcement)
"""
import sys
import json
import os
import re
import hashlib
import tempfile

TEST_PATTERNS = [
    r'\bnpm\s+test\b',
    r'\bnpx\s+jest\b',
    r'\bnpx\s+vitest\b',
    r'\bbun\s+test\b',
    r'\bpytest\b',
    r'\bpython\s+.*test',
    r'\bcargo\s+test\b',
    r'\bgo\s+test\b',
    r'\bmake\s+test\b',
    r'\byarn\s+test\b',
    r'\bpnpm\s+test\b',
]

FAILURE_INDICATORS = [
    r'FAILED',
    r'FAIL[^A-Z]',
    r'Error:',
    r'error:',
    r'Exit code [1-9]',
    r'exit code [1-9]',
    r'Traceback \(most recent',
    r'[1-9]\d* failed',
    r'FAILURES',
    r'AssertionError',
    r'AssertError',
]

# Patterns to extract test file names from test output
TEST_FILE_PATTERNS = [
    r'PASS\s+(\S+\.(?:test|spec)\.\S+)',       # jest: PASS src/auth.test.ts
    r'FAIL\s+(\S+\.(?:test|spec)\.\S+)',       # jest: FAIL src/auth.test.ts
    r'(\S+\.(?:test|spec)\.\S+)\s+\(\d',      # vitest: auth.test.ts (0.5s)
    r'(\S+test\S*\.py)\b',                      # pytest: test_auth.py or auth_test.py
    r'(\S+_test\.go)\b',                        # go: auth_test.go
    r'(\S+\.test\.\S+)',                        # generic: *.test.*
    r'(\S+\.spec\.\S+)',                        # generic: *.spec.*
]


def extract_test_files(output):
    """Extract test file paths from test runner output."""
    files = set()
    for pattern in TEST_FILE_PATTERNS:
        for match in re.finditer(pattern, output):
            files.add(match.group(1))
    return files


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd:
        return

    is_test_cmd = any(re.search(p, cmd, re.I) for p in TEST_PATTERNS)
    if not is_test_cmd:
        return

    response = data.get("tool_response", "")
    if isinstance(response, dict):
        response = json.dumps(response)
    response = str(response)

    tests_passed = not any(re.search(p, response) for p in FAILURE_INDICATORS)

    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
    tmp = tempfile.gettempdir()

    if tests_passed:
        with open(os.path.join(tmp, f"claude-tested-{h}.txt"), "w") as f:
            f.write("passed")

    # Track which test files ran (regardless of pass/fail)
    test_files = extract_test_files(response)

    # Also extract from the command itself (e.g. "npx jest auth.test.ts")
    test_files |= extract_test_files(cmd)

    if test_files:
        tested_files_path = os.path.join(tmp, f"claude-tested-files-{h}.txt")
        with open(tested_files_path, "a", encoding="utf-8") as f:
            for tf in test_files:
                f.write(tf + "\n")


if __name__ == "__main__":
    main()
