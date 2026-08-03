#!/usr/bin/env python3
"""Tests for the rules store (_rules.py) and rules CLI (scripts/rules.py)."""
import json
import os
import sys
import subprocess
import tempfile
import shutil

# Add hooks dir so we can import _rules
HOOKS_DIR = os.path.join(os.path.dirname(__file__), '..', 'hooks')
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'scripts')
sys.path.insert(0, HOOKS_DIR)

import _rules

passed = 0
failed = 0

TS = "2026-03-22T10:00:00+00:00"


def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} {detail}")


def make_proj():
    return tempfile.mkdtemp(prefix='blackbox-rules-test-')


def rules_path(tmpdir):
    return os.path.join(tmpdir, '.claude', 'sessions', 'rules.json')


# ============================================================
# record_hit — creation and defaults
# ============================================================
def test_record_hit_creates_rule():
    print("\n--- record_hit (creates rule) ---")
    tmpdir = make_proj()
    try:
        rule = _rules.record_hit(tmpdir, 'edit_without_read', TS)
        test("returns rule dict", isinstance(rule, dict))
        test("id is rule key", rule['id'] == 'edit_without_read')
        test("uses RULE_TEXTS default", rule['text'] == _rules.RULE_TEXTS['edit_without_read'])
        test("hits is 1", rule['hits'] == 1)
        test("status is candidate (<2 hits)", rule['status'] == 'candidate')
        test("last_hit_ts set", rule['last_hit_ts'] == TS)
        test("created_ts set", rule['created_ts'] == TS)
        test("sessions_since_hit is 0", rule['sessions_since_hit'] == 0)
        test("source is auto", rule['source'] == 'auto')

        # Persisted to disk
        test("rules.json written", os.path.exists(rules_path(tmpdir)))
        data = _rules.load_rules(tmpdir)
        test("store has version 1", data['version'] == 1)
        test("store has 1 rule", len(data['rules']) == 1)

        # Unknown key gets fallback text
        rule2 = _rules.record_hit(tmpdir, 'some_new_pattern', TS)
        test("fallback text for unknown key",
             rule2['text'] == 'Avoid repeating pattern: some_new_pattern.')

        # Explicit text wins
        rule3 = _rules.record_hit(tmpdir, 'custom_key', TS, text='Custom rule text.')
        test("explicit text used", rule3['text'] == 'Custom rule text.')
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# record_hit — status thresholds
# ============================================================
def test_record_hit_thresholds():
    print("\n--- record_hit (thresholds 2/4/8) ---")
    tmpdir = make_proj()
    try:
        r = _rules.record_hit(tmpdir, 'breakage', TS)
        test("1 hit -> candidate", r['status'] == 'candidate')
        r = _rules.record_hit(tmpdir, 'breakage', TS)
        test("2 hits -> watch", r['status'] == 'watch')
        r = _rules.record_hit(tmpdir, 'breakage', TS)
        test("3 hits -> still watch", r['status'] == 'watch')
        r = _rules.record_hit(tmpdir, 'breakage', TS)
        test("4 hits -> important", r['status'] == 'important')
        r = _rules.record_hit(tmpdir, 'breakage', TS, count=4)
        test("count param increments by 4", r['hits'] == 8)
        test("8 hits -> critical", r['status'] == 'critical')
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# record_hit — never demotes
# ============================================================
def test_record_hit_never_demotes():
    print("\n--- record_hit (never demotes) ---")
    tmpdir = make_proj()
    try:
        _rules.record_hit(tmpdir, 'overengineering', TS)  # 1 hit, candidate
        data = _rules.load_rules(tmpdir)
        data['rules'][0]['status'] = 'critical'  # manual promotion
        _rules.save_rules(tmpdir, data)

        r = _rules.record_hit(tmpdir, 'overengineering', TS)
        test("hit keeps manually promoted critical", r['status'] == 'critical',
             f"got {r['status']}")
        test("hits incremented to 2", r['hits'] == 2)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# record_clean_sessions
# ============================================================
def test_record_clean_sessions():
    print("\n--- record_clean_sessions ---")
    tmpdir = make_proj()
    try:
        _rules.record_hit(tmpdir, 'breakage', TS, count=2)      # watch
        _rules.record_hit(tmpdir, 'destructive_cmd', TS, count=4)  # important

        # Rule in hit_keys is NOT incremented
        _rules.record_clean_sessions(tmpdir, ['breakage'])
        data = _rules.load_rules(tmpdir)
        by_id = {r['id']: r for r in data['rules']}
        test("hit rule not incremented", by_id['breakage']['sessions_since_hit'] == 0)
        test("non-hit rule incremented", by_id['destructive_cmd']['sessions_since_hit'] == 1)

        # Watch archives at 10 clean sessions
        archived = []
        for _ in range(10):
            archived = _rules.record_clean_sessions(tmpdir, [])
        data = _rules.load_rules(tmpdir)
        by_id = {r['id']: r for r in data['rules']}
        test("watch archived at 10", by_id['breakage']['status'] == 'archived')
        test("archived id returned", 'breakage' in archived)
        test("important NOT archived at 11", by_id['destructive_cmd']['status'] == 'important')

        # Important archives at 20
        for _ in range(9):
            archived = _rules.record_clean_sessions(tmpdir, [])
        data = _rules.load_rules(tmpdir)
        by_id = {r['id']: r for r in data['rules']}
        test("important archived at 20", by_id['destructive_cmd']['status'] == 'archived')
        test("archived id returned (important)", 'destructive_cmd' in archived)

        # Archived rules are not incremented further
        before = by_id['breakage']['sessions_since_hit']
        _rules.record_clean_sessions(tmpdir, [])
        data = _rules.load_rules(tmpdir)
        by_id = {r['id']: r for r in data['rules']}
        test("archived rule not incremented", by_id['breakage']['sessions_since_hit'] == before)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# record_hit — revives archived
# ============================================================
def test_record_hit_revives_archived():
    print("\n--- record_hit (revives archived) ---")
    tmpdir = make_proj()
    try:
        _rules.record_hit(tmpdir, 'context_ignored', TS, count=4)  # important
        data = _rules.load_rules(tmpdir)
        data['rules'][0]['status'] = 'archived'
        _rules.save_rules(tmpdir, data)

        r = _rules.record_hit(tmpdir, 'context_ignored', TS)
        test("archived rule revived", r['status'] != 'archived')
        test("revived at hits-implied status (5 -> important)", r['status'] == 'important',
             f"got {r['status']}")
        test("sessions_since_hit reset", r['sessions_since_hit'] == 0)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# active_rules
# ============================================================
def test_active_rules():
    print("\n--- active_rules ---")
    tmpdir = make_proj()
    try:
        _rules.record_hit(tmpdir, 'cand_rule', TS)                 # candidate
        _rules.record_hit(tmpdir, 'watch_rule', TS, count=2)       # watch
        _rules.record_hit(tmpdir, 'imp_low', TS, count=4)          # important, 4 hits
        _rules.record_hit(tmpdir, 'imp_high', TS, count=6)         # important, 6 hits
        _rules.record_hit(tmpdir, 'crit_rule', TS, count=8)        # critical
        _rules.record_hit(tmpdir, 'arch_rule', TS, count=2)
        data = _rules.load_rules(tmpdir)
        for r in data['rules']:
            if r['id'] == 'arch_rule':
                r['status'] = 'archived'
        _rules.save_rules(tmpdir, data)

        active = _rules.active_rules(tmpdir)
        ids = [r['id'] for r in active]
        test("excludes candidate", 'cand_rule' not in ids)
        test("excludes archived", 'arch_rule' not in ids)
        test("includes watch/important/critical", set(ids) == {'watch_rule', 'imp_low', 'imp_high', 'crit_rule'})
        test("sorted critical > important > watch, ties by hits",
             ids == ['crit_rule', 'imp_high', 'imp_low', 'watch_rule'], f"got {ids}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# format_rules_context
# ============================================================
def test_format_rules_context():
    print("\n--- format_rules_context ---")
    rules = [
        {"id": "a", "text": "Never commit without running tests.", "status": "critical", "hits": 7},
        {"id": "b", "text": "Read before editing.", "status": "watch", "hits": 2},
    ]
    out = _rules.format_rules_context(rules)
    lines = out.split("\n")
    test("one line per rule", len(lines) == 2)
    test("bullet shape", lines[0] == "- [CRITICAL] Never commit without running tests. (7x)",
         f"got {lines[0]!r}")
    test("second bullet shape", lines[1] == "- [WATCH] Read before editing. (2x)")

    many = [{"id": str(i), "text": f"Rule {i}.", "status": "watch", "hits": i} for i in range(12)]
    out = _rules.format_rules_context(many)
    test("default max_rules=8 truncates", len(out.split("\n")) == 8)
    out = _rules.format_rules_context(many, max_rules=3)
    test("max_rules=3 truncates", len(out.split("\n")) == 3)
    test("empty list gives empty string", _rules.format_rules_context([]) == "")


# ============================================================
# corrupt / missing store
# ============================================================
def test_corrupt_store():
    print("\n--- load_rules (missing/corrupt) ---")
    tmpdir = make_proj()
    try:
        data = _rules.load_rules(tmpdir)
        test("missing file returns empty store", data == {"version": 1, "rules": []})

        path = rules_path(tmpdir)
        os.makedirs(os.path.dirname(path))
        with open(path, 'w', encoding='utf-8') as f:
            f.write("{not valid json!!")
        data = _rules.load_rules(tmpdir)
        test("corrupt file returns empty store", data == {"version": 1, "rules": []})

        with open(path, 'w', encoding='utf-8') as f:
            f.write('["wrong", "shape"]')
        data = _rules.load_rules(tmpdir)
        test("wrong-shape file returns empty store", data == {"version": 1, "rules": []})

        # record_hit still works on corrupt store
        with open(path, 'w', encoding='utf-8') as f:
            f.write("garbage")
        r = _rules.record_hit(tmpdir, 'breakage', TS)
        test("record_hit recovers from corrupt store", r['hits'] == 1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# CLI round-trip
# ============================================================
def run_cli(tmpdir, args):
    env = os.environ.copy()
    env['CLAUDE_PROJECT_DIR'] = tmpdir
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, 'rules.py')] + args,
        capture_output=True, timeout=10, env=env,
    )
    return result.returncode, result.stdout.decode(errors='replace'), result.stderr.decode(errors='replace')


def test_cli_roundtrip():
    print("\n--- rules.py CLI (round-trip) ---")
    tmpdir = make_proj()
    try:
        # Empty store
        code, out, err = run_cli(tmpdir, ['list'])
        test("list exits 0 on empty", code == 0, err)
        test("list says no rules yet", "No rules learned yet." in out)

        # Default command (no args) is list
        code, out, err = run_cli(tmpdir, [])
        test("no args defaults to list", code == 0 and "No rules learned yet." in out)

        # add
        code, out, err = run_cli(tmpdir, ['add', 'Always run the linter before finishing.'])
        test("add exits 0", code == 0, err)
        data = _rules.load_rules(tmpdir)
        by_id = {r['id']: r for r in data['rules']}
        test("add creates manual_1", 'manual_1' in by_id)
        if 'manual_1' in by_id:
            r = by_id['manual_1']
            test("added rule source is manual", r['source'] == 'manual')
            test("added rule status is watch", r['status'] == 'watch')
            test("added rule hits is 0", r['hits'] == 0)
            test("added rule text correct", r['text'] == 'Always run the linter before finishing.')

        # add with next default key
        run_cli(tmpdir, ['add', 'Second manual rule.'])
        data = _rules.load_rules(tmpdir)
        test("second add creates manual_2", any(r['id'] == 'manual_2' for r in data['rules']))

        # add with explicit key
        code, out, err = run_cli(tmpdir, ['add', 'Keyed rule.', '--key', 'my_key'])
        test("add --key exits 0", code == 0, err)
        data = _rules.load_rules(tmpdir)
        test("add --key uses given id", any(r['id'] == 'my_key' for r in data['rules']))

        # list shows the rules
        code, out, err = run_cli(tmpdir, ['list'])
        test("list shows STATUS header", 'STATUS' in out)
        test("list shows added rule id", 'manual_1' in out)
        test("list shows added rule text", 'Always run the linter before finishing.' in out)
        test("list shows archived footer", 'archived' in out)

        # promote
        code, out, err = run_cli(tmpdir, ['promote', 'manual_1', 'critical'])
        test("promote exits 0", code == 0, err)
        data = _rules.load_rules(tmpdir)
        by_id = {r['id']: r for r in data['rules']}
        test("promote sets critical", by_id['manual_1']['status'] == 'critical')

        code, out, err = run_cli(tmpdir, ['promote', 'manual_1', 'bogus'])
        test("promote bad status exits 1", code == 1)
        code, out, err = run_cli(tmpdir, ['promote', 'no_such_rule', 'watch'])
        test("promote unknown id exits 1", code == 1)

        # archive
        code, out, err = run_cli(tmpdir, ['archive', 'manual_2'])
        test("archive exits 0", code == 0, err)
        data = _rules.load_rules(tmpdir)
        by_id = {r['id']: r for r in data['rules']}
        test("archive sets archived", by_id['manual_2']['status'] == 'archived')

        code, out, err = run_cli(tmpdir, ['archive', 'no_such_rule'])
        test("archive unknown id exits 1", code == 1)

        # list hides archived, list --all shows it
        code, out, err = run_cli(tmpdir, ['list'])
        test("list hides archived rule", 'manual_2' not in out)
        test("footer counts 1 archived", '1 archived' in out)
        code, out, err = run_cli(tmpdir, ['list', '--all'])
        test("list --all shows archived rule", 'manual_2' in out)

        # unknown command
        code, out, err = run_cli(tmpdir, ['frobnicate'])
        test("unknown command exits 1", code == 1)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    print("blackbox rules test suite")
    print("=========================")

    test_record_hit_creates_rule()
    test_record_hit_thresholds()
    test_record_hit_never_demotes()
    test_record_clean_sessions()
    test_record_hit_revives_archived()
    test_active_rules()
    test_format_rules_context()
    test_corrupt_store()
    test_cli_roundtrip()

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*40}")

    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
