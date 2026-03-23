#!/usr/bin/env python3
"""PostToolUse hook for Bash: detect test commands and mark tests as run."""
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
    r'\bpython\s+-m\s+pytest\b',
    r'\bcargo\s+test\b',
    r'\bgo\s+test\b',
    r'\bmake\s+test\b',
    r'\byarn\s+test\b',
    r'\bpnpm\s+test\b',
]

def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    cmd = data.get("tool_input", {}).get("command", "")
    if not cmd:
        return

    for pattern in TEST_PATTERNS:
        if re.search(pattern, cmd, re.I):
            proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
            h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
            tested_file = os.path.join(tempfile.gettempdir(), f"claude-tested-{h}.txt")
            with open(tested_file, "w") as f:
                f.write("1")
            return

if __name__ == "__main__":
    main()
