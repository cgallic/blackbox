#!/usr/bin/env python3
"""
Backfill session logs from Claude Code transcript history.

Reads .jsonl session transcripts from ~/.claude/projects/<project>/,
analyzes them for failure signals, and writes retro-session JSONL logs
to the target project's .claude/sessions/ directory.

Usage:
    python scripts/backfill_sessions.py <project-key> [--output-dir <dir>]

Example:
    python scripts/backfill_sessions.py C--Users-cgall-OneDrive-Desktop-Dev-adminpanelnew
    python scripts/backfill_sessions.py E--Dev2-CMO-Agent-System --output-dir .claude/sessions
"""

import json
import os
import re
import sys
import glob
from datetime import datetime
from pathlib import Path
from collections import Counter

CLAUDE_DIR = os.path.expanduser("~/.claude/projects")

# Patterns that indicate user corrections
CORRECTION_PATTERNS = [
    # Strong signals — user explicitly correcting Claude
    (r'\bno[,.]?\s+(not |don\'t |stop |that\'s wrong|that\'s not)', 'explicit_no'),
    (r'\bthat\'s wrong\b', 'wrong'),
    (r'\bthat\'s not (right|correct|what)\b', 'not_right'),
    (r'\bnot that\b', 'not_that'),
    (r'\bundo (that|this|it)\b', 'undo'),
    (r'\brevert (that|this|it|the)\b', 'revert'),
    (r'\bdon\'t do that\b', 'dont_do'),
    (r'\bstop (doing|adding|changing|making|it)\b', 'stop_doing'),
    (r'\bthat\'s not what i\b', 'not_what_i_wanted'),
    (r'\bstart over\b', 'start_over'),
    (r'\byou broke\b', 'you_broke'),
    (r'\bthat broke\b', 'that_broke'),
    (r'\bwhy did you\b', 'why_did_you'),
    (r'\bi (already )?(said|told|asked)\b', 'i_said'),
    (r'\btoo complex\b', 'too_complex'),
    (r'\bover.?engineer', 'overengineered'),
    (r'\bsimpler\b', 'simpler'),
    (r'\bjust do\b', 'just_do'),
    (r'\byou suck\b', 'frustration'),
    (r'\bRequest interrupted by user\b', 'interrupted'),
]

# Patterns in tool results that indicate errors
ERROR_PATTERNS = [
    (r'Error:', 'error'),
    (r'error:', 'error'),
    (r'ENOENT', 'file_not_found'),
    (r'TypeError', 'type_error'),
    (r'SyntaxError', 'syntax_error'),
    (r'ReferenceError', 'reference_error'),
    (r'ECONNREFUSED', 'connection_error'),
    (r'Exit code [1-9]', 'nonzero_exit'),
    (r'ModuleNotFoundError', 'module_not_found'),
    (r'Cannot find module', 'module_not_found'),
    (r'compilation failed', 'build_error'),
    (r'Build error', 'build_error'),
    (r'FAILED', 'test_failure'),
    (r'failed', 'test_failure'),
]

# Patterns indicating approach changes
APPROACH_PATTERNS = [
    (r'\bactually\b.*\binstead\b', 'approach_change'),
    (r'\blet\'s try\b.*\bdifferent\b', 'approach_change'),
    (r'\bforget that\b', 'approach_change'),
    (r'\bscrap\b', 'approach_change'),
    (r'\bchange of plan\b', 'approach_change'),
    (r'\bnever\s?mind\b', 'approach_change'),
]


def parse_session(filepath):
    """Parse a single session transcript .jsonl file."""
    events = []
    session_id = Path(filepath).stem

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            for line_num, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    events.append(entry)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"  Error reading {filepath}: {e}", file=sys.stderr)
        return None

    if not events:
        return None

    return {
        'session_id': session_id,
        'events': events,
        'filepath': filepath,
    }


def analyze_session(session_data):
    """Analyze a parsed session for failure signals."""
    events = session_data['events']
    session_id = session_data['session_id']

    # Extract metadata
    first_ts = None
    last_ts = None
    branch = None
    user_messages = []
    assistant_messages = []
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

        if isinstance(message, dict):
            role = message.get('role', '')
            content = message.get('content', '')

            # Handle content that's a list of content blocks
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
                content = ' '.join(text_parts)

            if not isinstance(content, str):
                content = str(content) if content else ''

            if role == 'user' and entry_type == 'user':
                total_user_msgs += 1
                user_messages.append({'ts': ts, 'content': content[:500]})

                # Check for corrections
                content_lower = content.lower()
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
                        break  # One correction per message

                # Check for approach changes
                for pattern, label in APPROACH_PATTERNS:
                    if re.search(pattern, content_lower):
                        approach_changes.append({
                            'ts': ts,
                            'type': label,
                            'snippet': content[:200],
                        })
                        break

            elif role == 'assistant':
                assistant_messages.append({'ts': ts, 'content': content[:200]})

                # Check for tool errors in assistant messages that contain tool results
                for pattern, label in ERROR_PATTERNS:
                    if re.search(pattern, content):
                        tool_errors.append({
                            'ts': ts,
                            'type': label,
                            'snippet': content[:200],
                        })
                        break

        # Also check tool_result type entries
        if entry_type == 'tool_result' or entry.get('type') == 'tool_result':
            result = entry.get('content', '') or entry.get('output', '') or ''
            if isinstance(result, list):
                result = ' '.join(str(r) for r in result)
            if isinstance(result, str):
                for pattern, label in ERROR_PATTERNS:
                    if re.search(pattern, result):
                        tool_errors.append({
                            'ts': ts or last_ts,
                            'type': label,
                            'snippet': result[:200],
                        })
                        break

    if not first_ts:
        return None

    # Score the session
    correction_count = len(user_corrections)
    error_count = len(tool_errors)
    approach_count = len(approach_changes)

    # Accuracy: penalized by errors and corrections that indicate breakage
    breakage_corrections = sum(1 for c in user_corrections if c['type'] in
                              ('you_broke', 'that_broke', 'revert', 'undo'))
    accuracy = max(1, 10 - (breakage_corrections * 2) - (error_count * 0.5))
    accuracy = min(10, accuracy)

    # Efficiency: penalized by approach changes, interruptions, and "just do" / "simpler" corrections
    efficiency_corrections = sum(1 for c in user_corrections if c['type'] in
                                ('overengineered', 'too_complex', 'simpler', 'just_do', 'start_over'))
    efficiency = max(1, 10 - (approach_count * 1.5) - (interruptions * 0.5) - (efficiency_corrections * 2))
    efficiency = min(10, efficiency)

    # Context: penalized by "I said", "already told", "why did you" corrections
    context_corrections = sum(1 for c in user_corrections if c['type'] in
                             ('i_said', 'already_told', 'why_did_you', 'shouldnt'))
    context = max(1, 10 - (context_corrections * 2.5))
    context = min(10, context)

    composite = round((accuracy * 0.4) + (efficiency * 0.3) + (context * 0.3), 1)

    return {
        'session_id': session_id,
        'first_ts': first_ts,
        'last_ts': last_ts,
        'branch': branch,
        'total_user_msgs': total_user_msgs,
        'user_corrections': user_corrections,
        'tool_errors': tool_errors[:10],  # Cap at 10
        'approach_changes': approach_changes,
        'interruptions': interruptions,
        'scores': {
            'accuracy': round(accuracy, 1),
            'efficiency': round(efficiency, 1),
            'context': round(context, 1),
            'composite': composite,
        },
    }


def write_session_log(analysis, output_dir):
    """Write a retro-session JSONL log from analysis results."""
    ts = analysis['first_ts']
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        filename = dt.strftime('%Y-%m-%d-%H%M%S') + '.jsonl'
    except:
        filename = f"backfill-{analysis['session_id'][:8]}.jsonl"

    filepath = os.path.join(output_dir, filename)

    lines = []

    # Session start
    lines.append(json.dumps({
        'type': 'session_start',
        'ts': analysis['first_ts'],
        'product': 'KaiCalls',
        'branch': analysis['branch'] or 'unknown',
        'task_summary': f'Backfilled from transcript {analysis["session_id"][:8]}',
        'backfilled': True,
    }))

    # User corrections
    for corr in analysis['user_corrections']:
        lines.append(json.dumps({
            'type': 'user_correction',
            'ts': corr['ts'],
            'what': corr['type'],
            'context': corr['snippet'][:150],
        }))

    # Errors
    for err in analysis['tool_errors'][:5]:
        lines.append(json.dumps({
            'type': 'error',
            'ts': err['ts'],
            'command': 'unknown',
            'error': err['snippet'][:150],
            'was_my_fault': True,
        }))

    # Approach changes
    for ac in analysis['approach_changes']:
        lines.append(json.dumps({
            'type': 'approach_change',
            'ts': ac['ts'],
            'from': 'unknown',
            'to': 'unknown',
            'reason': ac['snippet'][:150],
        }))

    # Session end
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
        print("Usage: python backfill_sessions.py <project-key> [--output-dir <dir>]")
        print("\nAvailable projects:")
        for d in sorted(os.listdir(CLAUDE_DIR)):
            jsonl_count = len(glob.glob(os.path.join(CLAUDE_DIR, d, '*.jsonl')))
            if jsonl_count > 0:
                print(f"  {d} ({jsonl_count} sessions)")
        sys.exit(1)

    project_key = sys.argv[1]
    project_dir = os.path.join(CLAUDE_DIR, project_key)

    # Output directory
    output_dir = None
    if '--output-dir' in sys.argv:
        idx = sys.argv.index('--output-dir')
        if idx + 1 < len(sys.argv):
            output_dir = sys.argv[idx + 1]

    if not output_dir:
        output_dir = os.path.join(os.getcwd(), '.claude', 'sessions')

    os.makedirs(output_dir, exist_ok=True)

    if not os.path.isdir(project_dir):
        print(f"Error: Project directory not found: {project_dir}")
        sys.exit(1)

    # Find all session transcripts
    transcript_files = sorted(glob.glob(os.path.join(project_dir, '*.jsonl')))
    print(f"Found {len(transcript_files)} session transcripts in {project_key}")
    print(f"Output directory: {output_dir}")
    print()

    all_analyses = []
    low_score_sessions = []
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

        # Track stats
        for corr in analysis['user_corrections']:
            correction_types[corr['type']] += 1
        for err in analysis['tool_errors']:
            error_types[err['type']] += 1

        if analysis['scores']['composite'] < 7:
            low_score_sessions.append(analysis)

        # Write individual session log
        outpath = write_session_log(analysis, output_dir)

        score = analysis['scores']['composite']
        corrs = len(analysis['user_corrections'])
        errs = len(analysis['tool_errors'])
        marker = ' !!!' if score < 5 else (' !' if score < 7 else '')

        if (i + 1) % 10 == 0 or score < 5:
            print(f"  [{i+1}/{len(transcript_files)}] {analysis['session_id'][:8]}... "
                  f"score={score} corrections={corrs} errors={errs}{marker}")

    # Summary
    print(f"\n{'='*60}")
    print(f"BACKFILL COMPLETE")
    print(f"{'='*60}")
    print(f"Sessions processed: {len(all_analyses)}")
    print(f"Session logs written to: {output_dir}")

    if all_analyses:
        avg_score = sum(a['scores']['composite'] for a in all_analyses) / len(all_analyses)
        avg_accuracy = sum(a['scores']['accuracy'] for a in all_analyses) / len(all_analyses)
        avg_efficiency = sum(a['scores']['efficiency'] for a in all_analyses) / len(all_analyses)
        avg_context = sum(a['scores']['context'] for a in all_analyses) / len(all_analyses)

        print(f"\nAvg Composite Score: {avg_score:.1f}/10")
        print(f"  Accuracy:   {avg_accuracy:.1f}")
        print(f"  Efficiency: {avg_efficiency:.1f}")
        print(f"  Context:    {avg_context:.1f}")

        print(f"\nSessions scoring < 7: {len(low_score_sessions)}/{len(all_analyses)}")
        print(f"Sessions scoring < 5: {sum(1 for a in all_analyses if a['scores']['composite'] < 5)}/{len(all_analyses)}")

        if correction_types:
            print(f"\nTop Correction Types:")
            for ctype, count in correction_types.most_common(10):
                print(f"  {ctype}: {count}x")

        if error_types:
            print(f"\nTop Error Types:")
            for etype, count in error_types.most_common(10):
                print(f"  {etype}: {count}x")

        # Show worst sessions
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
