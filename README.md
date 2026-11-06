# DeepSeek Reviewer

**An independent code-review agent, directly in your Codex conversation.**

Codex prepares a scoped review. Claude Code runs DeepSeek with read-only file tools. Findings return to the same Codex session for verification and action.

[Website](https://deepseek-reviewer.outerepoch3.chatgpt.site) · [Download v1.0.0](https://github.com/liyunhui0707/deepseek-reviewer/releases/tag/v1.0.0) · [中文使用说明](docs/guide.zh-CN.md) · [Security & privacy](SECURITY.md) · [Release notes](CHANGELOG.md)

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

## Install

Download `deepseek-reviewer.pyz` and `SHA256SUMS` from the **same GitHub Release**. In the directory containing the downloaded files:

```sh
shasum -a 256 -c SHA256SUMS
python3 deepseek-reviewer.pyz --version
python3 deepseek-reviewer.pyz install
```

Continue only if the checksum succeeds. Installation creates `~/.local/bin/deepseek-reviewer` and a versioned directory under `~/.local/share/deepseek-reviewer`. It needs no `sudo`, Python packages, daemon or shell-profile edits. Use the full command path below if `~/.local/bin` is not on your PATH.

Register your existing compatible executable, then enroll your key **in your own interactive Terminal**:

```sh
~/.local/bin/deepseek-reviewer configure --claude "$HOME/.local/share/claude/versions/2.1.312"
~/.local/bin/deepseek-reviewer credentials save
~/.local/bin/deepseek-reviewer doctor
~/.local/bin/deepseek-reviewer install-skill
```

Use the actual native executable path on your Mac if different. `configure` runs only version/help checks; `doctor` neither reads a key nor calls a model. `install-skill` adds only `~/.codex/skills/deepseek-reviewer` and refuses to overwrite an existing skill. Start a new Codex session to discover it. If you have an older similarly named personal review skill, choose this one explicitly until you resolve the overlap.

Keychain may display an access dialog during a review. Choose **Allow**, not **Always Allow**. Saving a key removes repeated key entry; it does not remove macOS consent. See [credential maintenance](docs/credentials.md).

## Use from Codex

Say:

> Use DeepSeek to independently review these changes.

Or:

> 用 DeepSeek 来审核下。

The Skill selects a focused task, prepares a manifest, confirms any missing source-disclosure/cost authorization, invokes one review, and reads the Findings in the same conversation. Authorization already provided for the same scope is reused. Host command approvals still apply.

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

## Limits and data

| Setting | Default | Maximum supported override |
| --- | ---: | ---: |
| Wall time, including Keychain wait | 300 seconds | 600 seconds |
| Agent turn setting | 12 | 32 |
| Client budget threshold | US$0.50 | US$2.00 |
| Output-token setting per call | 16,000 | 64,000 |
| Explicit snapshot | 50 files, 256 KiB total | fixed |
| Retained / raw stdout / JSONL record | 4 MiB / 64 MiB / 1 MiB | fixed |

`prepare --help` lists overrides. Low effort is the default; `--effort default` leaves native behavior unchanged. Model/provider behavior may differ from a requested setting. Agent turns are **not HTTP requests**. Native retries/continuations may occur. Claude's cost estimate is **not DeepSeek's invoice or a hard billing cap**. Actual request count and provider charges can remain unknown.

Only the selected snapshot and task are intended for the fixed `deepseek-flash[1m]` route at `https://api.deepseek.com/anthropic`. No runtime data is sent to this project's website. Local snapshots, settings and reports live in a private per-user application directory and are retained for your inspection; they are not automatically deleted or uploaded. They can contain source. Do not commit or share them without review.

Restricted/safe-mode, Read/Glob/Grep, empty MCP, clean environment and separate configuration directories are **application-level restrictions, not an OS sandbox**. Common managed-policy files cause a stop for manual compatibility review. A clean configuration namespace can still cause macOS Keychain queries in that namespace. Read [the complete security boundary](SECURITY.md) before reviewing confidential code.

## Update and rollback

```sh
~/.local/bin/deepseek-reviewer check-update
~/.local/bin/deepseek-reviewer update
~/.local/bin/deepseek-reviewer rollback
```

Updates are user-triggered. The CLI fetches release metadata and the archive from this GitHub repository, enforces HTTPS/host/size checks, verifies SHA-256, and retains the previous version. It does not update Claude or Codex. Checksums protect transfer integrity; they are not independent signatures against a compromised release publisher.

To uninstall, stop active reviews, optionally run `credentials remove`, then move only `~/.local/bin/deepseek-reviewer`, `~/.local/share/deepseek-reviewer` and `~/.codex/skills/deepseek-reviewer` to Trash using Finder. The application directory contains local review evidence; export any records you want to retain first. This does not remove Claude, Codex or unrelated credentials.

## Development and verification

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 scripts/build.py
python3 dist/deepseek-reviewer.pyz --help
```

There are no runtime Python package dependencies. Offline tests use synthetic commands/data, covering capture limits, fail-closed behavior, snapshot safety, exact invocation settings, installation, updates and rollback. The underlying Claude/DeepSeek workflow has completed autonomous synthetic and limited real-project reviews, including Keychain authentication. Those historical runs do not certify every new Mac or every future CLI/provider version. Distribution testing does not perform paid reviews. See [verification scope](docs/verification.md).

MIT licensed. Independent project; not affiliated with OpenAI, Anthropic or DeepSeek. Their software, services and terms remain separate.
