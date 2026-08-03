#!/usr/bin/env python3
"""Shared correction-classification for blackbox hooks.

NOT a standalone hook — imported by track_prompt.py and scripts/backfill.py,
so live tracking and backfilled history classify user messages identically.
Patterns originated in backfill and are tuned here; false positives are
expensive because each match deducts score AND feeds the rules store.
"""
import re

# Patterns that indicate user corrections.
# Each pattern is tested against the full user message (lowercased).
# Only strong, unambiguous signals are included to minimize false positives.
CORRECTION_PATTERNS = [
    # Explicit rejection of Claude's output
    (r'\bno[,.]?\s+(not |don\'t |stop |that\'s wrong|that\'s not)', 'explicit_no'),
    (r'\bthat\'s wrong\b', 'wrong'),
    (r'\bthat\'s not (right|correct|what)\b', 'not_right'),
    (r'\bno,? not that\b', 'not_that'),
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
    (r'\bwhy did you\b(?!\s+guys)', 'why_did_you'),
    (r'\bi already (said|told|asked)\b|\bi (said|told|asked) you\b', 'i_said'),
    # Overengineering signals
    (r'\btoo complex\b', 'too_complex'),
    (r'\bover.?engineer', 'overengineered'),
    (r'\b(make|keep) (it|this|that) simpler\b|\bsimpler,? please\b', 'simpler'),
    (r'\bjust do\b', 'just_do'),
    # Interruptions (Claude Code specific). Lowercase: always matched
    # against lowercased text, an uppercase pattern can never fire.
    (r'\brequest interrupted by user\b', 'interrupted'),
]

# Patterns indicating the user redirected the approach
APPROACH_PATTERNS = [
    (r'\bactually\b.*\binstead\b', 'approach_change'),
    (r'\blet\'s try\b.*\bdifferent\b', 'approach_change'),
    (r'\bforget that\b', 'approach_change'),
    (r'\bscrap (that|this|it|the)\b', 'approach_change'),
    (r'\bchange of plan\b', 'approach_change'),
    (r'\bnever\s?mind\b', 'approach_change'),
]

# Maps a correction label to the retro rule it feeds (frozen contract).
LABEL_TO_RULE_KEY = {
    'you_broke': 'breakage',
    'that_broke': 'breakage',
    'revert': 'breakage',
    'undo': 'breakage',
    'i_said': 'context_ignored',
    'why_did_you': 'context_ignored',
    'overengineered': 'overengineering',
    'too_complex': 'overengineering',
    'simpler': 'overengineering',
    'just_do': 'overengineering',
    'explicit_no': 'wrong_direction',
    'wrong': 'wrong_direction',
    'not_right': 'wrong_direction',
    'not_that': 'wrong_direction',
    'not_what_i_wanted': 'wrong_direction',
    'dont_do': 'wrong_direction',
    'stop_doing': 'wrong_direction',
    'start_over': 'wrong_direction',
    'approach_change': 'approach_change',
}


def classify(text):
    """Classify a user message as a correction.

    Returns (label, rule_key), or (None, None) if the message is not a
    correction. Interruptions are not corrections and return (None, None).
    First CORRECTION_PATTERNS match wins; APPROACH_PATTERNS are checked
    only if no correction pattern matched.
    """
    text_lower = (text or "").lower()

    for pattern, label in CORRECTION_PATTERNS:
        if re.search(pattern, text_lower):
            if label == 'interrupted':
                return (None, None)
            return (label, LABEL_TO_RULE_KEY.get(label))

    for pattern, label in APPROACH_PATTERNS:
        if re.search(pattern, text_lower):
            return (label, LABEL_TO_RULE_KEY.get(label))

    return (None, None)
