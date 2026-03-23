#!/usr/bin/env python3
"""
Session Audit Report — Human-readable analysis of Claude's development sessions.

Provides:
1. Ground truth signals (git reverts, test failures) vs self-reported scores
2. Score calibration — is Claude inflating?
3. Rule compliance evidence — did Claude read before write?
4. Trend analysis — improving or getting worse?

Usage:
    python scripts/audit_sessions.py                    # Full report
    python scripts/audit_sessions.py --last 7           # Last 7 days
    python scripts/audit_sessions.py --worst 5          # 5 worst sessions
    python scripts/audit_sessions.py --product KaiCalls # Filter by product
"""

import json
import os
import sys
import glob
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict

# Fix Windows console encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.claude', 'sessions')


def load_sessions(sessions_dir=SESSIONS_DIR, last_days=None, product=None):
    """Load and parse all session JSONL files."""
    files = sorted(glob.glob(os.path.join(sessions_dir, '*.jsonl')))
    if not files:
        print("No session logs found. Run /retro-session after sessions or backfill with:")
        print("  python scripts/backfill_sessions.py <project-key>")
        return []

    sessions = []
    for fp in files:
        session = {'file': os.path.basename(fp), 'events': []}
        with open(fp, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    session['events'].append(json.loads(line.strip()))
                except:
                    continue

        # Extract metadata from events
        for e in session['events']:
            if e.get('type') == 'session_start':
                session['product'] = e.get('product', 'unknown')
                session['branch'] = e.get('branch', '?')
                session['start_ts'] = e.get('ts', '')
                session['backfilled'] = e.get('backfilled', False)
                session['task'] = e.get('task_summary', '')
            elif e.get('type') == 'session_end':
                session['scores'] = e.get('scores', {})
                session['end_ts'] = e.get('ts', '')
                session['corrections'] = e.get('user_corrections', 0)
                session['errors'] = e.get('errors', 0)
                session['interruptions'] = e.get('interruptions', 0)

        if 'scores' not in session:
            continue

        # Filter by date
        if last_days and session.get('start_ts'):
            try:
                ts = datetime.fromisoformat(session['start_ts'].replace('Z', '+00:00'))
                cutoff = datetime.now(timezone.utc) - timedelta(days=last_days)
                if ts < cutoff:
                    continue
            except:
                pass

        # Filter by product
        if product and session.get('product', '').lower() != product.lower():
            continue

        sessions.append(session)

    return sessions


def score_histogram(sessions):
    """Show distribution of scores."""
    buckets = {'1-3 (bad)': 0, '4-5 (poor)': 0, '6-7 (ok)': 0, '8-9 (good)': 0, '10 (perfect)': 0}
    for s in sessions:
        c = s['scores'].get('composite', 10)
        if c <= 3: buckets['1-3 (bad)'] += 1
        elif c <= 5: buckets['4-5 (poor)'] += 1
        elif c <= 7: buckets['6-7 (ok)'] += 1
        elif c <= 9: buckets['8-9 (good)'] += 1
        else: buckets['10 (perfect)'] += 1
    return buckets


def correction_analysis(sessions):
    """Analyze correction types across sessions."""
    types = Counter()
    contexts = []
    for s in sessions:
        for e in s['events']:
            if e.get('type') == 'user_correction':
                types[e.get('what', 'unknown')] += 1
                ctx = e.get('context', '')
                if ctx and len(ctx) > 20:
                    contexts.append((e.get('what', ''), ctx[:120]))
    return types, contexts


def error_analysis(sessions):
    """Analyze error types across sessions."""
    types = Counter()
    for s in sessions:
        for e in s['events']:
            if e.get('type') == 'error' and e.get('was_my_fault'):
                err = e.get('error', '')[:60]
                types[err] += 1
    return types


def calibration_check(sessions):
    """Check if self-reported scores are calibrated against objective signals.

    A session with corrections should NOT have a perfect score.
    A session with errors should NOT have accuracy=10.
    """
    miscalibrated = []
    for s in sessions:
        scores = s.get('scores', {})
        corrections = s.get('corrections', 0)
        errors = s.get('errors', 0)
        composite = scores.get('composite', 0)

        issues = []
        if corrections >= 3 and composite >= 9:
            issues.append(f"composite={composite} but {corrections} corrections")
        if errors >= 3 and scores.get('accuracy', 0) >= 9:
            issues.append(f"accuracy={scores['accuracy']} but {errors} errors")
        if corrections >= 2 and scores.get('context', 0) >= 9.5:
            issues.append(f"context={scores['context']} but {corrections} corrections")

        if issues:
            miscalibrated.append({
                'file': s['file'],
                'product': s.get('product', '?'),
                'issues': issues,
                'scores': scores,
            })
    return miscalibrated


def trend_analysis(sessions):
    """Analyze score trends over time (weekly buckets)."""
    by_week = defaultdict(list)
    for s in sessions:
        ts = s.get('start_ts', '')
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            week = dt.strftime('%Y-W%W')
            by_week[week].append(s['scores'].get('composite', 0))
        except:
            continue

    trends = {}
    for week in sorted(by_week.keys()):
        scores = by_week[week]
        trends[week] = {
            'count': len(scores),
            'avg': sum(scores) / len(scores) if scores else 0,
            'min': min(scores) if scores else 0,
        }
    return trends


def load_compliance(sessions_dir):
    """Load compliance data from .claude/sessions/compliance.jsonl.

    Returns aggregate counts across all sessions:
    - edit_total / edit_no_read: edits tracked vs those without a prior Read
    - commit_total / commit_no_test: commits tracked vs those without prior tests
    - safety_total: destructive commands caught by safety hooks
    - session_summaries: list of per-session summary dicts for trending
    """
    compliance_file = os.path.join(sessions_dir, 'compliance.jsonl')
    result = {
        'edit_total': 0,
        'edit_no_read': 0,
        'commit_total': 0,
        'commit_no_test': 0,
        'safety_total': 0,
        'session_summaries': [],
    }

    if not os.path.exists(compliance_file):
        return result

    try:
        with open(compliance_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                t = entry.get('type')
                if t == 'edit_compliance':
                    result['edit_total'] += 1
                    if not entry.get('was_read_first'):
                        result['edit_no_read'] += 1
                elif t == 'commit_compliance':
                    result['commit_total'] += 1
                    if not entry.get('tests_ran_first'):
                        result['commit_no_test'] += 1
                elif t == 'safety_trigger':
                    result['safety_total'] += 1
                elif t == 'session_summary':
                    result['session_summaries'].append(entry)
    except Exception:
        pass

    return result


def print_report(sessions, title="Session Audit Report"):
    """Print full human-readable report."""
    print(f"\n{'='*64}")
    print(f"  {title}")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*64}\n")

    if not sessions:
        print("No sessions to analyze.")
        return

    # Overview
    backfilled = sum(1 for s in sessions if s.get('backfilled'))
    live = len(sessions) - backfilled
    products = Counter(s.get('product', '?') for s in sessions)

    print(f"  Sessions: {len(sessions)} total ({live} live, {backfilled} backfilled)")
    print(f"  Products: {', '.join(f'{p} ({c})' for p, c in products.most_common())}")

    if sessions[0].get('start_ts') and sessions[-1].get('start_ts'):
        print(f"  Period:   {sessions[0]['start_ts'][:10]} to {sessions[-1]['start_ts'][:10]}")

    # Score summary
    print(f"\n--- SCORES {'-'*52}")
    all_comp = [s['scores']['composite'] for s in sessions if 'composite' in s['scores']]
    all_acc = [s['scores']['accuracy'] for s in sessions if 'accuracy' in s['scores']]
    all_eff = [s['scores']['efficiency'] for s in sessions if 'efficiency' in s['scores']]
    all_ctx = [s['scores']['context'] for s in sessions if 'context' in s['scores']]

    if all_comp:
        print(f"  Composite:  {sum(all_comp)/len(all_comp):.1f} avg  (min: {min(all_comp):.1f}, max: {max(all_comp):.1f})")
        print(f"  Accuracy:   {sum(all_acc)/len(all_acc):.1f} avg")
        print(f"  Efficiency: {sum(all_eff)/len(all_eff):.1f} avg")
        print(f"  Context:    {sum(all_ctx)/len(all_ctx):.1f} avg")

    # Histogram
    hist = score_histogram(sessions)
    print(f"\n  Distribution:")
    for bucket, count in hist.items():
        bar = '#' * count
        pct = (count / len(sessions) * 100) if sessions else 0
        if count > 0:
            print(f"    {bucket:14s} | {bar:<30s} {count} ({pct:.0f}%)")

    # Calibration check
    print(f"\n--- CALIBRATION CHECK {'-'*42}")
    miscal = calibration_check(sessions)
    if miscal:
        print(f"  WARNING: {len(miscal)} sessions may have inflated scores:")
        for m in miscal[:5]:
            print(f"    {m['file'][:30]} [{m['product']}]")
            for issue in m['issues']:
                print(f"      - {issue}")
    else:
        print(f"  OK: No obvious score inflation detected.")

    # Corrections
    print(f"\n--- USER CORRECTIONS {'-'*43}")
    corr_types, corr_contexts = correction_analysis(sessions)
    total_corr = sum(corr_types.values())
    print(f"  Total: {total_corr} corrections across {len(sessions)} sessions")
    if corr_types:
        print(f"\n  By type:")
        for ct, count in corr_types.most_common(10):
            pct = count / total_corr * 100
            print(f"    {ct:25s} {count:3d}x ({pct:.0f}%)")

    if corr_contexts:
        print(f"\n  Sample contexts (what the user actually said):")
        seen = set()
        for ctype, ctx in corr_contexts[:8]:
            if ctx not in seen:
                print(f"    [{ctype}] \"{ctx}\"")
                seen.add(ctx)

    # Errors
    print(f"\n--- ERRORS {'-'*53}")
    err_types = error_analysis(sessions)
    total_err = sum(err_types.values())
    print(f"  Total: {total_err} errors (Claude's fault)")
    if err_types:
        print(f"\n  By type:")
        for et, count in err_types.most_common(8):
            print(f"    [{count:2d}x] {et}")

    # Trends
    print(f"\n--- WEEKLY TRENDS {'-'*46}")
    trends = trend_analysis(sessions)
    if trends:
        for week, data in trends.items():
            bar = '#' * int(data['avg'])
            print(f"  {week}: avg={data['avg']:.1f} min={data['min']:.1f} sessions={data['count']:3d}  {bar}")
    else:
        print(f"  Not enough data for trends yet.")

    # Worst sessions
    print(f"\n--- WORST SESSIONS {'-'*45}")
    worst = sorted(sessions, key=lambda s: s['scores'].get('composite', 10))[:5]
    for w in worst:
        sc = w['scores']
        print(f"  {w['file'][:30]} score={sc.get('composite','?'):4} "
              f"acc={sc.get('accuracy','?')} eff={sc.get('efficiency','?')} ctx={sc.get('context','?')} "
              f"corr={w.get('corrections',0)} err={w.get('errors',0)} "
              f"[{w.get('product','?')}]")

    # Rule compliance (from ground truth hooks in .claude/hooks/)
    print(f"\n--- RULE COMPLIANCE {'-'*44}")
    compliance = load_compliance(SESSIONS_DIR)
    if compliance['edit_total'] == 0 and compliance['commit_total'] == 0 and compliance['safety_total'] == 0:
        print(f"  No compliance data yet. Hooks will populate after next session.")
    else:
        # Edit compliance
        if compliance['edit_total'] > 0:
            e_ok = compliance['edit_total'] - compliance['edit_no_read']
            e_pct = (e_ok / compliance['edit_total'] * 100)
            bar = '#' * int(e_pct / 5)
            print(f"  Edits read first:       {e_ok}/{compliance['edit_total']} ({e_pct:.0f}%) {bar}")
            if compliance['edit_no_read'] > 0:
                print(f"    WARNING: {compliance['edit_no_read']} edit(s) without reading the file first")
        else:
            print(f"  Edits read first:       no edits tracked yet")

        # Commit compliance
        if compliance['commit_total'] > 0:
            c_ok = compliance['commit_total'] - compliance['commit_no_test']
            c_pct = (c_ok / compliance['commit_total'] * 100)
            bar = '#' * int(c_pct / 5)
            print(f"  Commits with tests:     {c_ok}/{compliance['commit_total']} ({c_pct:.0f}%) {bar}")
            if compliance['commit_no_test'] > 0:
                print(f"    WARNING: {compliance['commit_no_test']} commit(s) without running tests first")
        else:
            print(f"  Commits with tests:     no commits tracked yet")

        # Safety triggers
        print(f"  Safety triggers:        {compliance['safety_total']} destructive command(s) caught")

        # Trending compliance (from session summaries)
        if compliance['session_summaries']:
            print(f"\n  Session compliance trend (last {min(10, len(compliance['session_summaries']))}):")
            for s in compliance['session_summaries'][-10:]:
                ts = s.get('ts', '?')[:16]
                e_t = s.get('edits_total', 0)
                e_nr = s.get('edits_without_read', 0)
                c_t = s.get('commits_total', 0)
                c_nt = s.get('commits_without_test', 0)
                sf = s.get('safety_triggers', 0)
                e_pct_s = s.get('edit_compliance_pct')
                c_pct_s = s.get('commit_compliance_pct')
                e_str = f"edits:{e_t-e_nr}/{e_t}({e_pct_s:.0f}%)" if e_pct_s is not None else f"edits:0"
                c_str = f"commits:{c_t-c_nt}/{c_t}({c_pct_s:.0f}%)" if c_pct_s is not None else f"commits:0"
                print(f"    {ts}  {e_str:22s} {c_str:24s} safety:{sf}")

    print(f"\n{'='*64}")
    print(f"  Run: python scripts/audit_sessions.py --last 7    (recent only)")
    print(f"  Run: python scripts/audit_sessions.py --worst 10  (worst N)")
    print(f"{'='*64}\n")


def main():
    last_days = None
    product = None
    worst_n = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--last' and i + 1 < len(args):
            last_days = int(args[i + 1])
            i += 2
        elif args[i] == '--product' and i + 1 < len(args):
            product = args[i + 1]
            i += 2
        elif args[i] == '--worst' and i + 1 < len(args):
            worst_n = int(args[i + 1])
            i += 2
        elif args[i] in ('-h', '--help'):
            print(__doc__)
            sys.exit(0)
        else:
            i += 1

    sessions = load_sessions(last_days=last_days, product=product)

    if worst_n:
        sessions = sorted(sessions, key=lambda s: s.get('scores', {}).get('composite', 10))[:worst_n]
        print_report(sessions, title=f"Worst {worst_n} Sessions")
    else:
        title = "Session Audit Report"
        if last_days:
            title += f" (Last {last_days} days)"
        if product:
            title += f" — {product}"
        print_report(sessions, title=title)


if __name__ == '__main__':
    main()
