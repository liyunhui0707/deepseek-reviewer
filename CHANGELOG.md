# Changelog

## 1.1.0

- Repeatable offline setup and readable Terminal diagnostics, with explicit JSON output for Codex.
- Preview/confirm/backup/restore for compatible Claude registration; managed Skill check/update/restore without overwriting customizations.
- Atomic version activation, preserved rollback history, maintenance/review locking, and cancellation reports.
- Observed reading gaps, elapsed/remaining time, saved-report retrieval, and fail-closed copyable installation instructions.
- No change to the pinned Claude version, review permissions, paid-call defaults or limits.

For the first upgrade from v1.0.0, verify the new archive and run its installer while no reviews are active. Then explicitly check/update the managed Skill. Registration, credentials and review records are preserved; customized Skills are not overwritten. See the [upgrade instructions](https://github.com/liyunhui0707/deepseek-reviewer/blob/v1.1.0/README.md#update-and-rollback).

## 1.0.0

- Portable macOS CLI for scoped independent DeepSeek reviews through Claude Code 2.1.312 Restricted.
- Explicit private snapshots, native Keychain helper, bounded execution and direct Findings return.
- Codex Skill for natural-language review requests.
- Versioned local installation, explicit checksum-verified updates and rollback.
- Public documentation, offline regression tests and a static download website.

This release does not redistribute Claude Code or Codex. Application restrictions, provider compatibility and client billing estimates retain the boundaries documented in SECURITY.md.
