#!/usr/bin/env python3
"""Tests for retro-loop hooks — blocking behavior, overrides, violations, scorecard."""
import json
import os
import re
import sys
import subprocess
import tempfile
import shutil

# Add parent dir so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

HOOKS_DIR = os.path.join(os.path.dirname(__file__), '..', 'hooks')
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'scripts')

passed = 0
failed = 0


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} {detail}")


def run_hook(hook_name, stdin_data=None, env_override=None):
    """Run a hook script with optional stdin JSON, return (exit_code, stdout, stderr)."""
    hook_path = os.path.join(HOOKS_DIR, hook_name)
    input_bytes = json.dumps(stdin_data).encode() if stdin_data else b'{}'
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        [sys.executable, hook_path],
        input=input_bytes,
        capture_output=True,
        timeout=10,
        env=env,
    )
    return result.returncode, result.stdout.decode(errors='replace'), result.stderr.decode(errors='replace')


def make_test_env():
    """Create a temp project dir with sessions subdir, return (tmpdir, env_dict)."""
    tmpdir = tempfile.mkdtemp(prefix='retro-loop-test-')
    sessions_dir = os.path.join(tmpdir, '.claude', 'sessions')
    os.makedirs(sessions_dir)
    env = {'CLAUDE_PROJECT_DIR': tmpdir}
    return tmpdir, env


def read_compliance(tmpdir):
    """Read all compliance entries from a test project dir."""
    compliance = os.path.join(tmpdir, '.claude', 'sessions', 'compliance.jsonl')
    entries = []
    if os.path.exists(compliance):
        with open(compliance, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
    return entries


# ============================================================
# track_read.py tests
# ============================================================
def test_track_read():
    """track_read.py should append file path to temp tracking file."""
    print("\n--- track_read.py ---")
    tmpdir, env = make_test_env()
    try:
        code, out, err = run_hook('track_read.py', {
            'tool_name': 'Read',
            'tool_input': {'file_path': '/tmp/test-file.py'},
        }, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")

        # Check tracking file was written
        import hashlib
        h = hashlib.md5(tmpdir.encode()).hexdigest()[:8]
        reads_file = os.path.join(tempfile.gettempdir(), f"claude-reads-{h}.txt")
        test("writes reads tracking file", os.path.exists(reads_file))
        if os.path.exists(reads_file):
            with open(reads_file) as f:
                content = f.read()
            test("tracking file contains file path", '/tmp/test-file.py' in content)
            os.remove(reads_file)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_track_read_empty_input():
    """track_read.py should handle empty input gracefully."""
    print("\n--- track_read.py (empty input) ---")
    code, out, err = run_hook('track_read.py', {'tool_input': {}})
    test("exits cleanly with empty input", code == 0)


# ============================================================
# check_edit.py tests (PreToolUse — BLOCKING)
# ============================================================
def test_check_edit_blocks_unread():
    """check_edit.py should output deny JSON when file was not read."""
    print("\n--- check_edit.py (blocks unread) ---")
    tmpdir, env = make_test_env()
    try:
        code, out, err = run_hook('check_edit.py', {
            'tool_name': 'Edit',
            'tool_input': {'file_path': '/tmp/never-read.py'},
        }, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")

        # Should output deny JSON
        if out.strip():
            result = json.loads(out.strip())
            hook_output = result.get("hookSpecificOutput", {})
            test("outputs deny decision", hook_output.get("permissionDecision") == "deny")
            test("includes BLOCKED in reason", "BLOCKED" in hook_output.get("permissionDecisionReason", ""))
        else:
            test("outputs deny JSON", False, "no stdout output")

        # Should log to compliance
        entries = read_compliance(tmpdir)
        edits = [e for e in entries if e['type'] == 'edit_compliance']
        test("logs edit_compliance", len(edits) == 1)
        if edits:
            test("was_read_first is false", edits[0]['was_read_first'] is False)
            test("was_overridden is false", edits[0]['was_overridden'] is False)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_check_edit_allows_read_file():
    """check_edit.py should NOT block if file was read first."""
    print("\n--- check_edit.py (allows read file) ---")
    tmpdir, env = make_test_env()
    try:
        # First, track a read
        run_hook('track_read.py', {
            'tool_input': {'file_path': '/project/src/main.py'},
        }, env)

        # Then try to edit it
        code, out, err = run_hook('check_edit.py', {
            'tool_name': 'Edit',
            'tool_input': {'file_path': '/project/src/main.py'},
        }, env)
        test("exits cleanly", code == 0)
        test("no deny output (allowed)", out.strip() == "", f"got: {out.strip()[:100]}")

        entries = read_compliance(tmpdir)
        edits = [e for e in entries if e['type'] == 'edit_compliance']
        if edits:
            test("was_read_first is true", edits[0]['was_read_first'] is True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_check_edit_override():
    """check_edit.py should allow edit with override file."""
    print("\n--- check_edit.py (override) ---")
    tmpdir, env = make_test_env()
    try:
        import hashlib
        h = hashlib.md5(tmpdir.encode()).hexdigest()[:8]
        override_path = os.path.join(tempfile.gettempdir(), f"claude-override-{h}.json")

        # Create override
        with open(override_path, 'w') as f:
            json.dump({"action": "edit", "reason": "test override", "ts": "2026-01-01", "uses": 1}, f)

        code, out, err = run_hook('check_edit.py', {
            'tool_name': 'Edit',
            'tool_input': {'file_path': '/tmp/unread-file.py'},
        }, env)
        test("exits cleanly", code == 0)
        test("no deny output (override consumed)", out.strip() == "", f"got: {out.strip()[:100]}")

        entries = read_compliance(tmpdir)
        edits = [e for e in entries if e['type'] == 'edit_compliance']
        if edits:
            test("was_overridden is true", edits[0]['was_overridden'] is True)

        # Override should be consumed (uses=0)
        with open(override_path) as f:
            data = json.load(f)
        test("override uses decremented to 0", data['uses'] == 0)

        # Second edit without re-reading should now be blocked
        code2, out2, err2 = run_hook('check_edit.py', {
            'tool_name': 'Edit',
            'tool_input': {'file_path': '/tmp/another-unread.py'},
        }, env)
        if out2.strip():
            result2 = json.loads(out2.strip())
            test("second edit blocked (override consumed)", result2.get("hookSpecificOutput", {}).get("permissionDecision") == "deny")
        else:
            test("second edit blocked (override consumed)", False, "no deny output")

        # Clean up
        if os.path.exists(override_path):
            os.remove(override_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_check_edit_violation_counter():
    """check_edit.py should increment violation counter."""
    print("\n--- check_edit.py (violation counter) ---")
    tmpdir, env = make_test_env()
    try:
        import hashlib
        h = hashlib.md5(tmpdir.encode()).hexdigest()[:8]
        violations_path = os.path.join(tempfile.gettempdir(), f"claude-violations-{h}.json")

        # Remove any existing violations
        if os.path.exists(violations_path):
            os.remove(violations_path)

        # Trigger 3 violations
        for i in range(3):
            run_hook('check_edit.py', {
                'tool_name': 'Edit',
                'tool_input': {'file_path': f'/tmp/unread-{i}.py'},
            }, env)

        test("violations file created", os.path.exists(violations_path))
        if os.path.exists(violations_path):
            with open(violations_path) as f:
                violations = json.load(f)
            test("edit_without_read count is 3", violations.get('edit_without_read') == 3)
            os.remove(violations_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# check_commit.py tests (PreToolUse — BLOCKING)
# ============================================================
def test_check_commit_blocks_without_tests():
    """check_commit.py should output deny JSON when tests haven't passed."""
    print("\n--- check_commit.py (blocks without tests) ---")
    tmpdir, env = make_test_env()
    try:
        code, out, err = run_hook('check_commit.py', {
            'tool_name': 'Bash',
            'tool_input': {'command': 'git commit -m "test"'},
        }, env)
        test("exits cleanly", code == 0)

        if out.strip():
            result = json.loads(out.strip())
            hook_output = result.get("hookSpecificOutput", {})
            test("outputs deny decision", hook_output.get("permissionDecision") == "deny")
            test("includes BLOCKED in reason", "BLOCKED" in hook_output.get("permissionDecisionReason", ""))
        else:
            test("outputs deny JSON", False, "no stdout output")

        entries = read_compliance(tmpdir)
        commits = [e for e in entries if e['type'] == 'commit_compliance']
        if commits:
            test("tests_passed_first is false", commits[0]['tests_passed_first'] is False)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_check_commit_allows_after_tests():
    """check_commit.py should allow commit after tests passed."""
    print("\n--- check_commit.py (allows after tests) ---")
    tmpdir, env = make_test_env()
    try:
        import hashlib
        h = hashlib.md5(tmpdir.encode()).hexdigest()[:8]

        # Simulate passing tests by writing the marker
        tested_file = os.path.join(tempfile.gettempdir(), f"claude-tested-{h}.txt")
        with open(tested_file, 'w') as f:
            f.write("passed")

        code, out, err = run_hook('check_commit.py', {
            'tool_name': 'Bash',
            'tool_input': {'command': 'git commit -m "test"'},
        }, env)
        test("exits cleanly", code == 0)
        test("no deny output (allowed)", out.strip() == "", f"got: {out.strip()[:100]}")

        entries = read_compliance(tmpdir)
        commits = [e for e in entries if e['type'] == 'commit_compliance']
        if commits:
            test("tests_passed_first is true", commits[0]['tests_passed_first'] is True)

        # Clean up
        if os.path.exists(tested_file):
            os.remove(tested_file)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_check_commit_ignores_non_commit():
    """check_commit.py should ignore non-commit commands."""
    print("\n--- check_commit.py (ignores non-commit) ---")
    tmpdir, env = make_test_env()
    try:
        code, out, err = run_hook('check_commit.py', {
            'tool_name': 'Bash',
            'tool_input': {'command': 'git status'},
        }, env)
        test("exits cleanly", code == 0)
        test("no output", out.strip() == "")

        entries = read_compliance(tmpdir)
        test("no compliance entry", len(entries) == 0)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_check_commit_override():
    """check_commit.py should allow commit with override."""
    print("\n--- check_commit.py (override) ---")
    tmpdir, env = make_test_env()
    try:
        import hashlib
        h = hashlib.md5(tmpdir.encode()).hexdigest()[:8]
        override_path = os.path.join(tempfile.gettempdir(), f"claude-override-{h}.json")

        with open(override_path, 'w') as f:
            json.dump({"action": "commit", "reason": "tests broken upstream", "ts": "2026-01-01", "uses": 1}, f)

        code, out, err = run_hook('check_commit.py', {
            'tool_name': 'Bash',
            'tool_input': {'command': 'git commit -m "hotfix"'},
        }, env)
        test("exits cleanly", code == 0)
        test("no deny output (override consumed)", out.strip() == "", f"got: {out.strip()[:100]}")

        entries = read_compliance(tmpdir)
        commits = [e for e in entries if e['type'] == 'commit_compliance']
        if commits:
            test("was_overridden is true", commits[0]['was_overridden'] is True)

        if os.path.exists(override_path):
            os.remove(override_path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# track_test.py tests
# ============================================================
def test_track_test_passing():
    """track_test.py should write marker when tests pass."""
    print("\n--- track_test.py (passing tests) ---")
    tmpdir, env = make_test_env()
    try:
        import hashlib
        h = hashlib.md5(tmpdir.encode()).hexdigest()[:8]
        tested_file = os.path.join(tempfile.gettempdir(), f"claude-tested-{h}.txt")

        if os.path.exists(tested_file):
            os.remove(tested_file)

        code, out, err = run_hook('track_test.py', {
            'tool_input': {'command': 'npm test'},
            'tool_response': 'Tests: 5 passed, 0 failed',
        }, env)
        test("exits cleanly", code == 0)
        test("writes tested marker", os.path.exists(tested_file))
        if os.path.exists(tested_file):
            with open(tested_file) as f:
                content = f.read()
            test("marker says 'passed'", content.strip() == "passed")
            os.remove(tested_file)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_track_test_failing():
    """track_test.py should NOT write marker when tests fail."""
    print("\n--- track_test.py (failing tests) ---")
    tmpdir, env = make_test_env()
    try:
        import hashlib
        h = hashlib.md5(tmpdir.encode()).hexdigest()[:8]
        tested_file = os.path.join(tempfile.gettempdir(), f"claude-tested-{h}.txt")

        if os.path.exists(tested_file):
            os.remove(tested_file)

        code, out, err = run_hook('track_test.py', {
            'tool_input': {'command': 'npm test'},
            'tool_response': 'Tests: 3 passed, 2 failed\nFAILED',
        }, env)
        test("exits cleanly", code == 0)
        test("does NOT write tested marker", not os.path.exists(tested_file))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_track_test_error_exit():
    """track_test.py should NOT write marker on non-zero exit."""
    print("\n--- track_test.py (error exit code) ---")
    tmpdir, env = make_test_env()
    try:
        import hashlib
        h = hashlib.md5(tmpdir.encode()).hexdigest()[:8]
        tested_file = os.path.join(tempfile.gettempdir(), f"claude-tested-{h}.txt")

        if os.path.exists(tested_file):
            os.remove(tested_file)

        code, out, err = run_hook('track_test.py', {
            'tool_input': {'command': 'pytest'},
            'tool_response': 'Exit code 1\nError: test_login failed',
        }, env)
        test("exits cleanly", code == 0)
        test("does NOT write tested marker", not os.path.exists(tested_file))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_track_test_ignores_non_test():
    """track_test.py should ignore non-test commands."""
    print("\n--- track_test.py (ignores non-test) ---")
    tmpdir, env = make_test_env()
    try:
        import hashlib
        h = hashlib.md5(tmpdir.encode()).hexdigest()[:8]
        tested_file = os.path.join(tempfile.gettempdir(), f"claude-tested-{h}.txt")

        if os.path.exists(tested_file):
            os.remove(tested_file)

        code, out, err = run_hook('track_test.py', {
            'tool_input': {'command': 'ls -la'},
            'tool_response': 'total 42',
        }, env)
        test("exits cleanly", code == 0)
        test("does NOT write tested marker", not os.path.exists(tested_file))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# track_safety.py tests
# ============================================================
def test_track_safety_catches_rm():
    """track_safety.py should log destructive commands with escalation."""
    print("\n--- track_safety.py ---")
    tmpdir, env = make_test_env()
    try:
        code, out, err = run_hook('track_safety.py', {
            'tool_name': 'Bash',
            'tool_input': {'command': 'rm -rf /tmp/important'},
        }, env)
        test("exits cleanly", code == 0)

        entries = read_compliance(tmpdir)
        safety = [e for e in entries if e['type'] == 'safety_trigger']
        test("catches rm -rf", len(safety) == 1)
        if safety:
            test("pattern is rm -rf", safety[0]['pattern'] == 'rm -rf')
            test("severity is warning (1st)", safety[0]['severity'] == 'warning')
            test("occurrence is 1", safety[0]['occurrence'] == 1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_track_safety_escalation():
    """track_safety.py should escalate to block on 3rd occurrence."""
    print("\n--- track_safety.py (escalation) ---")
    tmpdir, env = make_test_env()
    try:
        # Trigger 3 safety events
        for i in range(3):
            run_hook('track_safety.py', {
                'tool_name': 'Bash',
                'tool_input': {'command': 'rm -rf /tmp/stuff'},
            }, env)

        entries = read_compliance(tmpdir)
        safety = [e for e in entries if e['type'] == 'safety_trigger']
        test("3 safety triggers logged", len(safety) == 3)
        if len(safety) == 3:
            test("1st is warning", safety[0]['severity'] == 'warning')
            test("2nd is warning", safety[1]['severity'] == 'warning')
            test("3rd is block", safety[2]['severity'] == 'block')
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_track_safety_ignores_safe():
    """track_safety.py should ignore safe commands."""
    print("\n--- track_safety.py (safe command) ---")
    tmpdir, env = make_test_env()
    try:
        run_hook('track_safety.py', {
            'tool_name': 'Bash',
            'tool_input': {'command': 'ls -la'},
        }, env)
        entries = read_compliance(tmpdir)
        test("ignores safe commands", len(entries) == 0)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# session_init.py tests
# ============================================================
def test_session_init():
    """session_init.py should clear all temp files and log session_start."""
    print("\n--- session_init.py ---")
    tmpdir, env = make_test_env()
    try:
        import hashlib
        h = hashlib.md5(tmpdir.encode()).hexdigest()[:8]
        tmp = tempfile.gettempdir()

        # Create temp files that should be cleared
        for name in [f"claude-reads-{h}.txt", f"claude-tested-{h}.txt",
                     f"claude-violations-{h}.json", f"claude-override-{h}.json"]:
            with open(os.path.join(tmp, name), 'w') as f:
                f.write("stale data")

        code, out, err = run_hook('session_init.py', {}, env)
        test("exits cleanly", code == 0)

        # Check all temp files were cleared
        for name in [f"claude-reads-{h}.txt", f"claude-tested-{h}.txt",
                     f"claude-violations-{h}.json", f"claude-override-{h}.json"]:
            test(f"cleared {name}", not os.path.exists(os.path.join(tmp, name)))

        # Check session_start logged
        entries = read_compliance(tmpdir)
        starts = [e for e in entries if e['type'] == 'session_start']
        test("logs session_start", len(starts) == 1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# session_end.py tests
# ============================================================
def test_session_end_scorecard():
    """session_end.py should produce scorecard output and summary."""
    print("\n--- session_end.py (scorecard) ---")
    tmpdir, env = make_test_env()
    try:
        # Seed compliance.jsonl with a session
        compliance = os.path.join(tmpdir, '.claude', 'sessions', 'compliance.jsonl')
        events = [
            {"type": "session_start", "ts": "2026-03-22T10:00:00+00:00", "project_hash": "test1234"},
            {"type": "edit_compliance", "ts": "2026-03-22T10:01:00+00:00", "file": "/src/main.py", "was_read_first": True, "was_overridden": False},
            {"type": "edit_compliance", "ts": "2026-03-22T10:02:00+00:00", "file": "/src/other.py", "was_read_first": False, "was_overridden": False},
            {"type": "commit_compliance", "ts": "2026-03-22T10:03:00+00:00", "command": "git commit -m test", "tests_passed_first": True, "was_overridden": False},
            {"type": "safety_trigger", "ts": "2026-03-22T10:04:00+00:00", "command": "rm -rf /tmp", "pattern": "rm -rf", "severity": "warning", "occurrence": 1},
        ]
        with open(compliance, 'w', encoding='utf-8') as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

        code, out, err = run_hook('session_end.py', {}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")

        if out.strip():
            result = json.loads(out.strip())
            hook_output = result.get("hookSpecificOutput", {})
            test("has Stop hookEventName", hook_output.get("hookEventName") == "Stop")
            scorecard = hook_output.get("systemMessage", "")
            test("scorecard contains AGENT SCORECARD", "AGENT SCORECARD" in scorecard)
            test("scorecard contains Score", "Score:" in scorecard)
            test("scorecard contains timeline", "Timeline:" in scorecard or "EDIT" in scorecard)
        else:
            test("outputs scorecard JSON", False, "no stdout output")

        # Check summary was written
        entries = read_compliance(tmpdir)
        summaries = [e for e in entries if e['type'] == 'session_summary']
        test("writes session_summary", len(summaries) == 1)
        if summaries:
            s = summaries[0]
            test("summary has score", 'score' in s)
            test("summary counts 2 edits", s['edits_total'] == 2)
            test("summary counts 1 edit without read", s['edits_without_read'] == 1)
            test("summary counts 1 safety trigger", s['safety_triggers'] == 1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_session_end_perfect_score():
    """session_end.py should give 10.0 for a clean session."""
    print("\n--- session_end.py (perfect score) ---")
    tmpdir, env = make_test_env()
    try:
        compliance = os.path.join(tmpdir, '.claude', 'sessions', 'compliance.jsonl')
        events = [
            {"type": "session_start", "ts": "2026-03-22T10:00:00+00:00", "project_hash": "test1234"},
            {"type": "edit_compliance", "ts": "2026-03-22T10:01:00+00:00", "file": "/src/main.py", "was_read_first": True, "was_overridden": False},
            {"type": "commit_compliance", "ts": "2026-03-22T10:02:00+00:00", "command": "git commit", "tests_passed_first": True, "was_overridden": False},
        ]
        with open(compliance, 'w', encoding='utf-8') as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

        code, out, err = run_hook('session_end.py', {}, env)
        entries = read_compliance(tmpdir)
        summaries = [e for e in entries if e['type'] == 'session_summary']
        if summaries:
            test("perfect session scores 10.0", summaries[0]['score'] == 10.0)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# _violations.py module tests
# ============================================================
def test_violations_module():
    """Test the shared violations module directly."""
    print("\n--- _violations.py (module) ---")
    sys.path.insert(0, HOOKS_DIR)
    import _violations as v

    # Test with a fake project hash
    test_hash = "testmod1"
    violations_path = os.path.join(tempfile.gettempdir(), f"claude-violations-{test_hash}.json")
    override_path = os.path.join(tempfile.gettempdir(), f"claude-override-{test_hash}.json")

    # Clean slate
    for p in [violations_path, override_path]:
        if os.path.exists(p):
            os.remove(p)

    # Test get_violations (empty)
    violations = v.get_violations(test_hash)
    test("empty violations returns empty dict", violations == {})

    # Test increment
    count = v.increment_violation(test_hash, "test_type")
    test("first increment returns 1", count == 1)
    count = v.increment_violation(test_hash, "test_type")
    test("second increment returns 2", count == 2)
    count = v.increment_violation(test_hash, "other_type")
    test("different type starts at 1", count == 1)

    violations = v.get_violations(test_hash)
    test("violations dict correct", violations == {"test_type": 2, "other_type": 1})

    # Test override
    result = v.get_override(test_hash, "edit")
    test("no override returns None", result is None)

    # Create override
    with open(override_path, 'w') as f:
        json.dump({"action": "edit", "reason": "test", "ts": "2026-01-01", "uses": 1}, f)

    result = v.get_override(test_hash, "edit")
    test("override returns reason", result == "test")

    result = v.get_override(test_hash, "edit")
    test("consumed override returns None", result is None)

    result = v.get_override(test_hash, "commit")
    test("wrong action returns None", result is None)

    # Clean up
    for p in [violations_path, override_path]:
        if os.path.exists(p):
            os.remove(p)


# ============================================================
# _override.py CLI tests
# ============================================================
def test_override_cli():
    """Test the override CLI script."""
    print("\n--- _override.py (CLI) ---")
    tmpdir, env = make_test_env()
    try:
        import hashlib
        h = hashlib.md5(tmpdir.encode()).hexdigest()[:8]
        override_path = os.path.join(tempfile.gettempdir(), f"claude-override-{h}.json")

        if os.path.exists(override_path):
            os.remove(override_path)

        full_env = os.environ.copy()
        full_env['CLAUDE_PROJECT_DIR'] = tmpdir

        result = subprocess.run(
            [sys.executable, os.path.join(HOOKS_DIR, '_override.py'), 'edit', '--reason', 'emergency hotfix'],
            capture_output=True, timeout=10, env=full_env,
        )
        test("exits cleanly", result.returncode == 0, result.stderr.decode(errors='replace'))
        test("override file created", os.path.exists(override_path))

        if os.path.exists(override_path):
            with open(override_path) as f:
                data = json.load(f)
            test("action is edit", data['action'] == 'edit')
            test("reason is correct", data['reason'] == 'emergency hotfix')
            test("uses is 1", data['uses'] == 1)
            os.remove(override_path)

        # Test compliance logging
        entries = read_compliance(tmpdir)
        overrides = [e for e in entries if e['type'] == 'override_granted']
        test("override logged to compliance", len(overrides) == 1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# Full session lifecycle integration test
# ============================================================
def test_session_lifecycle():
    """Full lifecycle: init -> read -> edit (ok) -> edit (blocked) -> test -> commit -> end."""
    print("\n--- Session Lifecycle (integration) ---")
    tmpdir, env = make_test_env()
    try:
        full_env = os.environ.copy()
        full_env['CLAUDE_PROJECT_DIR'] = tmpdir

        def run(hook, data):
            return subprocess.run(
                [sys.executable, os.path.join(HOOKS_DIR, hook)],
                input=json.dumps(data).encode(),
                capture_output=True, env=full_env, timeout=10,
            )

        # 1. Session init
        run('session_init.py', {})

        # 2. Read a file
        run('track_read.py', {'tool_input': {'file_path': '/project/src/main.py'}})

        # 3. Edit the same file (should be allowed)
        r1 = run('check_edit.py', {'tool_input': {'file_path': '/project/src/main.py'}})
        test("edit of read file: no deny", r1.stdout.decode().strip() == "")

        # 4. Edit a different file (should be BLOCKED)
        r2 = run('check_edit.py', {'tool_input': {'file_path': '/project/src/other.py'}})
        if r2.stdout.decode().strip():
            result2 = json.loads(r2.stdout.decode().strip())
            test("edit of unread file: blocked", result2.get("hookSpecificOutput", {}).get("permissionDecision") == "deny")
        else:
            test("edit of unread file: blocked", False, "no deny output")

        # 5. Run passing tests
        run('track_test.py', {'tool_input': {'command': 'npm test'}, 'tool_response': 'All tests passed'})

        # 6. Commit (should be allowed)
        r3 = run('check_commit.py', {'tool_input': {'command': 'git commit -m "test"'}})
        test("commit after tests: no deny", r3.stdout.decode().strip() == "")

        # 7. Session end
        r4 = run('session_end.py', {})
        if r4.stdout.decode().strip():
            result4 = json.loads(r4.stdout.decode().strip())
            scorecard = result4.get("hookSpecificOutput", {}).get("systemMessage", "")
            test("session end produces scorecard", "AGENT SCORECARD" in scorecard)

        # Verify compliance data
        entries = read_compliance(tmpdir)
        types = [e['type'] for e in entries]
        test("has session_start", 'session_start' in types)
        test("has edit_compliance", 'edit_compliance' in types)
        test("has commit_compliance", 'commit_compliance' in types)
        test("has session_summary", 'session_summary' in types)

        edits = [e for e in entries if e['type'] == 'edit_compliance']
        test("tracked 2 edits", len(edits) == 2)
        if len(edits) == 2:
            test("first edit was read first", edits[0]['was_read_first'] is True)
            test("second edit was NOT read first", edits[1]['was_read_first'] is False)

        commits = [e for e in entries if e['type'] == 'commit_compliance']
        if commits:
            test("commit after tests: tests_passed_first=true", commits[0]['tests_passed_first'] is True)

        summaries = [e for e in entries if e['type'] == 'session_summary']
        if summaries:
            s = summaries[0]
            test("summary counts 2 edits", s['edits_total'] == 2)
            test("summary counts 1 edit without read", s['edits_without_read'] == 1)
            test("summary counts 1 commit", s['commits_total'] == 1)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# Backfill pattern tests
# ============================================================
def test_backfill_patterns():
    """Test that backfill correction/error patterns match correctly."""
    print("\n--- Backfill Pattern Matching ---")

    sys.path.insert(0, SCRIPTS_DIR)
    try:
        import backfill as bf
    except ImportError:
        # Fallback for old name
        try:
            import backfill_sessions as bf
        except ImportError:
            test("backfill module importable", False, "cannot import backfill or backfill_sessions")
            return

    test("derive_product_name from path",
         bf.derive_product_name('C--Users-cgall-Dev-adminpanelnew') == 'adminpanelnew')
    test("derive_product_name short key",
         bf.derive_product_name('E--Dev2-MyApp') == 'MyApp')

    for pattern, label in bf.CORRECTION_PATTERNS:
        try:
            re.compile(pattern)
            compiled = True
        except re.error:
            compiled = False
        test(f"pattern '{label}' compiles", compiled)

    test("'just do it' matches just_do",
         any(re.search(p, 'can you just do it?') for p, l in bf.CORRECTION_PATTERNS if l == 'just_do'))
    test("'git status' does NOT match corrections",
         not any(re.search(p, 'git status') for p, _ in bf.CORRECTION_PATTERNS))
    test("'Request interrupted by user' matches interrupted",
         any(re.search(p, 'Request interrupted by user') for p, l in bf.CORRECTION_PATTERNS if l == 'interrupted'))


# ============================================================
# Setup script syntax test
# ============================================================
def test_setup_syntax():
    """Verify setup script has valid bash syntax."""
    print("\n--- setup syntax ---")
    setup_path = os.path.join(os.path.dirname(__file__), '..', 'setup')
    test("setup exists", os.path.exists(setup_path))

    if os.path.exists(setup_path):
        with open(setup_path, 'r') as f:
            content = f.read()
        test("has bash shebang", content.startswith('#!/usr/bin/env bash'))
        test("uses set -e", 'set -e' in content)
        test("uses python heredoc (not inline shell substitution)", 'PYEOF' in content)
        test("references settings.local.json", 'settings.local.json' in content)


# ============================================================
# VERSION file test
# ============================================================
def test_version():
    """Verify VERSION file exists with semver."""
    print("\n--- VERSION ---")
    version_path = os.path.join(os.path.dirname(__file__), '..', 'VERSION')
    test("VERSION file exists", os.path.exists(version_path))
    if os.path.exists(version_path):
        with open(version_path) as f:
            ver = f.read().strip()
        test("VERSION is semver", bool(re.match(r'^\d+\.\d+\.\d+$', ver)))


# ============================================================
# blackbox CLI test
# ============================================================
def test_blackbox_cli():
    """Test the blackbox CLI help output."""
    print("\n--- blackbox CLI ---")
    cli_path = os.path.join(os.path.dirname(__file__), '..', 'bin', 'blackbox')
    test("blackbox CLI exists", os.path.exists(cli_path))

    if os.path.exists(cli_path):
        with open(cli_path) as f:
            content = f.read()
        test("has bash shebang", '#!/usr/bin/env bash' in content)
        test("has report command", 'report)' in content)
        test("has override command", 'override)' in content)
        test("has version command", 'version)' in content)
        test("has backfill command", 'backfill)' in content)


def main():
    print("retro-loop test suite")
    print("=====================")

    test_track_read()
    test_track_read_empty_input()
    test_check_edit_blocks_unread()
    test_check_edit_allows_read_file()
    test_check_edit_override()
    test_check_edit_violation_counter()
    test_check_commit_blocks_without_tests()
    test_check_commit_allows_after_tests()
    test_check_commit_ignores_non_commit()
    test_check_commit_override()
    test_track_test_passing()
    test_track_test_failing()
    test_track_test_error_exit()
    test_track_test_ignores_non_test()
    test_track_safety_catches_rm()
    test_track_safety_escalation()
    test_track_safety_ignores_safe()
    test_session_init()
    test_session_end_scorecard()
    test_session_end_perfect_score()
    test_violations_module()
    test_override_cli()
    test_session_lifecycle()
    test_backfill_patterns()
    test_setup_syntax()
    test_version()
    test_blackbox_cli()

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*40}")

    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
