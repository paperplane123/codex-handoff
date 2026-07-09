# codex-handoff

将本地 Codex 会话上下文和当前 Git 仓库状态导出为可读的交接包，供其他模型或编码代理使用。

## 为什么需要这个工具

当切换提供商、账户或模型时，Codex 会话可能难以继续。此工具不会修改 Codex 状态，它只读取本地会话 JSONL 文件并将可读部分导出为 Markdown。

它的工作流程如下：

```text
旧的 Codex 会话 + 当前仓库状态
        ↓
.agent_handoff/
        ↓
新的模型 / 第三方代理继续任务
```

## 安装

从仓库根目录：

```bash
python3 -m pip install -e .
```

或者直接从 GitHub 安装：

```bash
python3 -m pip install git+https://github.com/paperplane123/codex-handoff.git
```

## 使用方法

列出最近的本地 Codex 会话：

```bash
codex-handoff list --limit 30
```

导出会话：

```bash
codex-handoff export "/path/to/session.jsonl" -o CODEX_SESSION_RAW.md
```

为当前仓库创建交接包：

```bash
codex-handoff make "/path/to/session.jsonl" --repo . --out-dir .agent_handoff
```

然后询问下一个代理：

```text
读取 .agent_handoff/HANDOFF.md 并继续项目。首先总结当前状态和下一步计划，然后再修改代码。
```

## 读取内容

- `~/.codex/sessions`
- `~/.codex/archived_sessions`
- 通过 `git status`、`git diff` 和 `git log` 获取当前 Git 仓库状态

## 限制

- 不会修改 Codex SQLite、rollout 文件、提供商元数据、身份验证或配置。
- 不会解密 `encrypted_content`。
- 只导出本地 JSONL 会话文件中找到的可读文本。
- 如果旧会话主要是加密的，导出的转录内容将不完整。

## 许可证

MIT
