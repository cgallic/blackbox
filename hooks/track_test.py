#!/usr/bin/env python3
"""PostToolUse hook for Bash: detect test commands and verify they PASSED.

Only writes the "tested" marker if the test command actually passed
(exit code 0 and no error indicators in response).
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

# Indicators that tests failed (checked against tool_response)
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


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd:
        return

    is_test_cmd = False
    for pattern in TEST_PATTERNS:
        if re.search(pattern, cmd, re.I):
            is_test_cmd = True
            break

    if not is_test_cmd:
        return

    # Check if tests actually passed by examining tool_response
    response = data.get("tool_response", "")
    if isinstance(response, dict):
        response = json.dumps(response)

    tests_passed = True

    # Check for failure indicators in response
    for pattern in FAILURE_INDICATORS:
        if re.search(pattern, str(response)):
            tests_passed = False
            break

    # Only mark as tested if tests passed
    if tests_passed:
        proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
        tested_file = os.path.join(tempfile.gettempdir(), f"claude-tested-{h}.txt")
        with open(tested_file, "w") as f:
            f.write("passed")


if __name__ == "__main__":
    main()
