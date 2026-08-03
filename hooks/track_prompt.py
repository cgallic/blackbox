#!/usr/bin/env python3
"""UserPromptSubmit hook: classify user prompts as corrections.

Runs classify() from _corrections on every submitted prompt. If the prompt
looks like a correction (breakage, context failure, overengineering, wrong
direction, approach change), logs a user_correction event to compliance.jsonl.

Never blocks, never prints, always exits 0.
"""
import sys
import json
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _corrections import classify
from _violations import log_compliance


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    try:
        prompt = data.get("prompt", "")
        if not isinstance(prompt, str) or not prompt:
            return

        label, rule_key = classify(prompt)
        if not label:
            return

        proj_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        log_compliance(proj_dir, {
            "type": "user_correction",
            "ts": datetime.now(timezone.utc).isoformat(),
            "category": label,
            "rule_key": rule_key,
            "snippet": prompt[:160],
        })
    except Exception:
        return


if __name__ == "__main__":
    main()
