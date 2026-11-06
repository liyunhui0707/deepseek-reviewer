# 使用 DeepSeek Reviewer

本地工作流：**当前 Codex → Claude Code Restricted + DeepSeek → Findings 返回同一 Codex 会话**。DeepSeek 自主搜索、阅读你批准的文件；主 Codex 负责核实意见和运行本地测试。

## 一次安装

需要 macOS、Python 3.11+、Codex，以及自行通过官方渠道安装的 Claude Code **2.1.312**。本软件不打包或修改这些工具。下载同一 [GitHub Release](https://github.com/liyunhui0707/deepseek-reviewer/releases/latest) 的 `deepseek-reviewer.pyz` 和 `SHA256SUMS`，在下载目录执行：

```sh
shasum -a 256 -c SHA256SUMS
python3 deepseek-reviewer.pyz install
~/.local/bin/deepseek-reviewer configure --claude "$HOME/.local/share/claude/versions/2.1.312"
~/.local/bin/deepseek-reviewer credentials save
~/.local/bin/deepseek-reviewer doctor
~/.local/bin/deepseek-reviewer install-skill
```

校验失败即停止；Claude 路径以你的实际安装为准。Key 只在独立 Terminal 的原生隐藏提示中输入，不发给 Codex。以后需要时允许对应 Keychain 单次读取，不选择 Always Allow。更换和撤销见[凭据说明](credentials.md)。原有同名 Skill 不会被覆盖。

## 日常使用

在能发现新 Skill 的 Codex 会话中说：**“用 DeepSeek 来审核下。”** 也可明确指定 `$deepseek-reviewer`。

Codex 会选定一项审查目标及相关文件，生成快照清单，补齐尚未明确的源码外发和费用授权，然后执行一次审查并把结果读回当前对话。同一已授权范围无需反复请示；范围变化、费用增加和主机审批仍需处理。

默认每项任务为 300 秒、12 个 Agent 轮次、16,000 输出 tokens 设置、US$0.50 客户端预算。可在准备阶段显式调整，最高 600 秒、32 轮、64,000 tokens、US$2.00。轮次不是 HTTP 请求数，客户端估价不是实际账单硬上限。失败后不自动重启。

一份计划只能执行一次。`COMPLETED` 表示调用完成并取得报告，**不等于代码验收通过**；`PARTIAL` 表示有报告但执行或证据不完整；`FAILED` 表示未取得可交付报告。主 Codex 应区分确认缺陷、待验证假设和可选建议，说明覆盖缺口。

## 跨项目与数据边界

通过 `prepare --root ... --file ...` 明确选择文件；不默认开放整个业务仓库。Git Diff 可先整理为经批准的文本文件，与关联源码一起选择。仅接收 UTF-8 普通文件，最多 50 个、合计 256 KiB。密钥路径、符号链接和硬链接被拒绝；敏感内容检查仍需要人的判断。

Restricted 是 Claude 的应用级控制，**不是 OS 沙箱**。实际源码和任务会发送到 DeepSeek 官方 Anthropic 兼容接口；你的组织必须允许这种外发。本地私有快照和报告会保留，可能含源码，不能提交到公开 Git。首次换 Mac、Claude 版本或企业策略需要重新核实兼容性。

## 更新

```sh
~/.local/bin/deepseek-reviewer check-update
~/.local/bin/deepseek-reviewer update
~/.local/bin/deepseek-reviewer rollback
```

只在主动操作时检查更新。更新核验 GitHub 发行校验值并保留上一版本；不更新 Claude/Codex、不更改全局 PATH。完整参数和维护说明见 [README](../README.md)。
