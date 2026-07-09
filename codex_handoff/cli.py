from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable


CODEX_DIRS = [
    pathlib.Path.home() / ".codex" / "sessions",
    pathlib.Path.home() / ".codex" / "archived_sessions",
]

TEXT_KEYS = {
    "content",
    "text",
    "message",
    "user_message",
    "assistant_message",
    "summary",
    "input",
    "output",
}

SYSTEM_TITLE_PREFIXES = (
    "You are Codex",
    "You are a coding agent",
    "You are MiMo",
    "You are ChatGPT",
)


@dataclass(frozen=True)
class SessionRecord:
    path: pathlib.Path
    mtime: float
    rows: list[dict[str, Any]]
    meta: dict[str, Any]

    @property
    def cwd(self) -> str:
        value = self.meta.get("cwd") or self.meta.get("working_directory") or self.meta.get("workspace") or ""
        return str(value)

    @property
    def provider(self) -> str:
        value = self.meta.get("model_provider") or self.meta.get("provider") or ""
        return str(value)


def iter_jsonl_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in CODEX_DIRS:
        if root.exists():
            files.extend(root.rglob("*.jsonl"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                rows.append({
                    "type": "_parse_error",
                    "line_no": line_no,
                    "raw": line[:500],
                })
    return rows


def get_meta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        if row.get("type") == "session_meta":
            payload = row.get("payload") or {}
            if isinstance(payload, dict):
                return payload
    return {}


def load_records() -> list[SessionRecord]:
    records: list[SessionRecord] = []
    for path in iter_jsonl_files():
        rows = load_jsonl(path)
        records.append(
            SessionRecord(
                path=path,
                mtime=path.stat().st_mtime,
                rows=rows,
                meta=get_meta(rows),
            )
        )
    return records


def contains_encrypted(obj: Any) -> bool:
    try:
        return "encrypted_content" in json.dumps(obj, ensure_ascii=False)
    except Exception:
        return False


def walk_text(obj: Any, out: list[str]) -> None:
    if isinstance(obj, dict):
        if "encrypted_content" in obj:
            return

        for key, value in obj.items():
            if key in TEXT_KEYS and isinstance(value, str):
                text = value.strip()
                if text:
                    out.append(text)
            else:
                walk_text(value, out)

    elif isinstance(obj, list):
        for item in obj:
            walk_text(item, out)


def compact_texts(texts: Iterable[str]) -> list[str]:
    seen = set()
    clean: list[str] = []

    for text in texts:
        text = text.strip()
        if len(text) < 2:
            continue

        key = text[:500]
        if key in seen:
            continue

        seen.add(key)
        clean.append(text)

    return clean


def looks_like_system_prompt(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith(SYSTEM_TITLE_PREFIXES)


def infer_title(rows: list[dict[str, Any]]) -> str:
    texts: list[str] = []

    for row in rows[:200]:
        walk_text(row, texts)

    compacted = compact_texts(texts)

    for text in compacted:
        if len(text) > 10 and not looks_like_system_prompt(text):
            return text.replace("\n", " ")[:100]

    for text in compacted:
        if len(text) > 10:
            return text.replace("\n", " ")[:100]

    return "(no readable title)"


def normalize_path(value: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(value).expanduser().resolve()


def path_matches(cwd: str, target: str | pathlib.Path) -> bool:
    if not cwd:
        return False

    target_text = str(target).strip()
    cwd_text = str(cwd).strip()

    if not target_text:
        return True

    if target_text.lower() in cwd_text.lower():
        return True

    try:
        cwd_path = normalize_path(cwd_text)
        target_path = normalize_path(target_text)
    except Exception:
        return False

    if cwd_path == target_path:
        return True

    try:
        cwd_path.relative_to(target_path)
        return True
    except ValueError:
        pass

    try:
        target_path.relative_to(cwd_path)
        return True
    except ValueError:
        return False


def filter_records(records: list[SessionRecord], repo: str | None = None, project: str | None = None) -> list[SessionRecord]:
    filtered = records

    if repo:
        filtered = [record for record in filtered if path_matches(record.cwd, repo)]

    if project:
        filtered = [record for record in filtered if path_matches(record.cwd, project)]

    return filtered


def print_record(index: int, record: SessionRecord) -> None:
    mtime = datetime.fromtimestamp(record.mtime).strftime("%Y-%m-%d %H:%M:%S")
    title = infer_title(record.rows)

    print(f"[{index}] {mtime}")
    print(f"    file: {record.path}")
    if record.cwd:
        print(f"    cwd : {record.cwd}")
    if record.provider:
        print(f"    provider: {record.provider}")
    print(f"    title: {title}")
    print()


def cmd_list(args: argparse.Namespace) -> int:
    records = load_records()

    if not records:
        print("No Codex session JSONL files found.")
        return 1

    records = filter_records(records, repo=args.repo, project=args.project)

    if not records:
        print("No Codex sessions matched the current filter.")
        if args.repo:
            print(f"Tried --repo: {normalize_path(args.repo)}")
        if args.project:
            print(f"Tried --project: {args.project}")
        print("Try: codex-handoff list --limit 200")
        print("Or:  codex-handoff list --project <folder-name-or-path> --limit 200")
        return 1

    for index, record in enumerate(records[: args.limit], 1):
        print_record(index, record)

    return 0


def format_row(row: dict[str, Any]) -> str:
    row_type = row.get("type", "unknown")
    payload = row.get("payload", row)

    encrypted = contains_encrypted(row)

    texts: list[str] = []
    walk_text(payload, texts)
    texts = compact_texts(texts)

    if not texts and encrypted:
        return f"## {row_type}\n\n[skipped encrypted_content]\n"

    if not texts:
        return ""

    body = "\n\n".join(texts)
    return f"## {row_type}\n\n{body}\n"


def export_session(path: pathlib.Path, out_path: pathlib.Path) -> None:
    rows = load_jsonl(path)
    meta = get_meta(rows)

    parts = [
        "# Codex Session Raw Export",
        "",
        f"- Source: `{path}`",
        f"- Exported at: `{datetime.now().isoformat(timespec='seconds')}`",
        "",
        "## Session Meta",
        "",
        "```json",
        json.dumps(meta, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Transcript",
        "",
    ]

    encrypted_count = 0
    readable_count = 0

    for row in rows:
        if contains_encrypted(row):
            encrypted_count += 1

        block = format_row(row)
        if block:
            readable_count += 1
            parts.append(block)

    parts.extend([
        "",
        "## Export Stats",
        "",
        f"- Total rows: {len(rows)}",
        f"- Readable rows: {readable_count}",
        f"- Rows containing encrypted_content: {encrypted_count}",
        "",
    ])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts), encoding="utf-8")


def run_git(repo: pathlib.Path, git_args: list[str]) -> str:
    try:
        proc = subprocess.run(
            ["git", *git_args],
            cwd=str(repo),
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return proc.stdout
    except Exception as exc:
        return f"[git command failed: {exc}]"


def git_root(repo: pathlib.Path) -> pathlib.Path | None:
    output = run_git(repo, ["rev-parse", "--show-toplevel"]).strip()
    if not output or output.startswith("fatal:") or output.startswith("[git command failed:"):
        return None
    return pathlib.Path(output)


def write_git_snapshot(repo: pathlib.Path, out_dir: pathlib.Path) -> None:
    root = git_root(repo)

    if root is None:
        message = f"Not a git repository: {repo}\n"
        (out_dir / "git_status.txt").write_text(message, encoding="utf-8")
        (out_dir / "git_diff.patch").write_text(message, encoding="utf-8")
        (out_dir / "git_log.txt").write_text(message, encoding="utf-8")
        return

    (out_dir / "git_status.txt").write_text(
        run_git(root, ["status", "--short", "--branch"]),
        encoding="utf-8",
    )

    (out_dir / "git_diff.patch").write_text(
        run_git(root, ["diff", "--stat"]) + "\n\n" + run_git(root, ["diff"]),
        encoding="utf-8",
    )

    (out_dir / "git_log.txt").write_text(
        run_git(root, ["log", "--oneline", "-30"]),
        encoding="utf-8",
    )


def make_handoff(session_path: pathlib.Path, repo: pathlib.Path, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path = out_dir / "CODEX_SESSION_RAW.md"
    export_session(session_path, raw_path)
    write_git_snapshot(repo, out_dir)

    handoff = f"""# HANDOFF

## Purpose

This directory was generated from a local Codex session and the current Git repository state. It is intended to let another model or coding agent continue the work without relying on the original Codex provider session.

## Files

1. `CODEX_SESSION_RAW.md` — readable text extracted from the Codex JSONL session.
2. `git_status.txt` — current Git status, or a clear note when the provided repo path is not a Git repository.
3. `git_diff.patch` — current uncommitted diff, when available.
4. `git_log.txt` — recent commit history, when available.

## Source

- Session: `{session_path}`
- Repository: `{repo}`
- Exported at: `{datetime.now().isoformat(timespec='seconds')}`

## Instructions for the next agent

1. Read `CODEX_SESSION_RAW.md`.
2. Read `git_status.txt`, `git_diff.patch`, and `git_log.txt`.
3. Do not assume the old session is complete. `[skipped encrypted_content]` means that part cannot be recovered by this tool.
4. Summarize the current goal, completed work, risks, and next three concrete actions before changing code.
5. Prefer the smallest working continuation over broad refactoring.
"""

    (out_dir / "HANDOFF.md").write_text(handoff, encoding="utf-8")


def resolve_auto_session(repo: pathlib.Path, project: str | None = None) -> pathlib.Path | None:
    records = load_records()
    filtered = filter_records(records, repo=str(repo), project=project)
    if filtered:
        return filtered[0].path
    return None


def cmd_export(args: argparse.Namespace) -> int:
    session = pathlib.Path(args.session).expanduser()
    out = pathlib.Path(args.out).expanduser()

    if not session.exists():
        print(f"Session file not found: {session}")
        return 1

    export_session(session, out)
    print(f"Exported: {out}")
    return 0


def cmd_make(args: argparse.Namespace) -> int:
    repo = pathlib.Path(args.repo).expanduser().resolve()
    out_dir = pathlib.Path(args.out_dir).expanduser()

    if not repo.exists():
        print(f"Repository path not found: {repo}")
        return 1

    if args.auto:
        session = resolve_auto_session(repo, project=args.project)
        if session is None:
            print("No matching Codex session found for this project.")
            print(f"Tried repo: {repo}")
            if args.project:
                print(f"Tried project filter: {args.project}")
            print("Try: codex-handoff list --repo . --limit 200")
            print("Or:  codex-handoff list --project <folder-name-or-path> --limit 200")
            return 1
        print(f"Auto-selected session: {session}")
    else:
        if not args.session:
            print("Session path is required unless --auto is used.")
            print("Try: codex-handoff make --auto --repo . --out-dir .agent_handoff")
            return 1
        session = pathlib.Path(args.session).expanduser()

    if not session.exists():
        print(f"Session file not found: {session}")
        return 1

    make_handoff(session, repo, out_dir)
    print(f"Generated handoff directory: {out_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="codex-handoff")
    sub = parser.add_subparsers(dest="cmd", required=True)

    parser_list = sub.add_parser("list", help="List recent local Codex JSONL sessions.")
    parser_list.add_argument("--limit", type=int, default=20)
    parser_list.add_argument("--repo", help="Only show sessions whose cwd matches this repo/path.")
    parser_list.add_argument("--project", help="Only show sessions whose cwd contains this project name/path.")
    parser_list.set_defaults(func=cmd_list)

    parser_export = sub.add_parser("export", help="Export one Codex session JSONL file to Markdown.")
    parser_export.add_argument("session")
    parser_export.add_argument("-o", "--out", default="CODEX_SESSION_RAW.md")
    parser_export.set_defaults(func=cmd_export)

    parser_make = sub.add_parser("make", help="Create a handoff directory from a session and repo state.")
    parser_make.add_argument("session", nargs="?")
    parser_make.add_argument("--auto", action="store_true", help="Auto-select the newest session matching --repo/--project.")
    parser_make.add_argument("--project", help="Optional project name/path filter when using --auto.")
    parser_make.add_argument("--repo", default=".")
    parser_make.add_argument("--out-dir", default=".agent_handoff")
    parser_make.set_defaults(func=cmd_make)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
