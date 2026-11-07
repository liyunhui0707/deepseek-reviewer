# Maintaining a release

The public source of truth is this repository. Runtime dependencies (Claude/Codex), credentials, reviews and local deployment credentials do not belong in Git.

1. Implement a scoped fix. Run `PYTHONPATH=src python3 -m unittest discover -s tests -v` and `python3 scripts/build.py`, then `python3 scripts/check_release.py`. These checks do not call a model or access Keychain.
2. Obtain maintainer approval for the SemVer scope. Update the version in `src/deepseek_reviewer/__init__.py`, `pyproject.toml` and `scripts/build.py`, with the release notes and website's displayed/download version. Keep the compatible Claude version explicit; never silently accept a changed executable.
3. Inspect staged content for private paths, credentials, snapshots, reports, binaries and unrelated changes. Publish the reviewed source. The offline GitHub workflow must pass before releasing.
4. Run the manual **Publish release** workflow with that exact approved version. It builds and uploads `deepseek-reviewer.pyz`, `SHA256SUMS` and `release.json`. Do not overwrite an existing release artifact; use a new version for corrections. The CLI's explicit update command follows the latest non-prerelease GitHub Release.
5. The public website source is `site/dist/`, with no build dependencies. Deploy that exact directory to the existing official Site, and verify its public URL and release links. Deployment is a separate action; pushing GitHub does not silently deploy a website. Use the Sites publishing workflow and the locally persisted `site/.openai/hosting.json` identity, or find the existing Site by its URL when using a fresh checkout. Never create a replacement Site merely because a local temporary checkout was removed.

The maintainer approved version **1.1.0** and its publication. Keep the website's public download pointing to v1.0.0 until the approved v1.1.0 GitHub assets actually exist. At publication, update the website's installation commands from v1.0.0 registration to `setup` together with its displayed/download version. Do not point v1.0.0 users at commands it lacks. Preserve the original v1.0.0 Skill fingerprints used for safe migration; future managed installations carry their own receipts.

Verify the first upgrade with the candidate archive's installer against the v1.0.0 launcher/state layout. The old executable's `update` uses old installation logic; candidate recovery guarantees only apply when the candidate installer runs. GitHub pushes trigger offline checks, while Release publication requires the separate manual workflow; website deployment is separate from both.

New-Mac acceptance still requires a separately approved test: install the downloaded artifact, complete setup and credential enrollment locally, invoke one synthetic review from Codex, verify actual search/read evidence and Findings, and exercise the documented recovery path without widening permissions. Record packaging, real provider execution, review quality and coverage separately. Offline tests and source changes do not claim this acceptance was performed.

Official website: https://deepseek-reviewer.outerepoch3.chatgpt.site

The website uses no runtime connectors or API keys. Static copies can be hosted elsewhere by downstream maintainers. The official Site's short-lived publishing credential is never a repository file.

Release 1.0.0 verification: 27 offline tests passed locally and in GitHub's macOS/Linux Python 3.11/3.13 matrix. The actual archive was installed into a disposable HOME; command version, Skill install/no-overwrite and unconfigured fail-closed checks passed. Update/rollback and tampered checksums were exercised with synthetic release archives. The publicly downloaded artifact matched the locally verified release hash. No paid provider test was performed for packaging. Website scripts, links and assets passed static checks; interactive visual QA was unavailable because the browser host could not be reached.
