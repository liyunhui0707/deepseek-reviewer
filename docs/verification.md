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
