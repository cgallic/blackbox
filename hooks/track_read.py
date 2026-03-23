#!/usr/bin/env python3
"""PostToolUse hook for Read|Grep|Bash: track files Claude has seen content from.

Tracks:
- Read: file_path from tool_input
- Grep: path from tool_input + files from tool_response (files_with_matches)
- Bash: extracts file paths from cat/head/tail/less commands
"""
import sys
import json
import os
import re
import hashlib
import tempfile


def extract_paths_from_bash(cmd):
    """Extract file paths from bash commands that read files."""
    paths = set()
    # cat, head, tail, less, more + file path
    for match in re.finditer(r'\b(?:cat|head|tail|less|more)\s+["\']?([^\s;"\'|>]+)', cmd):
        p = match.group(1)
        if '/' in p or '\\' in p or '.' in p:
            paths.add(p)
    return paths


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", {})
    paths = set()

    # If no tool_name, infer from input shape
    if not tool:
        if "file_path" in tool_input:
            tool = "Read"
        elif "pattern" in tool_input:
            tool = "Grep"
        elif "command" in tool_input:
            tool = "Bash"

    if tool == "Read":
        fp = tool_input.get("file_path", "")
        if fp:
            paths.add(fp)

    elif tool == "Grep":
        # Grep searches within files — the path being searched counts
        search_path = tool_input.get("path", "")
        if search_path and os.path.isfile(search_path):
            paths.add(search_path)
        # Also extract matched file paths from response
        if isinstance(tool_response, str):
            for line in tool_response.split('\n'):
                line = line.strip()
                if line and os.path.sep in line or '/' in line:
                    # Could be "path/to/file.ts:123: matched line"
                    candidate = line.split(':')[0].strip()
                    if candidate and ('.' in candidate):
                        paths.add(candidate)
        elif isinstance(tool_response, dict):
            # files_with_matches mode returns file paths
            content = tool_response.get("content", "")
            if isinstance(content, str):
                for line in content.split('\n'):
                    line = line.strip()
                    if line and '.' in line:
                        paths.add(line)

    elif tool == "Bash":
        cmd = tool_input.get("command", "")
        paths = extract_paths_from_bash(cmd)

    if not paths:
        return

    proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    h = hashlib.md5(proj_dir.encode()).hexdigest()[:8]
    reads_file = os.path.join(tempfile.gettempdir(), f"claude-reads-{h}.txt")

    with open(reads_file, "a", encoding="utf-8") as f:
        for p in paths:
            normalized = os.path.normpath(p).replace(os.sep, "/")
            f.write(normalized + "\n")


if __name__ == "__main__":
    main()
