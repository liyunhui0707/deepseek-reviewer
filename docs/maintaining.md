# Maintaining a release

The public source of truth is this repository. Runtime dependencies (Claude/Codex), credentials, reviews and local deployment credentials do not belong in Git.

1. Implement a scoped fix. Run `PYTHONPATH=src python3 -m unittest discover -s tests -v` and `python3 scripts/build.py`, then `python3 scripts/check_release.py`. These checks do not call a model or access Keychain.
2. Obtain maintainer approval for the SemVer scope. Update the version in `src/deepseek_reviewer/__init__.py`, `pyproject.toml` and `scripts/build.py`, with the release notes and website's displayed/download version. Keep the compatible Claude version explicit; never silently accept a changed executable.
3. Inspect staged content for private paths, credentials, snapshots, reports, binaries and unrelated changes. Publish the reviewed source. The offline GitHub workflow must pass before releasing.
4. Run the manual **Publish release** workflow with that exact approved version. It builds and uploads `deepseek-reviewer.pyz`, `SHA256SUMS` and `release.json`. Do not overwrite an existing release artifact; use a new version for corrections. The CLI's explicit update command follows the latest non-prerelease GitHub Release.
5. The public website source is `site/dist/`, with no build dependencies. Deploy that exact directory to the existing official Site, and verify its public URL and release links. Deployment is a separate action; pushing GitHub does not silently deploy a website. Use the Sites publishing workflow and the locally persisted `site/.openai/hosting.json` identity, or find the existing Site by its URL when using a fresh checkout. Never create a replacement Site merely because a local temporary checkout was removed.

The maintainer approved version **1.4.0**, publication and local installation on 2026-11-14. It is now published with matching website instructions and installed CLI/Skill. Release 1.3.0 remains immutable; 1.4.0 adds optional project consent while preserving the report contract and execution restrictions. Do not point older-version users at commands they lack. Preserve the original v1.0.0 Skill fingerprints used for safe migration; future managed installations carry their own receipts. See [published 1.4.0](verification.md#published-140) for verification and the maintainer Mac's separate missing-Claude blocker.

Verify the first upgrade with the candidate archive's installer against the v1.0.0 launcher/state layout. The old executable's `update` uses old installation logic; candidate recovery guarantees only apply when the candidate installer runs. GitHub pushes trigger offline checks, while Release publication requires the separate manual workflow; website deployment is separate from both.

New-Mac acceptance still requires a separately approved test: install the downloaded artifact, complete setup and credential enrollment locally, invoke one synthetic review from Codex, verify actual search/read evidence and Findings, and exercise the documented recovery path without widening permissions. Record packaging, real provider execution, review quality and coverage separately. Offline tests and source changes do not claim this acceptance was performed.

Official website: https://deepseek-reviewer.outerepoch3.chatgpt.site

The website uses no runtime connectors or API keys. Static copies can be hosted elsewhere by downstream maintainers. The official Site's short-lived publishing credential is never a repository file.

On macOS, use `COPYFILE_DISABLE=1` for the Sites packaging helper and check the archive inventory before saving/deploying. Include only the expected static files and hosting manifest, without AppleDouble metadata or private checkout files.

Release 1.0.0 verification: 27 offline tests passed locally and in GitHub's macOS/Linux Python 3.11/3.13 matrix. The actual archive was installed into a disposable HOME; command version, Skill install/no-overwrite and unconfigured fail-closed checks passed. Update/rollback and tampered checksums were exercised with synthetic release archives. The publicly downloaded artifact matched the locally verified release hash. No paid provider test was performed for packaging. Website scripts, links and assets passed static checks; interactive visual QA was unavailable because the browser host could not be reached.

Release 1.1.0 is published. Its 49-test offline matrix and publication workflow passed; downloaded assets and isolated installation were verified. The existing public website now serves the matching instructions. Published hashes, source commits and remaining verification limits are recorded in [verification scope](verification.md#published-110).

Release 1.2.0 is published. Its 71-test offline matrix and publication workflow passed, and the public archive passed isolated installation checks. The main Git transport timed out; the official Git Data API transferred the identical local tree and commit, with hash equality verified before a non-forced branch update. No global Git/network configuration was changed. Downloaded hashes and remaining verification limits are in [verification scope](verification.md#published-120).

A first real-Mac setup of v1.2.0 exposed a hidden-help-option false rejection. The minimal fix is published in v1.2.1; v1.2.0 assets remain immutable and its release notes disclose the issue. Future packaging checks model the pinned CLI’s hidden `--max-turns` behavior.

Release 1.2.1 completed the real-Mac installation and legacy Skill migration, with the old Skill backed up unchanged outside discovery. The public archive and four-job CI passed; setup reports LOCAL_READY and CURRENT with no conflicting legacy Skill. Product credentials were not enrolled, read or migrated by the agent. See [published 1.2.1](verification.md#published-121) for evidence and verification limits.


Release 1.3.0 is published and installed on the maintainer Mac with the matching managed Skill. Its 104-test matrix, public-archive verification, disposable installation and actual-archive upgrade/rollback checks passed. The website deployment succeeded; after automated visitor-side checks were blocked in this environment, the maintainer confirmed normal browser access, v1.3.0 display and the download button on 2026-11-09. No additional paid review or credential access occurred during release; the preceding narrow real delivery acceptance is recorded separately. See [published 1.3.0](verification.md#published-130) for hashes, evidence and remaining limits. Continue maintenance only for observed faults, compatibility changes or authorized improvements.

Release 1.4.1 adds explicitly supported Claude 2.1.325 compatibility while preserving 2.1.312. The public archive is installed on the maintainer Mac; confirmed registration migration to the existing 2.1.325 executable restored LOCAL_READY with Skill CURRENT. Version/help checks and offline tests do not establish real-provider acceptance on 2.1.325. See [published 1.4.1](verification.md#published-141).
