# macOS Keychain

The dedicated generic-password identity is:

- Service: `io.github.liyunhui0707.deepseek-reviewer`
- Account: `deepseek-reviewer`
- Keychain: your `~/Library/Keychains/login.keychain-db`

This product does not reuse Claude login items or import a previous private deployment's credentials. The registered Keychain path is checked against the current user's home.

Run these commands yourself in an interactive Terminal. Never append a key, export it, pipe it, paste it into a Codex conversation or include it in an issue:

```sh
# First enrollment; stops if the item already exists.
~/.local/bin/deepseek-reviewer credentials save

# Replace the key using the same native hidden prompt.
~/.local/bin/deepseek-reviewer credentials replace

# Delete only this product's local credential item.
~/.local/bin/deepseek-reviewer credentials remove
```

The native `security add-generic-password` prompt reads the key directly. The command checks the default Keychain's **path only** and uses `-T ""`; it never uses `-A`, a key argument, or a broad trusted-application entry. Cancel with Ctrl-C rather than submitting an empty key. After enrollment/replacement, inspect this item's Access Control in Keychain Access without showing the password: “Allow all applications” should be off and the always-allowed application list empty.

Only Claude's native `apiKeyHelper` runs the fixed lookup during an authorized review. The key goes to Claude's provider client, not the parent Reviewer CLI or Codex model. Helper stderr is suppressed. Raw environment, headers and tool results are not written to product reports. Claude can cache the key in memory; a helper failure may retain a cached value or placeholder. Do not assume helper failure guarantees zero HTTP requests.

Approve a matching macOS prompt with **Allow**, never **Always Allow**. Do not permanently trust `security`, Python or a shell. The credential name is not a security boundary against all other programs running as you. Managed Macs may need administrator review; the product does not change policy.

Stop active reviews before replacement/removal. Removing the local item does not revoke the remote API key or erase another process's memory. Revoke it separately in the DeepSeek account console if needed.

No real credential is read during `doctor`, `prepare`, installation, updates or the offline test suite.
