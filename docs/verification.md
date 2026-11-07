# Verification scope

The core workflow was developed and accepted before this public distribution:

- Real DeepSeek via Claude Code autonomously used Glob/Grep/Read on synthetic code, found intentional defects, returned findings to the initiating Codex session and exited successfully.
- Claude 2.1.312 Restricted supplied application-level boundary evidence. This was never an OS-sandbox certification.
- A separately authorized limited historical-source review returned findings which the primary agent independently checked.
- Dedicated macOS Keychain authentication and result return were accepted without repeatedly entering an API key.
- Stream filtering and finite resource limits were repaired and regression-tested after incomplete historical runs.

Private project names, file bodies, conversations, credentials, session identifiers, raw logs and historic experimental implementations are not distributed. Historical failures are not rewritten as successes. The public repository has an independent history.

The portable release keeps the accepted bounded subprocess/capture implementation and invocation restrictions, and adds explicit snapshot preparation, per-Mac registration, packaging, installation/update/rollback and a portable Skill. Its offline suite uses synthetic subprocesses and disposable home directories. Those tests demonstrate local mechanics and fail-closed behavior; they do not substitute for a paid provider acceptance on each new Mac.

The first authorized use on a new Mac should verify model identity, actual read/search evidence, unchanged materials, final report, exit status and client usage. Do not reclassify missing evidence as success or enlarge source scope to diagnose a failure.

## Unreleased reliability and usability changes

The current development changes add repeatable setup, explicit runtime/Skill migration and restoration, atomic release activation, maintenance/review locking, saved-report retrieval, readable progress and actionable diagnostics. They have not replaced the published v1.0.0 release or been installed into the maintainer's normal Reviewer configuration.

Offline verification covers installation-command failure handling, interrupted first installation and updates, rollback history, customized-file preservation, stale registration confirmation, maintenance conflicts, Ctrl-C/SIGTERM cleanup, report retention and observed-read coverage. The packaged archive is installed in a disposable HOME and exercised with a synthetic Claude executable; it never retrieves a key or sends a model request. Existing Restricted, snapshot, capture-limit and one-attempt tests remain in the regression suite.

Local verification on 2026-11-07: 48 Python tests passed, the archive build passed, and `scripts/check_release.py` passed on macOS. This records local results; it does not claim a new GitHub CI run or publication.

Release-preparation follow-up on the same date: the full suite passed 49 tests, including migration from the exact v1.0.0 launcher/state layout using synthetic archives. Interrupted migration kept the old executable usable; successful migration and rollback preserved synthetic registration and review evidence. The actual development archive again passed `scripts/check_release.py`. This does not certify a published old-to-new binary upgrade before the new release version/artifact is finalized.

The publication-scope check covered 35 source/document/test files and the local archive inventory. No protected credential files, machine-specific private paths or credential-like literals were found in that checked scope; pattern checks cannot guarantee the absence of all secrets. Only sample Git hooks were present. The public Release remained v1.0.0 at the time of this check; no commit, push, release, website deployment or paid review was performed.

Website copy behavior has synthetic DOM coverage and the displayed installation commands are tested with synthetic commands in a real shell. Actual desktop/mobile viewport inspection remains NOT TESTED in this round because browser access is unavailable. A clean second Mac and a new paid provider acceptance have not been exercised. These are release acceptance gaps, not evidence that authentication, billing or every supported machine has already passed.

## Approved 1.1.0 candidate

The maintainer approved version 1.1.0 on 2026-11-07. The module, project metadata, builder and archive metadata agree; publication is still pending. The local candidate archive is 32,399 bytes, SHA-256 `1205be2958a3d580e8e61e11b0a766a5bdcf2f9a7185408b783be28630253a8c`.

- All 49 offline tests and the actual-archive installation checks passed with this candidate.
- A separate disposable HOME exercised the actual candidate installer against v1.0.0 rebuilt from public source commit `562a8ae45fd589ab0d29e6bd44a12ea772a81c4f`. The old archive was rebuilt locally, not downloaded or claimed byte-identical to the published asset.
- Registration and synthetic review evidence survived migration, rollback and re-upgrade. The exact legacy Skill was recognized, explicitly updated and restored. Only a synthetic Claude executable ran; there were no credential reads or model requests.
- No user installation, global configuration, public Release or website deployment was changed. Public download links still refer to v1.0.0.

The release workflow rebuilds the archive. Its future output must be checked and its own checksum recorded; the local candidate checksum is not a claim about an unpublished CI artifact. Browser viewport, second-Mac and real-provider acceptance limitations above remain unchanged.

## Published 1.1.0

- [Release v1.1.0](https://github.com/liyunhui0707/deepseek-reviewer/releases/tag/v1.1.0) was published from source commit `a68e58b8fd16c182f7a61629087abe22d47ee572`.
- [Offline CI](https://github.com/liyunhui0707/deepseek-reviewer/actions/runs/42378736057) passed all four macOS/Linux and Python 3.11/3.13 combinations. The [publication workflow](https://github.com/liyunhui0707/deepseek-reviewer/actions/runs/42378839981) also passed its tests, build and installation checks.
- All three assets were downloaded from the public Release and matched GitHub's asset digests, `release.json` and `SHA256SUMS`. The published archive SHA-256 is `b77eaac41154a0631f432ee48268b2c8e2514f22eb129659e18d020b4c7049ac`; its packaged file contents match the accepted local candidate despite the rebuilt ZIP having a different overall checksum.
- The downloaded archive passed installation, version, setup, Skill and configuration checks in a disposable HOME using a synthetic Claude executable. No real model or Keychain access occurred, and the maintainer's normal installation was not changed.
- The [existing public website](https://deepseek-reviewer.outerepoch3.chatgpt.site) was deployed successfully as Site version 2 from website source commit `73141f48a352fa27c9d5c4c2ef445701fc4e2777`. It points to v1.1.0 and includes the new setup command and v1.0.0 migration guidance. The final packaging check accepted exactly four static resources and one hosting manifest, without macOS AppleDouble entries. The original Site identity and public audience were retained.
- Website installation-command tests, JavaScript syntax, assets and anchor checks passed. Browser access remained unavailable, so real desktop/mobile viewport QA is NOT TESTED. New-Mac paid-provider acceptance remains separate; publication did not perform it.
