#!/usr/bin/env python3
"""Tests for retro-loop hooks and scripts."""
import json
import os
import re
import sys
import subprocess
import tempfile
import shutil

# Add parent dir so we can import scripts
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


def run_hook(hook_name, stdin_data=None):
    """Run a hook script with optional stdin JSON, return (exit_code, stdout, stderr)."""
    hook_path = os.path.join(HOOKS_DIR, hook_name)
    input_bytes = json.dumps(stdin_data).encode() if stdin_data else b'{}'
    result = subprocess.run(
        [sys.executable, hook_path],
        input=input_bytes,
        capture_output=True,
        timeout=10,
    )
    return result.returncode, result.stdout.decode(errors='replace'), result.stderr.decode(errors='replace')


def test_track_read():
    """track_read.py should append file path to temp tracking file."""
    print("\n--- track_read.py ---")
    code, out, err = run_hook('track_read.py', {
        'tool_name': 'Read',
        'tool_input': {'file_path': '/tmp/test-file.py'},
    })
    test("exits cleanly", code == 0, f"exit={code} err={err}")


def test_check_edit():
    """check_edit.py should write compliance entry."""
    print("\n--- check_edit.py ---")

    # Create a temp project dir with sessions subdir
    tmpdir = tempfile.mkdtemp(prefix='retro-loop-test-')
    sessions_dir = os.path.join(tmpdir, '.claude', 'sessions')
    os.makedirs(sessions_dir)

    try:
        # Run with CLAUDE_PROJECT_DIR set
        hook_path = os.path.join(HOOKS_DIR, 'check_edit.py')
        input_data = json.dumps({
            'tool_name': 'Edit',
            'tool_input': {'file_path': '/tmp/test-file.py'},
        }).encode()

        env = os.environ.copy()
        env['CLAUDE_PROJECT_DIR'] = tmpdir

        result = subprocess.run(
            [sys.executable, hook_path],
            input=input_data, capture_output=True, env=env, timeout=10,
        )
        test("exits cleanly", result.returncode == 0,
             f"exit={result.returncode} err={result.stderr.decode(errors='replace')}")

        compliance = os.path.join(sessions_dir, 'compliance.jsonl')
        test("writes compliance.jsonl", os.path.exists(compliance))

        if os.path.exists(compliance):
            with open(compliance) as f:
                entry = json.loads(f.readline())
            test("entry type is edit_compliance", entry['type'] == 'edit_compliance')
            test("records was_read_first=false (file not read)", entry['was_read_first'] is False)
            test("records file path", '/tmp/test-file.py' in entry.get('file', ''))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_check_commit():
    """check_commit.py should log compliance for git commit commands."""
    print("\n--- check_commit.py ---")

    tmpdir = tempfile.mkdtemp(prefix='retro-loop-test-')
    sessions_dir = os.path.join(tmpdir, '.claude', 'sessions')
    os.makedirs(sessions_dir)

    try:
        hook_path = os.path.join(HOOKS_DIR, 'check_commit.py')
        env = os.environ.copy()
        env['CLAUDE_PROJECT_DIR'] = tmpdir

        # Test with git commit command
        input_data = json.dumps({
            'tool_name': 'Bash',
            'tool_input': {'command': 'git commit -m "test"'},
        }).encode()

        result = subprocess.run(
            [sys.executable, hook_path],
            input=input_data, capture_output=True, env=env, timeout=10,
        )
        test("exits cleanly", result.returncode == 0)

        compliance = os.path.join(sessions_dir, 'compliance.jsonl')
        test("writes compliance.jsonl", os.path.exists(compliance))

        if os.path.exists(compliance):
            with open(compliance) as f:
                entry = json.loads(f.readline())
            test("entry type is commit_compliance", entry['type'] == 'commit_compliance')
            test("records tests_ran_first=false (no tests)", entry['tests_ran_first'] is False)

        # Test with non-commit command (should NOT write)
        os.remove(compliance)
        input_data = json.dumps({
            'tool_name': 'Bash',
            'tool_input': {'command': 'git status'},
        }).encode()

        subprocess.run(
            [sys.executable, hook_path],
            input=input_data, capture_output=True, env=env, timeout=10,
        )
        test("ignores non-commit commands", not os.path.exists(compliance))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_track_safety():
    """track_safety.py should log destructive commands."""
    print("\n--- track_safety.py ---")

    tmpdir = tempfile.mkdtemp(prefix='retro-loop-test-')
    sessions_dir = os.path.join(tmpdir, '.claude', 'sessions')
    os.makedirs(sessions_dir)

    try:
        hook_path = os.path.join(HOOKS_DIR, 'track_safety.py')
        env = os.environ.copy()
        env['CLAUDE_PROJECT_DIR'] = tmpdir

        # Destructive command
        input_data = json.dumps({
            'tool_name': 'Bash',
            'tool_input': {'command': 'rm -rf /tmp/important'},
        }).encode()

        result = subprocess.run(
            [sys.executable, hook_path],
            input=input_data, capture_output=True, env=env, timeout=10,
        )
        compliance = os.path.join(sessions_dir, 'compliance.jsonl')
        test("catches rm -rf", os.path.exists(compliance))

        if os.path.exists(compliance):
            with open(compliance) as f:
                entry = json.loads(f.readline())
            test("entry type is safety_trigger", entry['type'] == 'safety_trigger')
            test("pattern is rm -rf", entry['pattern'] == 'rm -rf')

        # Safe command
        os.remove(compliance)
        input_data = json.dumps({
            'tool_name': 'Bash',
            'tool_input': {'command': 'ls -la'},
        }).encode()

        subprocess.run(
            [sys.executable, hook_path],
            input=input_data, capture_output=True, env=env, timeout=10,
        )
        test("ignores safe commands", not os.path.exists(compliance))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_session_lifecycle():
    """Full session lifecycle: init -> read -> edit -> test -> commit -> end."""
    print("\n--- Session Lifecycle (integration) ---")

    tmpdir = tempfile.mkdtemp(prefix='retro-loop-test-')
    sessions_dir = os.path.join(tmpdir, '.claude', 'sessions')
    os.makedirs(sessions_dir)

    try:
        env = os.environ.copy()
        env['CLAUDE_PROJECT_DIR'] = tmpdir

        def run(hook, data):
            return subprocess.run(
                [sys.executable, os.path.join(HOOKS_DIR, hook)],
                input=json.dumps(data).encode(),
                capture_output=True, env=env, timeout=10,
            )

        # 1. Session init
        run('session_init.py', {})

        # 2. Read a file
        run('track_read.py', {'tool_input': {'file_path': '/project/src/main.py'}})

        # 3. Edit the same file (should be compliant)
        run('check_edit.py', {'tool_input': {'file_path': '/project/src/main.py'}})

        # 4. Edit a different file (should be non-compliant)
        run('check_edit.py', {'tool_input': {'file_path': '/project/src/other.py'}})

        # 5. Run tests
        run('track_test.py', {'tool_input': {'command': 'npm test'}})

        # 6. Commit
        run('check_commit.py', {'tool_input': {'command': 'git commit -m "test"'}})

        # 7. Session end
        run('session_end.py', {})

        compliance = os.path.join(sessions_dir, 'compliance.jsonl')
        test("compliance.jsonl exists", os.path.exists(compliance))

        if os.path.exists(compliance):
            entries = []
            with open(compliance) as f:
                for line in f:
                    if line.strip():
                        entries.append(json.loads(line))

            types = [e['type'] for e in entries]
            test("has session_start", 'session_start' in types)
            test("has edit_compliance", 'edit_compliance' in types)
            test("has commit_compliance", 'commit_compliance' in types)
            test("has session_summary", 'session_summary' in types)

            # Check edit compliance details
            edits = [e for e in entries if e['type'] == 'edit_compliance']
            test("tracked 2 edits", len(edits) == 2)
            if len(edits) == 2:
                test("first edit was read first", edits[0]['was_read_first'] is True)
                test("second edit was NOT read first", edits[1]['was_read_first'] is False)

            # Check commit compliance
            commits = [e for e in entries if e['type'] == 'commit_compliance']
            if commits:
                test("commit after tests: tests_ran_first=true", commits[0]['tests_ran_first'] is True)

            # Check session summary
            summaries = [e for e in entries if e['type'] == 'session_summary']
            if summaries:
                s = summaries[0]
                test("summary counts 2 edits", s['edits_total'] == 2)
                test("summary counts 1 edit without read", s['edits_without_read'] == 1)
                test("summary edit compliance 50%", s['edit_compliance_pct'] == 50.0)
                test("summary counts 1 commit", s['commits_total'] == 1)
                test("summary commit compliance 100%", s['commit_compliance_pct'] == 100.0)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_backfill_patterns():
    """Test that backfill correction/error patterns match correctly."""
    print("\n--- Backfill Pattern Matching ---")

    # Import the module
    sys.path.insert(0, SCRIPTS_DIR)
    import backfill_sessions as bf

    test("derive_product_name from path",
         bf.derive_product_name('C--Users-cgall-Dev-adminpanelnew') == 'adminpanelnew')
    test("derive_product_name short key",
         bf.derive_product_name('E--Dev2-MyApp') == 'MyApp')

    # Test correction patterns against known inputs
    for pattern, label in bf.CORRECTION_PATTERNS:
        # Each pattern should compile without error
        try:
            re.compile(pattern)
            compiled = True
        except re.error:
            compiled = False
        test(f"pattern '{label}' compiles", compiled)

    # Test that "just do" matches but "I just do not agree" context is limited
    test("'just do it' matches just_do",
         any(re.search(p, 'can you just do it?') for p, l in bf.CORRECTION_PATTERNS if l == 'just_do'))
    test("'git status' does NOT match corrections",
         not any(re.search(p, 'git status') for p, _ in bf.CORRECTION_PATTERNS))
    test("'Request interrupted by user' matches interrupted",
         any(re.search(p, 'Request interrupted by user') for p, l in bf.CORRECTION_PATTERNS if l == 'interrupted'))


def test_setup_project_syntax():
    """Verify setup-project script has valid bash syntax."""
    print("\n--- setup-project syntax ---")
    setup_path = os.path.join(os.path.dirname(__file__), '..', 'setup-project')
    test("setup-project exists", os.path.exists(setup_path))

    if sys.platform == 'win32':
        # bash -n can't resolve Windows paths reliably; read-check instead
        with open(setup_path, 'r') as f:
            content = f.read()
        test("has bash shebang", content.startswith('#!/usr/bin/env bash'))
        test("uses set -e", 'set -e' in content)
        test("uses python3 heredoc (not inline shell substitution)",
             'PYEOF' in content or 'python3 -' in content)
    else:
        result = subprocess.run(
            ['bash', '-n', setup_path],
            capture_output=True, timeout=10,
        )
        test("setup-project has valid bash syntax", result.returncode == 0,
             result.stderr.decode(errors='replace'))


def main():
    print("retro-loop test suite")
    print("=====================")

    test_track_read()
    test_check_edit()
    test_check_commit()
    test_track_safety()
    test_session_lifecycle()
    test_backfill_patterns()
    test_setup_project_syntax()

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*40}")

    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
