#!/usr/bin/env python3
"""Tests for track_prompt.py and the shared _corrections module."""
import json
import os
import sys
import subprocess
import tempfile
import shutil

# Add parent dir so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

HOOKS_DIR = os.path.join(os.path.dirname(__file__), '..', 'hooks')

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


def run_hook(hook_name, stdin_data=None, env_override=None, raw_stdin=None):
    """Run a hook script with optional stdin JSON, return (exit_code, stdout, stderr)."""
    hook_path = os.path.join(HOOKS_DIR, hook_name)
    if raw_stdin is not None:
        input_bytes = raw_stdin
    else:
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
    tmpdir = tempfile.mkdtemp(prefix='blackbox-prompt-test-')
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
# _corrections.py classify() tests
# ============================================================
def test_classify():
    """classify() should return expected (label, rule_key) pairs."""
    print("\n--- _corrections.py classify() ---")
    sys.path.insert(0, HOOKS_DIR)
    from _corrections import classify

    cases = [
        ("no, that's wrong", 'explicit_no', 'wrong_direction'),
        ("undo that", 'undo', 'breakage'),
        ("i already told you that", 'i_said', 'context_ignored'),
        ("too complex", 'too_complex', 'overengineering'),
        ("actually let's try a different approach", 'approach_change', 'approach_change'),
        ("you broke the build", 'you_broke', 'breakage'),
        ("revert that change", 'revert', 'breakage'),
        ("why did you delete the config?", 'why_did_you', 'context_ignored'),
        ("this is way overengineered", 'overengineered', 'overengineering'),
        ("just do it", 'just_do', 'overengineering'),
        ("don't do that", 'dont_do', 'wrong_direction'),
        ("start over please", 'start_over', 'wrong_direction'),
        ("never mind, forget it", 'approach_change', 'approach_change'),
    ]
    for text, expected_label, expected_key in cases:
        label, rule_key = classify(text)
        test(f"'{text}' -> {expected_label}", label == expected_label,
             f"got label={label}")
        test(f"'{text}' -> rule_key={expected_key}", rule_key == expected_key,
             f"got rule_key={rule_key}")

    # Interruptions are not corrections
    label, rule_key = classify("Request interrupted by user")
    test("'Request interrupted by user' -> (None, None)",
         label is None and rule_key is None, f"got ({label}, {rule_key})")

    # Neutral prompts are not corrections
    for neutral in ["please add a login page", "git status", "can you write the tests now?"]:
        label, rule_key = classify(neutral)
        test(f"neutral '{neutral}' -> (None, None)",
             label is None and rule_key is None, f"got ({label}, {rule_key})")

    # Case insensitivity (classify lowercases)
    label, rule_key = classify("UNDO THAT")
    test("'UNDO THAT' (uppercase) -> undo", label == 'undo', f"got {label}")


def test_label_to_rule_key_contract():
    """LABEL_TO_RULE_KEY must cover the frozen contract exactly."""
    print("\n--- _corrections.py LABEL_TO_RULE_KEY contract ---")
    from _corrections import LABEL_TO_RULE_KEY

    expected = {
        'you_broke': 'breakage', 'that_broke': 'breakage',
        'revert': 'breakage', 'undo': 'breakage',
        'i_said': 'context_ignored', 'why_did_you': 'context_ignored',
        'overengineered': 'overengineering', 'too_complex': 'overengineering',
        'simpler': 'overengineering', 'just_do': 'overengineering',
        'explicit_no': 'wrong_direction', 'wrong': 'wrong_direction',
        'not_right': 'wrong_direction', 'not_that': 'wrong_direction',
        'not_what_i_wanted': 'wrong_direction', 'dont_do': 'wrong_direction',
        'stop_doing': 'wrong_direction', 'start_over': 'wrong_direction',
        'approach_change': 'approach_change',
    }
    test("LABEL_TO_RULE_KEY matches frozen contract", LABEL_TO_RULE_KEY == expected)


def test_patterns_match_backfill():
    """Patterns must stay in sync with scripts/backfill.py (verbatim port)."""
    print("\n--- _corrections.py patterns match backfill.py ---")
    scripts_dir = os.path.join(os.path.dirname(__file__), '..', 'scripts')
    sys.path.insert(0, scripts_dir)
    try:
        import backfill as bf
    except ImportError:
        test("backfill module importable", False, "cannot import backfill")
        return
    from _corrections import CORRECTION_PATTERNS, APPROACH_PATTERNS
    test("CORRECTION_PATTERNS identical to backfill",
         CORRECTION_PATTERNS == bf.CORRECTION_PATTERNS)
    test("APPROACH_PATTERNS identical to backfill",
         APPROACH_PATTERNS == bf.APPROACH_PATTERNS)


# ============================================================
# track_prompt.py hook tests
# ============================================================
def test_track_prompt_correction():
    """track_prompt.py should log exactly one user_correction for a correction prompt."""
    print("\n--- track_prompt.py (correction prompt) ---")
    tmpdir, env = make_test_env()
    try:
        prompt = "no, that's wrong — the endpoint should return 404"
        code, out, err = run_hook('track_prompt.py', {
            'session_id': 'abc123',
            'prompt': prompt,
        }, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")
        test("prints nothing", out.strip() == "", f"got: {out.strip()[:100]}")

        entries = read_compliance(tmpdir)
        corrections = [e for e in entries if e['type'] == 'user_correction']
        test("logs exactly one user_correction", len(corrections) == 1,
             f"got {len(corrections)}")
        if corrections:
            c = corrections[0]
            test("category is explicit_no", c['category'] == 'explicit_no',
                 f"got {c.get('category')}")
            test("rule_key is wrong_direction", c['rule_key'] == 'wrong_direction',
                 f"got {c.get('rule_key')}")
            test("snippet is first 160 chars", c['snippet'] == prompt[:160])
            test("has ts", bool(c.get('ts')))
            test("has session_id key", 'session_id' in c)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_track_prompt_snippet_truncation():
    """track_prompt.py should truncate the snippet to 160 chars."""
    print("\n--- track_prompt.py (snippet truncation) ---")
    tmpdir, env = make_test_env()
    try:
        prompt = "undo that " + ("x" * 300)
        code, out, err = run_hook('track_prompt.py', {'prompt': prompt}, env)
        test("exits cleanly", code == 0)

        entries = read_compliance(tmpdir)
        corrections = [e for e in entries if e['type'] == 'user_correction']
        test("logs one correction", len(corrections) == 1)
        if corrections:
            test("snippet truncated to 160", len(corrections[0]['snippet']) == 160,
                 f"len={len(corrections[0]['snippet'])}")
            test("category is undo", corrections[0]['category'] == 'undo')
            test("rule_key is breakage", corrections[0]['rule_key'] == 'breakage')
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_track_prompt_neutral():
    """track_prompt.py should log nothing for a neutral prompt."""
    print("\n--- track_prompt.py (neutral prompt) ---")
    tmpdir, env = make_test_env()
    try:
        code, out, err = run_hook('track_prompt.py', {
            'prompt': 'please add a login page',
        }, env)
        test("exits cleanly", code == 0)
        test("prints nothing", out.strip() == "")

        entries = read_compliance(tmpdir)
        test("no compliance entry", len(entries) == 0, f"got {len(entries)}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_track_prompt_interruption():
    """track_prompt.py should NOT log interruptions as corrections."""
    print("\n--- track_prompt.py (interruption) ---")
    tmpdir, env = make_test_env()
    try:
        code, out, err = run_hook('track_prompt.py', {
            'prompt': '[Request interrupted by user]',
        }, env)
        test("exits cleanly", code == 0)
        entries = read_compliance(tmpdir)
        test("no compliance entry for interruption", len(entries) == 0)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_track_prompt_malformed_stdin():
    """track_prompt.py should exit 0 with no output on malformed stdin."""
    print("\n--- track_prompt.py (malformed stdin) ---")
    tmpdir, env = make_test_env()
    try:
        for raw in [b'not json at all', b'', b'{"prompt": ']:
            code, out, err = run_hook('track_prompt.py', env_override=env, raw_stdin=raw)
            test(f"exits 0 on stdin {raw!r:.30}", code == 0, f"exit={code} err={err}")
            test(f"no output on stdin {raw!r:.30}", out.strip() == "")

        # Missing prompt field
        code, out, err = run_hook('track_prompt.py', {'session_id': 'abc'}, env)
        test("exits 0 with no prompt field", code == 0)

        # Non-string prompt
        code, out, err = run_hook('track_prompt.py', {'prompt': 42}, env)
        test("exits 0 with non-string prompt", code == 0)

        entries = read_compliance(tmpdir)
        test("no compliance entries from malformed input", len(entries) == 0)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    print("track_prompt test suite")
    print("=======================")

    test_classify()
    test_label_to_rule_key_contract()
    test_patterns_match_backfill()
    test_track_prompt_correction()
    test_track_prompt_snippet_truncation()
    test_track_prompt_neutral()
    test_track_prompt_interruption()
    test_track_prompt_malformed_stdin()

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*40}")

    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
