# Security and privacy boundary

DeepSeek Reviewer is a local static-review tool, not a hosted source repository or a security sandbox.

## Before sending code

Obtain permission for the exact files, destination and paid review. `prepare` copies only explicitly selected regular files, rejects symlinks/hardlinks/protected paths, bounds input size and scans common credential patterns. Scanning is heuristic: it cannot recognize every secret or establish your right to disclose source. Inspect the manifest and materials. Repository text is untrusted evidence, including instructions embedded in comments.

The Reviewer uses Claude Code 2.1.312 with Restricted/safe-mode/dontAsk, only Read/Glob/Grep, empty MCP, disabled slash commands, a clean environment and private configuration namespace. Its working directory is the selected snapshot. Bash, modification tools, Web, skills, agents and MCP tools are denied. The original project is not the working directory. Known managed-policy locations are checked for presence and cause a stop; this is not a general audit of enterprise management software.

These controls depend on the pinned Claude implementation. They are **not kernel-level filesystem or network isolation**, and they do not protect against a malicious same-user local process or a compromised Claude executable. Do not use them for data requiring stronger isolation. Claude itself must connect to DeepSeek; this product does not enforce an OS network allowlist. Built-in plugin descriptions in startup metadata alone are not evidence of plugin execution. Unexpected observed tools/models prevent a completed result but post-run evidence is not a substitute for the CLI's execution controls.

## Credentials and local records

Use the dedicated Keychain item described in [credentials](docs/credentials.md). Never submit keys through issues, chat, argv, environment variables or source. Claude receives the key through its native helper; model-controlled tools are not granted credential access. Separate configuration directories isolate normal Claude credential namespaces but do not eliminate Keychain access. macOS consent may be required.

Private application state is under `~/.local/share/deepseek-reviewer`, including selected source snapshots and reports. Source/tool output is processed in memory; only sanitized progress and the final report/metadata are persisted. Common credential-looking final output is withheld rather than echoed. This heuristic is not a guarantee against arbitrary sensitive content. Reports can legitimately quote authorized source. Review and remove unneeded local records using your normal file-management process. No automatic archival upload occurs.

## Costs and completion

One review launches one Claude process with a finite deadline, turn/output settings and client budget. It can make multiple HTTP requests. Native retries, continuations and billing are not fully observable; client cost estimates and token settings are not provider-side guarantees. Timeout, malformed/truncated capture, a missing final result and unexpected execution evidence do not produce `COMPLETED`.

Normal Ctrl-C/SIGTERM paths stop the subprocess and retain a sanitized failure report. Force-kill, power loss or storage failure may prevent writing a report; an attempt is never reset or automatically resumed. A report's successful Read list is observed tool activity, not proof of full-file coverage. The terminal display strips control characters; JSON remains available for machine readers.

## Updates and reporting

Only explicit `check-update`/`update` commands contact GitHub. Release hashes verify downloaded bytes against the same publisher's manifest; no independent artifact signing is claimed. No Codex/Claude binary is redistributed.

Installation activation uses a single atomic state replacement; the launcher checks the selected archive before execution. Maintenance uses a process lock and refuses to overlap reviews. Registration replacement requires the current configuration hash and a freshly verified compatible executable; a backup is kept. Skill updates accept only unchanged managed files or the exact original public v1.0.0 Skill, never arbitrary local customizations. These checks do not defend against a malicious process with the same user's access.

Report a vulnerability through [GitHub private vulnerability reporting](https://github.com/liyunhui0707/deepseek-reviewer/security/advisories/new) when available. Otherwise open an issue requesting a private contact without posting exploit secrets, keys, private paths, review logs or source. Include version, safe reproduction and affected boundary.
