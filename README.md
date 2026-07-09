# codex-handoff

Export readable local Codex session context and current Git repository state into a handoff package for another model or coding agent.

## Why

Codex sessions can become hard to continue when switching provider, account, or model. This tool does not modify Codex state. It only reads local session JSONL files and exports the readable parts into Markdown.

It is designed for this workflow:

```text
old Codex session + current repo state
        ↓
.agent_handoff/
        ↓
new model / third-party agent continues the task
```

## Install

From the repository root:

```bash
python3 -m pip install -e .
```

Or directly from GitHub:

```bash
python3 -m pip install git+https://github.com/paperplane123/codex-handoff.git
```

Upgrade an existing local clone:

```bash
git pull
python3 -m pip install -e .
```

## Usage

List recent local Codex sessions:

```bash
codex-handoff list --limit 30
```

List sessions for the current project/repo:

```bash
codex-handoff list --repo . --limit 100
```

List sessions by project folder name or path:

```bash
codex-handoff list --project "配电网仿真" --limit 100
```

Export a session:

```bash
codex-handoff export "/path/to/session.jsonl" -o CODEX_SESSION_RAW.md
```

Create a handoff package for the current repo from a known session:

```bash
codex-handoff make "/path/to/session.jsonl" --repo . --out-dir .agent_handoff
```

Auto-select the newest session matching the current repo:

```bash
codex-handoff make --auto --repo . --out-dir .agent_handoff
```

Auto-select by project folder name or path:

```bash
codex-handoff make --auto --project "配电网仿真" --repo . --out-dir .agent_handoff
```

Then ask the next agent:

```text
Read .agent_handoff/HANDOFF.md and continue the project. First summarize the current state and next steps before changing code.
```

## Matching behavior

`--repo` and `--project` match sessions by the `cwd` recorded in Codex session metadata.

A session matches when:

- its `cwd` equals the target path;
- its `cwd` is inside the target path;
- the target path is inside its `cwd`;
- or the target text appears in `cwd`, which helps with folder names like `配电网仿真`.

## What it reads

- `~/.codex/sessions`
- `~/.codex/archived_sessions`
- current Git repo state through `git status`, `git diff`, and `git log`

## Limitations

- It does not modify Codex SQLite, rollout files, provider metadata, auth, or config.
- It does not decrypt `encrypted_content`.
- It only exports readable text found in local JSONL session files.
- If the old session is mostly encrypted, the exported transcript will be incomplete.
- If the provided `--repo` is not a Git repository, Git snapshot files contain a clear `Not a git repository` note instead of raw fatal output.

## License

MIT

## 中文版本

中文版本请查看 [README_CN.md](README_CN.md)
