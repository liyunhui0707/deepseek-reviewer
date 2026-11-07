# 使用 DeepSeek Reviewer

本地工作流：**当前 Codex → Claude Code Restricted + DeepSeek → Findings 返回同一 Codex 会话**。DeepSeek 自主搜索、阅读你批准的文件；主 Codex 负责核实意见和运行本地测试。

## 一次安装

本页适用于 **v1.1.0**。请从发行列表选择标明 v1.1.0 的配套文件；下列新增命令不能用于 v1.0.0。旧版用户可参考其[固定版本说明](https://github.com/liyunhui0707/deepseek-reviewer/blob/v1.0.0/docs/guide.zh-CN.md)及本页的升级步骤。

需要 macOS、Python 3.11+、Codex，以及自行通过官方渠道安装的 Claude Code **2.1.312**。本软件不打包或修改这些工具。下载同一 [GitHub Release](https://github.com/liyunhui0707/deepseek-reviewer/releases/latest) 的 `deepseek-reviewer.pyz` 和 `SHA256SUMS`，在下载目录执行：

```sh
/bin/sh -eu -c '
shasum -a 256 -c SHA256SUMS
python3 deepseek-reviewer.pyz install
~/.local/bin/deepseek-reviewer setup
'
```

`setup` 自动定位已安装的兼容 Claude、检查版本与能力、安装产品 Skill，不读取 Key，也不调用模型。找不到时使用 `setup --claude /完整路径/claude`；已有配置变化时停止并指明恢复步骤。可以重复运行，不覆盖定制 Skill。

然后只在自己的独立 Terminal 中录入一次凭据（已经保存过就跳过 `save`）：

```sh
/bin/sh -eu -c '
~/.local/bin/deepseek-reviewer credentials save
~/.local/bin/deepseek-reviewer doctor
'
```

每组命令任一步失败即停止。Key 只在原生隐藏提示中输入，不发给 Codex。以后需要时允许对应 Keychain 单次读取，不选择 Always Allow。更换和撤销见[凭据说明](credentials.md)。`LOCAL_READY` 仅表示本地注册通过，不表示认证或本机真实调用已验证；同时查看 Skill 状态。新 Codex 会话才能发现安装或更新后的 Skill。

## 日常使用

在能发现新 Skill 的 Codex 会话中说：**“用 DeepSeek 来审核下。”** 也可明确指定 `$deepseek-reviewer`。

Codex 会选定一项审查目标及相关文件，生成快照清单，补齐尚未明确的源码外发和费用授权，然后执行一次审查并把结果读回当前对话。同一已授权范围无需反复请示；范围变化、费用增加和主机审批仍需处理。

默认每项任务为 300 秒、12 个 Agent 轮次、16,000 输出 tokens 设置、US$0.50 客户端预算。可在准备阶段显式调整，最高 600 秒、32 轮、64,000 tokens、US$2.00。轮次不是 HTTP 请求数，客户端估价不是实际账单硬上限。失败后不自动重启。

一份计划只能执行一次。`COMPLETED` 表示调用完成并取得报告，**不等于代码验收通过**；`PARTIAL` 表示有报告但执行或证据不完整；`FAILED` 表示未取得可交付报告。主 Codex 应区分确认缺陷、待验证假设和可选建议，说明覆盖缺口。

Terminal 默认显示便于阅读的状态、已用/剩余时间、读取证据和结果摘要；供 Codex/脚本读取时默认 JSON，也可明确指定 `--json`。`--text` 可强制人类可读输出。没有新事件时只报告等待，不把沉默诊断为 Keychain 卡住。

Ctrl-C 或正常终止会清理子进程并保存失败报告。强制杀进程、断电可能来不及保存，但原任务仍不可重跑。用准备结果中的 `id` 读取已有报告，不产生费用：

```sh
~/.local/bin/deepseek-reviewer report --id 准备结果中的ID --text
```

报告明确区分成功 Read 的文件、未观察到成功 Read 的文件和真正的 Findings。Read 成功不能证明全文覆盖，模型意见仍由主 Codex 独立核实。

## 跨项目与数据边界

通过 `prepare --root ... --file ...` 明确选择文件；不默认开放整个业务仓库。Git Diff 可先整理为经批准的文本文件，与关联源码一起选择。仅接收 UTF-8 普通文件，最多 50 个、合计 256 KiB。密钥路径、符号链接和硬链接被拒绝；敏感内容检查仍需要人的判断。

Restricted 是 Claude 的应用级控制，**不是 OS 沙箱**。实际源码和任务会发送到 DeepSeek 官方 Anthropic 兼容接口；你的组织必须允许这种外发。本地私有快照和报告会保留，可能含源码，不能提交到公开 Git。首次换 Mac、Claude 版本或企业策略需要重新核实兼容性。

## 更新

从 v1.0.0 首次升级时，请下载并校验新版本，在没有审查运行时执行新包的 `python3 deepseek-reviewer.pyz install`。这样由新安装器迁移旧启动入口，保留注册、审查记录及回退版本。直接运行 v1.0.0 的 `update` 时，首次切换仍由旧安装器完成，不能把新版原子切换保护追溯到旧代码。迁移完成后使用：

```sh
~/.local/bin/deepseek-reviewer check-update
~/.local/bin/deepseek-reviewer update
~/.local/bin/deepseek-reviewer rollback
```

只在主动操作时检查更新。更新核验 GitHub 发行校验值并保留上一版本；不更新 Claude/Codex、不更改全局 PATH。完整参数和维护说明见 [README](../README.md)。

升级 CLI 后，用新版入口检查并显式更新 Skill：

```sh
~/.local/bin/deepseek-reviewer install-skill --check
~/.local/bin/deepseek-reviewer install-skill --update
```

仅更新未被用户修改的产品 Skill；有定制或未知文件时停止。更新前保留备份，可用 `install-skill --restore` 恢复，然后重开 Codex 会话。CLI 回退不会暗中改写 Skill。

## 遇到问题时

| 情况 | 应做的事 |
| --- | --- |
| 找不到兼容 Claude | 按官方说明准备受支持版本，使用 `setup --claude 路径`；本工具不替你安装或降级 |
| 注册的 Claude 路径/指纹变化 | 用 `configure --claude 路径 --check` 查看差异；确认后用 `--replace --expected-runtime-sha256 返回的current_sha256` 更新，原配置留有备份 |
| 需要恢复上次注册 | 用 `configure --restore --expected-runtime-sha256 当前配置哈希`；旧二进制必须仍存在且通过兼容检查 |
| 企业策略阻止运行 | 交由管理员核实兼容性，不关闭 Managed Policy 或 Restricted |
| `state_busy` | 等当前审查/维护结束，不删除锁文件；已消费审查不重启 |
| Skill 被定制或更新中断 | 保留定制文件；受管理的更新可用 `install-skill --restore` 恢复，不强行覆盖 |
| 轮次、预算或时间用完 | 先读报告与覆盖缺口，缩小下一次任务；扩大范围/额度或再付费调用须重新授权 |

首次在新 Mac 上的真实调用仍需单独授权；离线诊断不会测试 Key 是否有效，也不会产生模型费用。
