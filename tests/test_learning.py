#!/usr/bin/env python3
"""Tests for the learning loop — session_init rule injection, session_end learning updates."""
import json
import os
import sys
import subprocess
import tempfile
import shutil

# Add parent dir so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

HOOKS_DIR = os.path.join(os.path.dirname(__file__), '..', 'hooks')
sys.path.insert(0, HOOKS_DIR)
import _rules

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
    tmpdir = tempfile.mkdtemp(prefix='blackbox-learning-test-')
    sessions_dir = os.path.join(tmpdir, '.claude', 'sessions')
    os.makedirs(sessions_dir)
    env = {'CLAUDE_PROJECT_DIR': tmpdir}
    return tmpdir, env


def seed_compliance(tmpdir, events):
    """Write events to <tmpdir>/.claude/sessions/compliance.jsonl."""
    compliance = os.path.join(tmpdir, '.claude', 'sessions', 'compliance.jsonl')
    with open(compliance, 'w', encoding='utf-8') as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def read_compliance(tmpdir):
    compliance = os.path.join(tmpdir, '.claude', 'sessions', 'compliance.jsonl')
    entries = []
    if os.path.exists(compliance):
        with open(compliance, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
    return entries


def read_rules(tmpdir):
    """Read rules.json directly, return {rule_id: rule}."""
    path = os.path.join(tmpdir, '.claude', 'sessions', 'rules.json')
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return {r['id']: r for r in data.get('rules', [])}


SID = "learn-session-1"


def start_event():
    return {"type": "session_start", "ts": "2026-07-13T10:00:00+00:00",
            "session_id": SID, "project_hash": "learn123"}


def edit_event(read_first=True):
    return {"type": "edit_compliance", "ts": "2026-07-13T10:01:00+00:00",
            "session_id": SID, "file": "/src/main.py",
            "was_read_first": read_first, "was_overridden": False}


def commit_event(tested=True):
    return {"type": "commit_compliance", "ts": "2026-07-13T10:02:00+00:00",
            "session_id": SID, "command": "git commit -m x",
            "tests_passed_first": tested, "was_overridden": False}


def safety_event():
    return {"type": "safety_trigger", "ts": "2026-07-13T10:03:00+00:00",
            "session_id": SID, "command": "rm -rf /tmp/x", "pattern": "rm -rf",
            "severity": "warning", "occurrence": 1}


def correction_event(category, rule_key):
    return {"type": "user_correction", "ts": "2026-07-13T10:04:00+00:00",
            "session_id": SID, "category": category, "rule_key": rule_key,
            "snippet": "no, that's wrong"}


# ============================================================
# session_init.py — learning context injection
# ============================================================
def test_init_empty_prints_nothing():
    """session_init with empty store and no history prints nothing."""
    print("\n--- session_init.py (empty store, no history) ---")
    tmpdir, env = make_test_env()
    try:
        code, out, err = run_hook('session_init.py', {'session_id': SID}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")
        test("prints nothing", out.strip() == "", f"got: {out.strip()[:120]}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_init_active_rule_injects_context():
    """session_init with an active rule prints SessionStart JSON with rule text."""
    print("\n--- session_init.py (active rule) ---")
    tmpdir, env = make_test_env()
    try:
        # Two hits -> status "watch" -> active
        _rules.record_hit(tmpdir, "commit_without_test", "2026-07-01T00:00:00+00:00", count=2)

        code, out, err = run_hook('session_init.py', {'session_id': SID}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")
        test("prints one line", out.strip() != "" and len(out.strip().splitlines()) == 1,
             f"got: {out.strip()[:120]}")

        ctx = ""
        try:
            result = json.loads(out.strip())
            hso = result.get("hookSpecificOutput", {})
            test("hookEventName is SessionStart", hso.get("hookEventName") == "SessionStart")
            ctx = hso.get("additionalContext", "")
        except Exception as ex:
            test("output is valid JSON", False, str(ex))

        test("context has header", "## Blackbox: learned rules from past sessions" in ctx)
        test("context contains rule text",
             _rules.RULE_TEXTS["commit_without_test"] in ctx, f"ctx: {ctx[:200]}")
        test("context mentions WATCH status", "[WATCH]" in ctx)
        test("context under 1200 chars", len(ctx) <= 1200)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_init_bad_summary_prints_last_session_line():
    """session_init with no rules but a bad last summary prints the recap line."""
    print("\n--- session_init.py (bad last summary) ---")
    tmpdir, env = make_test_env()
    try:
        seed_compliance(tmpdir, [
            {"type": "session_summary", "ts": "2026-07-12T10:00:00+00:00",
             "score": 8.1,
             "guardrails_triggered": {"edit_blocked": 2, "commit_blocked": 1,
                                      "destructive_cmd_caught": 0},
             "user_corrections": 1},
        ])
        code, out, err = run_hook('session_init.py', {'session_id': SID}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")
        ctx = ""
        if out.strip():
            try:
                ctx = json.loads(out.strip()).get("hookSpecificOutput", {}).get("additionalContext", "")
            except Exception:
                pass
        test("prints context", ctx != "", f"got: {out.strip()[:120]}")
        test("mentions 3 guardrail triggers", "3 guardrail trigger(s)" in ctx, f"ctx: {ctx[:250]}")
        test("breakdown includes edit blocks", "2 edit blocks" in ctx, f"ctx: {ctx[:250]}")
        test("breakdown includes untested commit", "1 untested commit" in ctx, f"ctx: {ctx[:250]}")
        test("mentions 1 user correction", "1 user correction(s)" in ctx, f"ctx: {ctx[:250]}")
        test("says do not repeat", "Do not repeat these." in ctx)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# session_end.py — corrections on scorecard + summary
# ============================================================
def test_end_corrections():
    """session_end counts corrections, deducts score, extends summary."""
    print("\n--- session_end.py (user corrections) ---")
    tmpdir, env = make_test_env()
    try:
        seed_compliance(tmpdir, [
            start_event(),
            edit_event(read_first=True),
            correction_event("simpler", "overengineering"),
            correction_event("simpler", "overengineering"),
            correction_event("wrong", "wrong_direction"),
        ])
        code, out, err = run_hook('session_end.py', {'session_id': SID}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")

        scorecard = ""
        if out.strip():
            scorecard = json.loads(out.strip()).get("systemMessage", "")
        test("prints scorecard", "SESSION SUMMARY" in scorecard)
        test("scorecard shows corrections line", "User corrections: 3" in scorecard,
             scorecard[:400])
        test("scorecard shows top categories", "top: simpler x2, wrong x1" in scorecard,
             scorecard[:600])

        summaries = [e for e in read_compliance(tmpdir) if e['type'] == 'session_summary']
        test("writes session_summary", len(summaries) == 1)
        if summaries:
            s = summaries[0]
            # Score: 10 - 3*0.3 = 9.1
            test("score deducts 0.3 per correction (9.1)", s['score'] == 9.1,
                 f"got {s.get('score')}")
            test("summary has user_corrections=3", s.get('user_corrections') == 3)
            test("summary has correction_categories",
                 s.get('correction_categories') == {"simpler": 2, "wrong": 1},
                 f"got {s.get('correction_categories')}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_end_correction_deduction_capped():
    """Correction deduction is capped at 2.0 total."""
    print("\n--- session_end.py (correction cap) ---")
    tmpdir, env = make_test_env()
    try:
        events = [start_event(), edit_event(read_first=True)]
        events += [correction_event("simpler", "overengineering") for _ in range(10)]
        seed_compliance(tmpdir, events)
        code, out, err = run_hook('session_end.py', {'session_id': SID}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")
        summaries = [e for e in read_compliance(tmpdir) if e['type'] == 'session_summary']
        if summaries:
            # 10 corrections x 0.3 = 3.0, capped at 2.0 -> score 8.0
            test("deduction capped at 2.0 (score 8.0)", summaries[0]['score'] == 8.0,
                 f"got {summaries[0].get('score')}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# session_end.py — learning update writes rules.json
# ============================================================
def test_end_creates_rules_from_guardrails():
    """session_end creates rules.json entries with correct hit counts."""
    print("\n--- session_end.py (creates rules from guardrails) ---")
    tmpdir, env = make_test_env()
    try:
        seed_compliance(tmpdir, [
            start_event(),
            edit_event(read_first=False),
            edit_event(read_first=False),
            commit_event(tested=False),
            safety_event(),
        ])
        code, out, err = run_hook('session_end.py', {'session_id': SID}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")

        rules_path = os.path.join(tmpdir, '.claude', 'sessions', 'rules.json')
        test("rules.json created", os.path.exists(rules_path))
        if os.path.exists(rules_path):
            rules = read_rules(tmpdir)
            test("edit_without_read rule exists", "edit_without_read" in rules)
            test("edit_without_read has 2 hits",
                 rules.get("edit_without_read", {}).get("hits") == 2)
            test("edit_without_read escalated to watch",
                 rules.get("edit_without_read", {}).get("status") == "watch")
            test("commit_without_test has 1 hit",
                 rules.get("commit_without_test", {}).get("hits") == 1)
            test("destructive_cmd has 1 hit",
                 rules.get("destructive_cmd", {}).get("hits") == 1)

        scorecard = ""
        if out.strip():
            scorecard = json.loads(out.strip()).get("systemMessage", "")
        test("scorecard has Learning section", "Learning:" in scorecard, scorecard[:600])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_end_correction_rule_keys_recorded():
    """session_end records correction rule_keys as hits (null rule_keys skipped)."""
    print("\n--- session_end.py (correction rule_key hits) ---")
    tmpdir, env = make_test_env()
    try:
        seed_compliance(tmpdir, [
            start_event(),
            edit_event(read_first=True),
            correction_event("simpler", "overengineering"),
            correction_event("interrupted", None),
        ])
        code, out, err = run_hook('session_end.py', {'session_id': SID}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")
        rules = read_rules(tmpdir)
        test("overengineering rule created with 1 hit",
             rules.get("overengineering", {}).get("hits") == 1)
        test("no rule created for null rule_key",
             None not in rules and "None" not in rules and "null" not in rules)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_end_clean_session_increments_since_hit():
    """A session with zero hits increments sessions_since_hit for existing rules."""
    print("\n--- session_end.py (clean session bumps sessions_since_hit) ---")
    tmpdir, env = make_test_env()
    try:
        _rules.record_hit(tmpdir, "overengineering", "2026-07-01T00:00:00+00:00", count=3)
        seed_compliance(tmpdir, [
            start_event(),
            edit_event(read_first=True),
            commit_event(tested=True),
        ])
        code, out, err = run_hook('session_end.py', {'session_id': SID}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")
        rules = read_rules(tmpdir)
        test("sessions_since_hit incremented to 1",
             rules.get("overengineering", {}).get("sessions_since_hit") == 1,
             f"got {rules.get('overengineering')}")
        test("hits unchanged", rules.get("overengineering", {}).get("hits") == 3)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_end_archives_stale_rule():
    """A rule at the archive threshold gets archived and reported on the scorecard."""
    print("\n--- session_end.py (archives stale rule) ---")
    tmpdir, env = make_test_env()
    try:
        _rules.record_hit(tmpdir, "overengineering", "2026-06-01T00:00:00+00:00", count=2)
        data = _rules.load_rules(tmpdir)
        data["rules"][0]["sessions_since_hit"] = 9  # watch archives at 10
        _rules.save_rules(tmpdir, data)

        seed_compliance(tmpdir, [start_event(), edit_event(read_first=True)])
        code, out, err = run_hook('session_end.py', {'session_id': SID}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")
        rules = read_rules(tmpdir)
        test("stale rule archived", rules.get("overengineering", {}).get("status") == "archived")

        scorecard = ""
        if out.strip():
            scorecard = json.loads(out.strip()).get("systemMessage", "")
        test("scorecard reports archived rule", "archived: overengineering" in scorecard,
             scorecard[:600])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_end_second_fire_applies_delta_only():
    """Stop fires at the end of EVERY turn: later fires must apply only the
    delta since the previous summary, not recount the whole session."""
    print("\n--- session_end.py (per-turn fires apply deltas) ---")
    tmpdir, env = make_test_env()
    try:
        _rules.record_hit(tmpdir, "context_ignored", "2026-07-01T00:00:00+00:00", count=2)
        seed_compliance(tmpdir, [
            start_event(),
            edit_event(read_first=False),
            correction_event("simpler", "overengineering"),
        ])

        run_hook('session_end.py', {'session_id': SID}, env)

        # Second fire, same session, no new activity this turn
        code, out, err = run_hook('session_end.py', {'session_id': SID}, env)
        test("second fire exits cleanly", code == 0, f"exit={code} err={err}")
        rules2 = read_rules(tmpdir)
        test("edit hits not double-counted",
             rules2.get("edit_without_read", {}).get("hits") == 1,
             f"got {rules2.get('edit_without_read')}")
        test("correction hits not double-counted",
             rules2.get("overengineering", {}).get("hits") == 1,
             f"got {rules2.get('overengineering')}")
        test("clean decay applied once per session",
             rules2.get("context_ignored", {}).get("sessions_since_hit") == 1,
             f"got {rules2.get('context_ignored')}")

        # A new violation on a later turn adds exactly its delta
        compliance = os.path.join(tmpdir, '.claude', 'sessions', 'compliance.jsonl')
        with open(compliance, 'a', encoding='utf-8') as f:
            f.write(json.dumps(edit_event(read_first=False)) + "\n")
        code, out, err = run_hook('session_end.py', {'session_id': SID}, env)
        test("third fire exits cleanly", code == 0, f"exit={code} err={err}")
        rules3 = read_rules(tmpdir)
        test("new violation adds exactly one hit",
             rules3.get("edit_without_read", {}).get("hits") == 2,
             f"got {rules3.get('edit_without_read')}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_end_fallback_path_ignores_foreign_summaries():
    """Without a session_id, per-turn fires must still be delta-based against
    OUR OWN previous summary, and a concurrent session's summaries must not
    become the baseline or count as 'prior sessions'."""
    print("\n--- session_end.py (sid-less fallback: foreign summaries) ---")
    tmpdir, env = make_test_env()
    try:
        # Events carry no session_id; hook stdin carries none either.
        seed_compliance(tmpdir, [
            {"type": "session_start", "ts": "2026-07-13T10:00:00+00:00",
             "session_id": "", "project_hash": "fb1"},
            {"type": "edit_compliance", "ts": "2026-07-13T10:01:00+00:00",
             "file": "/src/a.py", "was_read_first": False, "was_overridden": False},
        ])
        code, out, err = run_hook('session_end.py', {}, env)
        test("fire 1 exits cleanly", code == 0, f"exit={code} err={err}")
        rules = read_rules(tmpdir)
        test("fire 1 records one hit",
             rules.get("edit_without_read", {}).get("hits") == 1,
             f"got {rules.get('edit_without_read')}")

        # A concurrent session appends its own zero-count summary.
        compliance = os.path.join(tmpdir, '.claude', 'sessions', 'compliance.jsonl')
        with open(compliance, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                "type": "session_summary", "ts": "2026-07-13T10:02:00+00:00",
                "session_id": "other-session", "score": 10.0,
                "edits_total": 0, "edits_without_read": 0,
                "commits_total": 0, "commits_without_test": 0,
                "safety_triggers": 0,
                "guardrails_triggered": {"edit_blocked": 0, "commit_blocked": 0,
                                         "destructive_cmd_caught": 0},
            }) + "\n")

        code, out, err = run_hook('session_end.py', {}, env)
        test("fire 2 exits cleanly", code == 0, f"exit={code} err={err}")
        rules = read_rules(tmpdir)
        test("foreign summary is not the delta baseline (hits stay 1)",
             rules.get("edit_without_read", {}).get("hits") == 1,
             f"got {rules.get('edit_without_read')}")

        summaries = [e for e in read_compliance(tmpdir)
                     if e['type'] == 'session_summary'
                     and e.get('session_id') != 'other-session']
        test("own summaries do not count as prior sessions",
             summaries and summaries[-1].get('repeated_patterns') == [],
             f"got {summaries[-1].get('repeated_patterns') if summaries else None}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# Scorecard box integrity
# ============================================================
def test_scorecard_box_integrity():
    """Every line of the printed scorecard has identical length."""
    print("\n--- session_end.py (box integrity) ---")
    tmpdir, env = make_test_env()
    try:
        # Busy session: guardrails + corrections + learning changes
        seed_compliance(tmpdir, [
            start_event(),
            edit_event(read_first=False),
            edit_event(read_first=False),
            commit_event(tested=False),
            safety_event(),
            correction_event("simpler", "overengineering"),
            correction_event("i_said", "context_ignored"),
            correction_event("wrong", "wrong_direction"),
        ])
        code, out, err = run_hook('session_end.py', {'session_id': SID}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")
        scorecard = ""
        if out.strip():
            scorecard = json.loads(out.strip()).get("systemMessage", "")
        test("prints scorecard", scorecard != "")
        if scorecard:
            lengths = {len(line) for line in scorecard.splitlines()}
            test("all lines identical length", len(lengths) == 1,
                 f"lengths: {sorted(lengths)}\n{scorecard}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# Learning failure never blocks the scorecard
# ============================================================
def test_learning_failure_still_prints_scorecard():
    """rules.json pre-created as a DIRECTORY: learning fails, scorecard still prints."""
    print("\n--- session_end.py (learning failure) ---")
    tmpdir, env = make_test_env()
    try:
        os.makedirs(os.path.join(tmpdir, '.claude', 'sessions', 'rules.json'))
        seed_compliance(tmpdir, [
            start_event(),
            edit_event(read_first=False),
            correction_event("simpler", "overengineering"),
        ])
        code, out, err = run_hook('session_end.py', {'session_id': SID}, env)
        test("exits cleanly", code == 0, f"exit={code} err={err}")
        scorecard = ""
        if out.strip():
            scorecard = json.loads(out.strip()).get("systemMessage", "")
        test("still prints scorecard", "SESSION SUMMARY" in scorecard)
        test("corrections still counted", "User corrections: 1" in scorecard)

        summaries = [e for e in read_compliance(tmpdir) if e['type'] == 'session_summary']
        test("summary still written", len(summaries) == 1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    print("blackbox learning-loop test suite")
    print("=================================")

    test_init_empty_prints_nothing()
    test_init_active_rule_injects_context()
    test_init_bad_summary_prints_last_session_line()
    test_end_corrections()
    test_end_correction_deduction_capped()
    test_end_creates_rules_from_guardrails()
    test_end_correction_rule_keys_recorded()
    test_end_clean_session_increments_since_hit()
    test_end_archives_stale_rule()
    test_end_second_fire_applies_delta_only()
    test_end_fallback_path_ignores_foreign_summaries()
    test_scorecard_box_integrity()
    test_learning_failure_still_prints_scorecard()

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*40}")

    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
