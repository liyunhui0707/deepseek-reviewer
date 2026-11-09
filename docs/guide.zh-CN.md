# 使用 DeepSeek Reviewer

本地工作流：**当前 Codex → Claude Code Restricted + DeepSeek → Findings 返回同一 Codex 会话**。DeepSeek 自主搜索、阅读你批准的文件；主 Codex 负责核实意见和运行本地测试。

## 一次安装

本页适用于 **v1.3.0**。请从发行列表选择标明 v1.3.0 的配套文件；旧版不一定支持下列全部命令。旧版用户可参考其[固定版本说明](https://github.com/liyunhui0707/deepseek-reviewer/blob/v1.0.0/docs/guide.zh-CN.md)及本页的升级步骤。

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

每组命令任一步失败即停止。Key 只在原生隐藏提示中输入，不发给 Codex。以后需要时允许对应 Keychain 单次读取，不选择 Always Allow。更换和撤销见[凭据说明](credentials.md)。`LOCAL_READY` 仅表示本地注册通过，不表示认证或本机真实调用已验证；同时查看 Skill 状态。Codex 会自动发现 Skill 更新；如果进行中的会话仍沿用旧指令，保存工作后退出，再在同一项目执行 `codex resume` 接续原会话即可，不用重新登录。见 [Codex 官方说明](https://learn.chatgpt.com/docs/build-skills)。

## 日常使用

安装后，在任意项目的 Codex 会话中说：**“用 DeepSeek 来审核下。”** 也可明确指定 `$deepseek-reviewer`。

Skill 负责告诉 Codex 如何调用，CLI 负责实际执行和保存报告。所有项目使用同一条 `~/.local/bin/deepseek-reviewer` 入口，不需要临时脚本或旧 audit 适配器。

Codex 会选定一项审查目标及相关文件，生成快照清单，补齐尚未明确的源码外发和费用授权，然后执行一次审查并把结果读回当前对话。同一已授权范围无需反复请示；范围变化、费用增加和主机审批仍需处理。

`--profile quick` 适合一个窄风险：180 秒、8 轮、4,000 输出 tokens 设置、US$0.25 客户端预算。`--profile standard` 保留原默认值；显式资源参数可覆盖档位。`--focus-file` 可优先查阅最多三份已经批准的文件。档位不是完成保证；材料较多时先缩小问题和补齐依赖，不自动提高预算。

默认每项任务为 300 秒、12 个 Agent 轮次、16,000 输出 tokens 设置、US$0.50 客户端预算。可在准备阶段显式调整，最高 600 秒、32 轮、64,000 tokens、US$2.00。轮次不是 HTTP 请求数，客户端估价不是实际账单硬上限。失败后不自动重启。

一份计划只能执行一次。`COMPLETED` 表示调用完成并取得报告，**不等于代码验收通过**；`PARTIAL` 表示有最终报告或可用阶段意见，但执行或证据不完整；`FAILED` 表示未取得可交付报告。主 Codex 应区分确认缺陷、待验证假设和可选建议，说明覆盖缺口。

Terminal 默认显示便于阅读的状态、已用/剩余时间、读取证据和结果摘要；供 Codex/脚本读取时默认 JSON，也可明确指定 `--json`。`--text` 可强制人类可读输出。没有新事件时只报告等待，不把沉默诊断为 Keychain 卡住。

Ctrl-C 或正常终止会清理子进程并保存失败报告。强制杀进程、断电可能来不及保存，但原任务仍不可重跑。用准备结果中的 `id` 读取已有报告，不产生费用：

```sh
~/.local/bin/deepseek-reviewer report --id 准备结果中的ID --text
```

新版 `partial_review` 保存模型明确输出且通过校验的最近一份结构化阶段意见，`findings` 保留最终报告。阶段意见仍需主 Codex 核实，不能视为审核通过。没有强制预留最终报告轮次；模型可能不输出阶段意见，强制杀死父进程或断电也可能来不及保存。不会从内部推理、工具正文或错误文字拼凑 Findings。

v1.3.0 统一使用包含审查结论、Findings、已阅读文件和覆盖缺口的结构化报告。只有成功结束时的最终结果通过内容、读取证据及执行安全校验，才标为 `COMPLETED`。裸 JSON、单个 `review-report` / `json` / 旧 `review-checkpoint` 代码块采用相同校验；标签不决定是否完成。前面的阶段意见不能替代缺失或无效的最终结果。预算、轮次、超时及异常退出仍属未完成；可用意见保存为 `PARTIAL`，`delivery=NONE` 表示没有交付意见。

后续修订被拒绝时，安全的较早意见会标记 `partial_review_stale=true`，不能冒充最新结论。`final_report_diagnostic` 保存固定的脱敏拒绝类别，供已有报告查询使用；不保存被拒绝正文、秘密片段或内部思考。旧报告及失败记录不变，**尚未执行的旧计划须重新 prepare 并核对授权，已消费任务不能重用**。

新版通过固定 Provider 配置明确请求关闭 thinking，与 effort 分开设置。一项获授权的小范围真实调用已返回有效最终报告、正常退出且未观察到 thinking 事件，详见[验收范围](verification.md)。这验证了该次交付，不保证每项任务都完成，也不代表模型意见正确或覆盖完整。原有时间、轮次、输出和预算保护保持不变，不自动续跑或增加付费调用。

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

## 从旧 audit 入口迁移

若 `doctor --json` 的 `conflicting_skills` 非空，先检查旧 `deepseek-review` Skill，经用户授权将它备份到 Skill 搜索目录之外，再使用产品 `deepseek-reviewer` Skill。不要删除历史项目，也不要让两个入口同时承担同一个触发词。产品 setup 不会自动覆盖定制旧 Skill。

旧私有工作流的 Keychain 项与本产品不同，不能当作产品已经完成认证。用户需在自己的 Terminal 用上述 `credentials save` 为本产品录入一次；无需在每个业务项目重复保存，也不要让 Codex 读取或搬运旧 Key。旧凭据项保持原样。
