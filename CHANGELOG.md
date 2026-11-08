# Changelog

## 1.2.0

- Preserve explicitly structured public review checkpoints as `partial_review` when time, turns or the client budget run out. Keep provisional opinions separate from the final `findings` report and never reinterpret internal thinking, tool results or error text as Findings.
- Add quick/standard planning presets, priority-file selection and oversized-scope advice. Existing defaults and hard resource ceilings remain unchanged; no automatic budget increase or retry.
- Report partial observed token usage without double-counting response snapshots; keep HTTP request count and actual provider billing unknown.
- Detect competing legacy Skills, direct all product calls through `prepare / review / report`, and preserve original failure diagnostics when process cleanup fails.
- Early checkpoints are requested, not guaranteed. This CLI does not enforce a final-report reservation before a hard stop. New retention behavior has offline synthetic coverage; no new paid review was performed for this release.

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
