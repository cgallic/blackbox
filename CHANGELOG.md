# Changelog

## 0.2.0 (2026-07-13)

Self-learning loop.

- Live user-correction tracking: new `track_prompt.py` UserPromptSubmit hook classifies corrections ("no, that's wrong", "I already told you", "simpler") as you type them and logs `user_correction` events — previously this signal only existed in backfill
- Persistent rules store (`.claude/sessions/rules.json`) with automatic lifecycle: candidate → Watch (2+ hits) → Important (4+) → Critical (8+), auto-archive after 10 clean sessions (20 for Important/Critical)
- Session-start context injection: active rules and last session's failures are injected into Claude's context via the SessionStart hook, closing the learning loop
- Session-end learning update: guardrail triggers and corrections become rule hits automatically; scorecard gains "User corrections" and "Learning" sections
- `blackbox rules` CLI: list / add / archive / promote learned rules
- Shared correction heuristics extracted to `hooks/_corrections.py` (used by live tracking; same patterns as backfill)
- `/retro` skill reworked around the rules store; `/scorecard` skill includes corrections
- CI runs all test files; new test suites for corrections, rules store, and session learning

## 0.1.0 (2026-03-23)

Initial release.

- 7 compliance tracking hooks (read-before-edit, test-before-commit, destructive command detection)
- Enforcement: blocks edits on unread files, blocks commits without passing tests
- Escalation: 1st warn, 3rd block, 5th require override
- Override system: `blackbox override <action> --reason "..."`
- Agent Scorecard: printed automatically at session end
- Session timeline: ordered list of actions with violation markers
- `/scorecard` skill: manual session scoring
- `/retro` skill: weekly pattern mining, auto-updates CLAUDE.md rules (max 10, strict format)
- `blackbox report`: full audit dashboard
- `blackbox backfill`: mine historical Claude Code transcripts
- 57+ tests
