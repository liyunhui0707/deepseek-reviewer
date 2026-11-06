# Working on DeepSeek Reviewer

This is the public, portable product. Keep historical audit records, private
review snapshots, credentials and machine-specific paths out of this repository.

- Preserve Restricted / safe-mode / dontAsk, Read/Glob/Grep only, empty MCP,
  isolated settings and Keychain namespace, one attempt and bounded execution.
- Do not retrieve credentials as a preflight or launch a paid review without
  task-specific authorization. Use synthetic subprocesses in offline tests.
- Do not change global Claude/Codex settings or install third-party binaries.
- Validate changes with `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
  Build with `python3 scripts/build.py`. Website source is in `site/`.
- Never claim application restrictions are OS isolation or a client budget is
  an absolute API bill cap. Keep observed execution, review quality and coverage distinct.
- Versions follow SemVer. Maintainer approval is required for a release number
  and publication. Do not publish or bump automatically for a routine patch.
