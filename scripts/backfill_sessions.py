#!/usr/bin/env python3
"""
Backfill session logs from Claude Code transcript history.

Reads .jsonl session transcripts from ~/.claude/projects/<project>/,
analyzes them for failure signals, and writes retro-session JSONL logs
to the target project's .claude/sessions/ directory.

Usage:
    python scripts/backfill_sessions.py                           # List projects
    python scripts/backfill_sessions.py <project-key>             # Backfill
    python scripts/backfill_sessions.py <project-key> --product MyApp
    python scripts/backfill_sessions.py <project-key> --output-dir .claude/sessions
"""

import json
import os
import re
import sys
import glob
from datetime import datetime
from pathlib import Path
from collections import Counter

# Fix Windows console encoding
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CLAUDE_DIR = os.path.expanduser("~/.claude/projects")

# Patterns that indicate user corrections.
# Each pattern is tested against the full user message (lowercased).
# Only strong, unambiguous signals are included to minimize false positives.
CORRECTION_PATTERNS = [
    # Explicit rejection of Claude's output
    (r'\bno[,.]?\s+(not |don\'t |stop |that\'s wrong|that\'s not)', 'explicit_no'),
    (r'\bthat\'s wrong\b', 'wrong'),
    (r'\bthat\'s not (right|correct|what)\b', 'not_right'),
    (r'\bnot that\b', 'not_that'),
    # Undo/revert requests (require object to reduce false positives)
    (r'\bundo (that|this|it|the)\b', 'undo'),
    (r'\brevert (that|this|it|the)\b', 'revert'),
    # Direct behavioral corrections
    (r'\bdon\'t do that\b', 'dont_do'),
    (r'\bstop (doing|adding|changing|making|it)\b', 'stop_doing'),
    (r'\bthat\'s not what i\b', 'not_what_i_wanted'),
    (r'\bstart over\b', 'start_over'),
    # Breakage signals
    (r'\byou broke\b', 'you_broke'),
    (r'\bthat broke\b', 'that_broke'),
    # Context/listening failures
    (r'\bwhy did you\b', 'why_did_you'),
    (r'\bi (already )?(said|told|asked)\b', 'i_said'),
    # Overengineering signals
    (r'\btoo complex\b', 'too_complex'),
    (r'\bover.?engineer', 'overengineered'),
    (r'\bsimpler\b', 'simpler'),
    (r'\bjust do\b', 'just_do'),
    # Interruptions (Claude Code specific)
    (r'\bRequest interrupted by user\b', 'interrupted'),
]

# Patterns in tool results/assistant messages that indicate errors caused by Claude.
# Intentionally conservative — only matches unambiguous error indicators.
ERROR_PATTERNS = [
    (r'Exit code [1-9]', 'nonzero_exit'),
    (r'TypeError:', 'type_error'),
    (r'SyntaxError:', 'syntax_error'),
    (r'ReferenceError:', 'reference_error'),
    (r'ModuleNotFoundError:', 'module_not_found'),
    (r'Cannot find module', 'module_not_found'),
    (r'ENOENT:', 'file_not_found'),
    (r'ECONNREFUSED', 'connection_error'),
    (r'compilation failed', 'build_error'),
    (r'Build error', 'build_error'),
]

# Patterns indicating the user redirected the approach
APPROACH_PATTERNS = [
    (r'\bactually\b.*\binstead\b', 'approach_change'),
    (r'\blet\'s try\b.*\bdifferent\b', 'approach_change'),
    (r'\bforget that\b', 'approach_change'),
    (r'\bscrap\b', 'approach_change'),
    (r'\bchange of plan\b', 'approach_change'),
    (r'\bnever\s?mind\b', 'approach_change'),
]


def derive_product_name(project_key):
    """Derive a human-readable product name from the project key.

    Project keys look like 'C--Users-cgall-OneDrive-Desktop-Dev-adminpanelnew'
    or 'E--Dev2-CMO-Agent-System'. We take the last segment.
    """
    parts = project_key.replace('\\', '-').replace('/', '-').split('-')
    # Filter out empty strings and drive letters
    parts = [p for p in parts if p and len(p) > 1]
    if parts:
        return parts[-1]
    return project_key[:20]


def extract_text(content):
    """Extract text from a message content field (string or content blocks list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
                elif block.get('type') == 'tool_result':
                    result_content = block.get('content', '')
                    if isinstance(result_content, str):
                        text_parts.append(result_content)
            elif isinstance(block, str):
                text_parts.append(block)
        return ' '.join(text_parts)
    return str(content) if content else ''


def parse_session(filepath):
    """Parse a single session transcript .jsonl file."""
    events = []
    session_id = Path(filepath).stem

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"  Error reading {filepath}: {e}", file=sys.stderr)
        return None

    return {'session_id': session_id, 'events': events} if events else None


def analyze_session(session_data):
    """Analyze a parsed session for failure signals."""
    events = session_data['events']
    session_id = session_data['session_id']

    first_ts = None
    last_ts = None
    branch = None
    tool_errors = []
    user_corrections = []
    approach_changes = []
    interruptions = 0
    total_user_msgs = 0

    for entry in events:
        ts = entry.get('timestamp')
        if ts and not first_ts:
            first_ts = ts
        if ts:
            last_ts = ts

        if not branch and entry.get('gitBranch'):
            branch = entry['gitBranch']

        entry_type = entry.get('type', '')
        message = entry.get('message', {})

        if not isinstance(message, dict):
            continue

        role = message.get('role', '')
        content = extract_text(message.get('content', ''))

        if role == 'user' and entry_type == 'user':
            total_user_msgs += 1
            content_lower = content.lower()

            # Check for corrections (one per message, first match wins)
            for pattern, label in CORRECTION_PATTERNS:
                if re.search(pattern, content_lower):
                    if label == 'interrupted':
                        interruptions += 1
                    else:
                        user_corrections.append({
                            'ts': ts,
                            'type': label,
                            'snippet': content[:200],
                        })
                    break

            # Check for approach changes
            for pattern, label in APPROACH_PATTERNS:
                if re.search(pattern, content_lower):
                    approach_changes.append({
                        'ts': ts, 'type': label, 'snippet': content[:200],
                    })
                    break

        elif role == 'assistant':
            for pattern, label in ERROR_PATTERNS:
                if re.search(pattern, content):
                    tool_errors.append({
                        'ts': ts, 'type': label, 'snippet': content[:200],
                    })
                    break

    if not first_ts:
        return None

    # Score the session based on objective signals
    breakage = sum(1 for c in user_corrections if c['type'] in
                   ('you_broke', 'that_broke', 'revert', 'undo'))
    accuracy = max(1, min(10, 10 - (breakage * 2) - (len(tool_errors) * 0.5)))

    overeng = sum(1 for c in user_corrections if c['type'] in
                  ('overengineered', 'too_complex', 'simpler', 'just_do', 'start_over'))
    efficiency = max(1, min(10, 10 - (len(approach_changes) * 1.5)
                            - (interruptions * 0.5) - (overeng * 2)))

    context_fails = sum(1 for c in user_corrections if c['type'] in
                        ('i_said', 'why_did_you'))
    context = max(1, min(10, 10 - (context_fails * 2.5)))

    composite = round((accuracy * 0.4) + (efficiency * 0.3) + (context * 0.3), 1)

    return {
        'session_id': session_id,
        'first_ts': first_ts,
        'last_ts': last_ts,
        'branch': branch,
        'total_user_msgs': total_user_msgs,
        'user_corrections': user_corrections,
        'tool_errors': tool_errors[:10],
        'approach_changes': approach_changes,
        'interruptions': interruptions,
        'scores': {
            'accuracy': round(accuracy, 1),
            'efficiency': round(efficiency, 1),
            'context': round(context, 1),
            'composite': composite,
        },
    }


def write_session_log(analysis, output_dir, product_name):
    """Write a retro-session JSONL log from analysis results."""
    ts = analysis['first_ts']
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        filename = dt.strftime('%Y-%m-%d-%H%M%S') + '.jsonl'
    except Exception:
        filename = f"backfill-{analysis['session_id'][:8]}.jsonl"

    filepath = os.path.join(output_dir, filename)
    lines = []

    lines.append(json.dumps({
        'type': 'session_start',
        'ts': analysis['first_ts'],
        'product': product_name,
        'branch': analysis['branch'] or 'unknown',
        'task_summary': f'Backfilled from transcript {analysis["session_id"][:8]}',
        'backfilled': True,
    }))

    for corr in analysis['user_corrections']:
        lines.append(json.dumps({
            'type': 'user_correction',
            'ts': corr['ts'],
            'what': corr['type'],
            'context': corr['snippet'][:150],
        }))

    for err in analysis['tool_errors'][:5]:
        lines.append(json.dumps({
            'type': 'error',
            'ts': err['ts'],
            'command': 'unknown',
            'error': err['snippet'][:150],
            'was_my_fault': True,
        }))

    for ac in analysis['approach_changes']:
        lines.append(json.dumps({
            'type': 'approach_change',
            'ts': ac['ts'],
            'from': 'unknown',
            'to': 'unknown',
            'reason': ac['snippet'][:150],
        }))

    lines.append(json.dumps({
        'type': 'session_end',
        'ts': analysis['last_ts'],
        'scores': analysis['scores'],
        'user_messages': analysis['total_user_msgs'],
        'user_corrections': len(analysis['user_corrections']),
        'errors': len(analysis['tool_errors']),
        'interruptions': analysis['interruptions'],
        'backfilled': True,
    }))

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')

    return filepath


def main():
    if len(sys.argv) < 2:
        print("Usage: python backfill_sessions.py <project-key> [--product NAME] [--output-dir DIR]")
        print("\nAvailable projects:")
        for d in sorted(os.listdir(CLAUDE_DIR)):
            jsonl_count = len(glob.glob(os.path.join(CLAUDE_DIR, d, '*.jsonl')))
            if jsonl_count > 0:
                print(f"  {d} ({jsonl_count} sessions)")
        sys.exit(1)

    project_key = sys.argv[1]
    project_dir = os.path.join(CLAUDE_DIR, project_key)

    # Parse optional args
    output_dir = None
    product_name = None
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == '--output-dir' and i + 1 < len(args):
            output_dir = args[i + 1]
            i += 2
        elif args[i] == '--product' and i + 1 < len(args):
            product_name = args[i + 1]
            i += 2
        else:
            i += 1

    if not output_dir:
        output_dir = os.path.join(os.getcwd(), '.claude', 'sessions')
    if not product_name:
        product_name = derive_product_name(project_key)

    os.makedirs(output_dir, exist_ok=True)

    if not os.path.isdir(project_dir):
        print(f"Error: Project directory not found: {project_dir}")
        sys.exit(1)

    transcript_files = sorted(glob.glob(os.path.join(project_dir, '*.jsonl')))
    print(f"Found {len(transcript_files)} session transcripts in {project_key}")
    print(f"Product name: {product_name}")
    print(f"Output directory: {output_dir}")
    print()

    all_analyses = []
    correction_types = Counter()
    error_types = Counter()

    for i, filepath in enumerate(transcript_files):
        session_data = parse_session(filepath)
        if not session_data:
            continue

        analysis = analyze_session(session_data)
        if not analysis:
            continue

        all_analyses.append(analysis)

        for corr in analysis['user_corrections']:
            correction_types[corr['type']] += 1
        for err in analysis['tool_errors']:
            error_types[err['type']] += 1

        write_session_log(analysis, output_dir, product_name)

        score = analysis['scores']['composite']
        corrs = len(analysis['user_corrections'])
        errs = len(analysis['tool_errors'])
        marker = ' !!!' if score < 5 else (' !' if score < 7 else '')

        if (i + 1) % 10 == 0 or score < 5:
            print(f"  [{i+1}/{len(transcript_files)}] {analysis['session_id'][:8]}... "
                  f"score={score} corrections={corrs} errors={errs}{marker}")

    print(f"\n{'='*60}")
    print(f"BACKFILL COMPLETE")
    print(f"{'='*60}")
    print(f"Sessions processed: {len(all_analyses)}")
    print(f"Session logs written to: {output_dir}")

    if all_analyses:
        avg = lambda key: sum(a['scores'][key] for a in all_analyses) / len(all_analyses)
        print(f"\nAvg Composite Score: {avg('composite'):.1f}/10")
        print(f"  Accuracy:   {avg('accuracy'):.1f}")
        print(f"  Efficiency: {avg('efficiency'):.1f}")
        print(f"  Context:    {avg('context'):.1f}")

        low = sum(1 for a in all_analyses if a['scores']['composite'] < 7)
        vlow = sum(1 for a in all_analyses if a['scores']['composite'] < 5)
        print(f"\nSessions scoring < 7: {low}/{len(all_analyses)}")
        print(f"Sessions scoring < 5: {vlow}/{len(all_analyses)}")

        if correction_types:
            print(f"\nTop Correction Types:")
            for ctype, count in correction_types.most_common(10):
                print(f"  {ctype}: {count}x")

        if error_types:
            print(f"\nTop Error Types:")
            for etype, count in error_types.most_common(10):
                print(f"  {etype}: {count}x")

        worst = sorted(all_analyses, key=lambda a: a['scores']['composite'])[:5]
        if worst:
            print(f"\nWorst 5 Sessions:")
            for w in worst:
                print(f"  {w['session_id'][:8]}... score={w['scores']['composite']} "
                      f"corrections={len(w['user_corrections'])} "
                      f"errors={len(w['tool_errors'])} "
                      f"branch={w['branch'] or '?'}")


if __name__ == '__main__':
    main()
