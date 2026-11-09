# DeepSeek Reviewer

**An independent code-review agent, directly in your Codex conversation.**

Codex prepares a scoped review. Claude Code runs DeepSeek with read-only file tools. Findings return to the same Codex session for verification and action.

[Website](https://deepseek-reviewer.outerepoch3.chatgpt.site) · [Download v1.2.1](https://github.com/liyunhui0707/deepseek-reviewer/releases/tag/v1.2.1) · [中文使用说明](docs/guide.zh-CN.md) · [Security & privacy](SECURITY.md) · [Release notes](CHANGELOG.md)

```text
Your Codex session → approved snapshot → Claude Code Restricted + DeepSeek
         ↑                                Glob · Grep · Read
         └──────── evidence-backed findings ────────────┘
```

## What it does

- Lets a second model independently search and read selected code and tests.
- Keeps your primary Codex model, login and global configuration unchanged.
- Creates a private snapshot from an explicit file list; blocks secret paths, symlinks, hardlinks and common credential patterns before copying.
- Uses macOS Keychain through Claude's native `apiKeyHelper`. The parent CLI never retrieves the API key.
- Limits execution time, output capture, Agent turns and the client's cost estimate. Streams concise progress and preserves the final report.
- Provides a Codex Skill, checksum-verified updates and local rollback.

This is **static review**, not an automatic acceptance test. Findings need verification by the primary agent or developer. The Reviewer cannot execute tests or edit code.

## Requirements

- macOS, Python **3.11+**, and a working Codex installation.
- An independently installed **Claude Code 2.1.312** native executable. This release checks that version and registers its SHA-256; it stops if the executable changes. Other versions require a compatibility update.
- Your own DeepSeek API account/key and permission to send the selected materials to DeepSeek.

Claude Code and Codex are separate products, **not included** in this distribution. Obtain them from their official publishers. Review [Claude's setup documentation](https://code.claude.com/docs/en/setup) for installation/version management. This product does not install, downgrade, upgrade or log into either CLI.

This guide covers **v1.2.1**. Select matching v1.2.1 assets from the release list. Earlier versions do not support every command below; use their versioned documentation or upgrade first.

## Install

Download `deepseek-reviewer.pyz` and `SHA256SUMS` from the **same GitHub Release**. In the directory containing the downloaded files:

```sh
/bin/sh -eu -c '
shasum -a 256 -c SHA256SUMS
python3 deepseek-reviewer.pyz --version
python3 deepseek-reviewer.pyz install
'
```

Continue only if the checksum succeeds. Installation creates `~/.local/bin/deepseek-reviewer` and a versioned directory under `~/.local/share/deepseek-reviewer`. It needs no `sudo`, Python packages, daemon or shell-profile edits. Use the full command path below if `~/.local/bin` is not on your PATH.

Run setup, then enroll your key once **in your own interactive Terminal**:

```sh
/bin/sh -eu -c '
~/.local/bin/deepseek-reviewer setup
~/.local/bin/deepseek-reviewer credentials save
~/.local/bin/deepseek-reviewer doctor
'
```

`setup` looks for the pinned Claude version, then the `claude` on PATH; use `setup --claude /absolute/path` for a different location. It checks compatibility and installs the bundled Skill without replacing existing customizations. It is repeatable and does not access credentials or call a model. Skip `credentials save` if already enrolled for this product. `doctor` reports **LOCAL_READY**, not authenticated or live-tested. Codex detects Skill updates automatically. If an active session still follows old instructions, save your work, exit and `codex resume` that same session in the same project; no logout or login is needed. Use `$deepseek-reviewer` explicitly to select the product Skill. See [Codex’s Skill documentation](https://learn.chatgpt.com/docs/build-skills).

Keychain may display an access dialog during a review. Choose **Allow**, not **Always Allow**. Saving a key removes repeated key entry; it does not remove macOS consent. See [credential maintenance](docs/credentials.md).

## Use from Codex

Say:

> Use DeepSeek to independently review these changes.

Or:

> 用 DeepSeek 来审核下。

The Skill selects a focused task, prepares a manifest, confirms any missing source-disclosure/cost authorization, invokes one review, and reads the Findings in the same conversation. Authorization already provided for the same scope is reused. Host command approvals still apply.

The **Skill** tells Codex how to use the product; the **CLI** performs preparation, bounded execution and report retrieval. All projects use the same installed CLI. They do not need their own launcher or the historical audit project.

For direct CLI use, prepare first. This step is offline:

```sh
~/.local/bin/deepseek-reviewer prepare \
  --root "$PWD" \
  --file src/price.py --file tests/test_price.py \
  --question 'Check quantity validation and total calculation against the tests.' \
  --revision 'working files selected for this review'
```

Inspect the returned file list, hashes, task and limits. After authorizing that exact snapshot's disclosure and paid call, use the **returned** values:

```sh
~/.local/bin/deepseek-reviewer review \
  --plan /absolute/path/from/prepare/plan.json \
  --plan-sha256 HASH_FROM_PREPARE \
  --approve-upload
```

A plan can run once. There is no automatic relaunch. `COMPLETED` means the bounded invocation returned a report with the expected observed model/tools and unchanged snapshot. `PARTIAL` preserves a usable report when execution or evidence is incomplete. Neither status certifies code correctness or complete coverage. Exit 0 is reserved for `COMPLETED`; other outcomes exit nonzero.

Interactive terminals show readable summaries and elapsed/remaining time. Pipes default to JSON; `--text` or `--json` overrides either behavior. Codex should use `--json`. Silence means no new observed output, not confirmed Keychain waiting. Press Ctrl-C to cancel; normal cancellation/termination cleans up the child and saves a failure report. Force-kill or power loss can prevent report creation; a consumed attempt is never reset.

Retrieve an existing result without starting a model:

```sh
~/.local/bin/deepseek-reviewer report --id ATTEMPT_ID --text
```

The ID is returned by `prepare`. Reports distinguish successful Read observations, files without such observations, Findings and client usage. A successful Read does not prove full-file reading or complete review. Codex must still classify confirmed defects, unverified hypotheses and optional advice.

### Partial reports and review profiles

Version 1.2.0 preserves the latest **explicit, structured public review checkpoint** when budget, turns or time run out. `PARTIAL` can mean **partial review available, no final report**. `findings` remains the final-report field; `partial_review` holds provisional opinions and declared coverage gaps. Ordinary progress, internal thinking, tool output and error messages are never promoted to Findings. Invalid, secret-like or out-of-scope checkpoints are withheld; corrupted/oversized captures cannot produce accepted partial reports. Missing usage remains unknown, not zero. A later final report supersedes preliminary opinions.

Preparation adds `--profile quick` (180s, 8 turns, 4,000 output tokens, $0.25) and `--profile standard` (the existing defaults below). Explicit limit flags override the preset. `--focus-file` prioritizes up to three paths already selected with `--file`; it leaves other approved context available for independent exploration. Scope advisories appear above 6 files/48 KiB for quick or 12 files/96 KiB for standard. These are guidance, not measured completion capacities. Narrow the question and include necessary context before authorizing; do not automatically increase budgets or split into paid runs.

**There is no enforced “stop exploring, then finish” reservation in this invocation.** The pinned CLI's turn/budget caps stop execution; the Runner's timeout terminates it. Checkpoint/report instructions cannot force model compliance or a final report. Streaming another input can start another turn with its own limit, so this product does not inject follow-up prompts, resume or relaunch to manufacture completion. See the [official CLI reference](https://code.claude.com/docs/en/cli-reference). Bounded synthetic subprocess tests verify retention mechanics; the live acceptance described below covers one narrow task. Checkpoints are saved when the bounded invocation returns; a forced kill of the parent or power loss can still prevent saving.

Version 1.3.0 uses one cumulative structured report format for provisional opinions and the final result. Completion requires a valid report in the successful terminal result, complete capture, exit 0, expected model/tools, observed reads, unchanged snapshot and successful cleanup. Bare JSON and one `review-report`, `json` or legacy `review-checkpoint` fence are equivalent envelopes. An earlier assistant report cannot replace missing or invalid terminal content. Budget, turn, timeout and process failures remain incomplete; safe opinions may survive as `PARTIAL`. A supported no-defect assessment is valid; progress is not a report.

Rejected final results retain `final_report_diagnostic`: fixed status, stage, reason and envelope categories, without rejected prose or hidden reasoning. If a later revision is rejected, an earlier safe opinion is marked `partial_review_stale=true`. Corrupted capture or unsafe execution withholds partial delivery. Saved historical reports keep their original status. **Prepare and authorize a new plan for old, unexecuted plans; consumed attempts cannot be reused.**

Thinking is explicitly requested disabled through the pinned client's fixed provider configuration, independently of effort. One authorized narrow real-provider acceptance returned a validated final report with normal exit and no observed thinking events. That proves delivery for that run, not guaranteed completion, accurate Findings or full coverage. See [verification scope](docs/verification.md).

The updated Skill status also reports competing `deepseek-review` entries in `~/.agents/skills` or `~/.codex/skills`. Inspect and back up/retire the legacy entry with user approval, then use the product `deepseek-reviewer` Skill. Do not invent a project-local wrapper when the installed CLI is absent. Installation/setup does not silently overwrite or disable a customized legacy Skill.

## Limits and data

| Setting | Default | Maximum supported override |
| --- | ---: | ---: |
| Wall time, including Keychain wait | 300 seconds | 600 seconds |
| Agent turn setting | 12 | 32 |
| Client budget threshold | US$0.50 | US$2.00 |
| Output-token setting per call | 16,000 | 64,000 |
| Explicit snapshot | 50 files, 256 KiB total | fixed |
| Retained / raw stdout / JSONL record | 4 MiB / 64 MiB / 1 MiB | fixed |

`prepare --help` lists overrides. Low effort is the default effort setting; `--effort default` leaves that effort field unset. Thinking is independently requested disabled. Model/provider behavior may differ from a requested setting. Agent turns are **not HTTP requests**. Native retries/continuations may occur. Claude's cost estimate is **not DeepSeek's invoice or a hard billing cap**. Actual request count and provider charges can remain unknown.

Only the selected snapshot and task are intended for the fixed `deepseek-flash[1m]` route at `https://api.deepseek.com/anthropic`. No runtime data is sent to this project's website. Local snapshots, settings and reports live in a private per-user application directory and are retained for your inspection; they are not automatically deleted or uploaded. They can contain source. Do not commit or share them without review.

Restricted/safe-mode, Read/Glob/Grep, empty MCP, clean environment and separate configuration directories are **application-level restrictions, not an OS sandbox**. Common managed-policy files cause a stop for manual compatibility review. A clean configuration namespace can still cause macOS Keychain queries in that namespace. Read [the complete security boundary](SECURITY.md) before reviewing confidential code.

## Update and rollback

For the first upgrade from v1.0.0, download and verify the new release, then run its `python3 deepseek-reviewer.pyz install` command while no reviews are active. This uses the new installer to migrate the old launcher while preserving registration, review records and rollback. Running `update` from v1.0.0 instead uses the old installer for that first transition; the new atomic-activation protection cannot apply retroactively. After migration, use:

```sh
~/.local/bin/deepseek-reviewer check-update
~/.local/bin/deepseek-reviewer update
~/.local/bin/deepseek-reviewer rollback
```

Updates are user-triggered. The CLI fetches release metadata and the archive from this GitHub repository, enforces HTTPS/host/size checks, verifies SHA-256, and retains the previous version. It does not update Claude or Codex. Checksums protect transfer integrity; they are not independent signatures against a compromised release publisher.

The executable selects a checksum-verified archive through one atomic installation-state file. An interrupted activation retains the previously selected version; an interrupted first install fails closed and can be repeated with the same verified archive. Reinstalling the same version preserves rollback history. Maintenance refuses to overlap active reviews or other maintenance.

Skill updates are separate and explicit, using the **newly installed CLI**:

```sh
~/.local/bin/deepseek-reviewer install-skill --check
~/.local/bin/deepseek-reviewer install-skill --update
# If you need the saved previous Skill:
~/.local/bin/deepseek-reviewer install-skill --restore
```

Only unchanged product-managed files (or the exact public v1.0.0 Skill) are eligible. Unknown files, links and customizations stop automatic replacement. A bounded local backup is retained. If Codex still follows the old Skill, exit and resume the same session. A CLI rollback does not silently downgrade the Skill; check compatibility and explicitly restore it if necessary.

If Claude moved or changed, the Reviewer stops. First inspect the proposed registration; do not delete the existing one:

```sh
~/.local/bin/deepseek-reviewer configure --claude /absolute/path/to/claude --check
# After inspecting and approving the difference, use the returned current_sha256:
~/.local/bin/deepseek-reviewer configure --claude /absolute/path/to/claude --replace --expected-runtime-sha256 HASH_FROM_CHECK
# Restore the previous registration only if its executable is still compatible:
~/.local/bin/deepseek-reviewer configure --restore --expected-runtime-sha256 CURRENT_HASH_FROM_CHECK
```

Replacement still enforces the pinned version, capabilities and binary fingerprint, preserves `runtime.previous.json`, and never accesses Keychain. Previously prepared plans bound to the old runtime must be prepared and authorized again. A missing or changed old binary cannot be restored by changing configuration alone.

To uninstall, stop active reviews, optionally run `credentials remove`, then move only `~/.local/bin/deepseek-reviewer`, `~/.local/share/deepseek-reviewer` and `~/.codex/skills/deepseek-reviewer` to Trash using Finder. The application directory contains local review evidence; export any records you want to retain first. This does not remove Claude, Codex or unrelated credentials.

## Development and verification

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/build.py
python3 dist/deepseek-reviewer.pyz --help
```

There are no runtime Python package dependencies. Offline tests use synthetic commands/data, covering capture limits, fail-closed behavior, snapshot safety, exact invocation settings, installation, updates and rollback. The underlying Claude/DeepSeek workflow has completed autonomous synthetic and limited real-project reviews, including Keychain authentication. Those historical runs do not certify every new Mac or every future CLI/provider version. Distribution testing does not perform paid reviews. See [verification scope](docs/verification.md).

MIT licensed. Independent project; not affiliated with OpenAI, Anthropic or DeepSeek. Their software, services and terms remain separate.
