# Changelog

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
