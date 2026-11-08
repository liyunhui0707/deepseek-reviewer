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

## Published 1.2.0

- [Release v1.2.0](https://github.com/liyunhui0707/deepseek-reviewer/releases/tag/v1.2.0) was published from source commit `6683cf0d24ce65502fe770680e95d0bb28cb5f8f`.
- All 71 offline tests passed locally and in the [four-job macOS/Linux Python 3.11/3.13 CI matrix](https://github.com/liyunhui0707/deepseek-reviewer/actions/runs/42490456521). The [publication workflow](https://github.com/liyunhui0707/deepseek-reviewer/actions/runs/42490580804) passed its tests, build and actual-archive installation check.
- Tests cover explicit public checkpoint retention during budget/turn/time exhaustion, missing or invalid final results, secret/out-of-scope checkpoint rejection, capture limits, deduplicated observed usage, profile overrides, legacy Skill conflicts and cleanup failures. They do not prove the model will emit a checkpoint or finish within a budget.
- All three public assets were downloaded and matched GitHub digests, `release.json` and `SHA256SUMS`. The published archive SHA-256 is `8554f83ffb4d4f1ff583b589709c61e06daf21daf421e2c6c8c18296b704e805`; its packaged entries match the accepted local build. The public archive passed installation/setup/doctor/Skill checks in a disposable HOME with a synthetic Claude only.
- The existing public website deployed successfully as Site version 3 from source `153e5e145a3d712f99a113e9d022aa8d1d8cee19`. Five expected archive files (four static resources and one manifest) were checked; Site identity and public audience were preserved. Copy-command tests, JavaScript syntax, links and assets passed. Layout was unchanged; a new browser viewport test was not performed.
- The checked 36-file publication scope contained no detected credential-like literals, private user paths or protected credential files. Pattern scanning is not a proof that all possible sensitive data is absent.
- No paid review, Keychain secret retrieval or new-Mac provider acceptance was performed for this release. Live-model checkpoint behavior and actual provider billing remain separately unverified. Earlier verification entries above record their original point in time; they are not rewritten as new results.

### Installation follow-up

Installing the verified public v1.2.0 archive on the maintainer Mac succeeded, but the real pinned Claude registration preview stopped with `missing_claude_capability`. The unchanged 2.1.312 executable defines `--max-turns` with `hideHelp()`; registration incorrectly required that flag in `--help`. The [official CLI contract](https://code.claude.com/docs/en/cli-reference) documents the flag. The legacy Skill has not been retired and no credential was read as part of this failure.

The minimal correction removes only the hidden flag from the visible-help assertion. It retains the pinned version, binary fingerprint, visible safety-flag checks and `--max-turns` in the actual invocation. A regression reproduces the original error and still rejects missing Restricted support and unsupported versions. All 72 offline tests, the actual candidate archive check and a read-only preview against the installed Claude passed. The published v1.2.0 archive was not overwritten; its release notes disclose this setup issue. The maintainer subsequently approved patch version 1.2.1; publication and local migration are recorded below when complete.

## Published 1.2.1

- The maintainer approved and published [v1.2.1](https://github.com/liyunhui0707/deepseek-reviewer/releases/tag/v1.2.1) from `b03d684d0f9ed5953db3bcf39b98095e16443071`, without replacing v1.2.0 artifacts.
- All 72 offline tests passed locally and in the [four-job CI matrix](https://github.com/liyunhui0707/deepseek-reviewer/actions/runs/42491379542). The [publication workflow](https://github.com/liyunhui0707/deepseek-reviewer/actions/runs/42491511201) passed tests, build and installation checks. The earlier registration test failure was reproduced before the fix; the real pinned Claude then passed an offline registration preview.
- Three public assets were downloaded and matched their GitHub digests, `release.json` and `SHA256SUMS`. Published archive SHA-256: `9056a88f9e25ae75e338e2e1feff3b0f3bb84c03b879f01b4699366b38c2855c`. Its entries match the local candidate; actual-archive setup/doctor/Skill checks passed in an isolated synthetic HOME.
- That same public archive was installed on the maintainer Mac, and the unchanged Claude 2.1.312 was registered. The old audit Skill was backed up byte-for-byte outside Skill discovery before installing the product Skill. `doctor` reports version 1.2.1, LOCAL_READY, Skill CURRENT and zero legacy conflicts. Only product-local registration and Skill files changed; no Claude/Codex global settings or historical audit files were edited. No credential was retrieved or copied. Authentication and a new paid review are NOT TESTED.
- Existing Site version 4 deployed successfully from `d738fd24498d1d4a56ec369fc90488fb25517d7a`, with v1.2.1 links, the same public URL/audience and five validated archive files. Installation copy-block tests, JavaScript syntax, assets and anchors passed. A new visual viewport check was not performed; layout is unchanged.
- The standard product Keychain item is distinct from the legacy private workflow. User-side enrollment remains necessary unless that product item already exists; setup/doctor do not establish its presence or validity. Current sessions can re-read the updated Skill, or exit and resume if stale instructions persist. No account logout is required.
