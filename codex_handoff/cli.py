from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
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


def infer_title(rows: list[dict[str, Any]]) -> str:
    texts: list[str] = []

    for row in rows[:80]:
        walk_text(row, texts)

    for text in compact_texts(texts):
        if len(text) > 10:
            return text.replace("\n", " ")[:100]

    return "(no readable title)"


def cmd_list(args: argparse.Namespace) -> int:
    files = iter_jsonl_files()

    if not files:
        print("No Codex session JSONL files found.")
        return 1

    for index, path in enumerate(files[: args.limit], 1):
        rows = load_jsonl(path)
        meta = get_meta(rows)
        stat = path.stat()

        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        cwd = meta.get("cwd") or meta.get("working_directory") or meta.get("workspace") or ""
        provider = meta.get("model_provider") or meta.get("provider") or ""
        title = infer_title(rows)

        print(f"[{index}] {mtime}")
        print(f"    file: {path}")
        if cwd:
            print(f"    cwd : {cwd}")
        if provider:
            print(f"    provider: {provider}")
        print(f"    title: {title}")
        print()

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


def make_handoff(session_path: pathlib.Path, repo: pathlib.Path, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_path = out_dir / "CODEX_SESSION_RAW.md"
    export_session(session_path, raw_path)

    (out_dir / "git_status.txt").write_text(
        run_git(repo, ["status", "--short", "--branch"]),
        encoding="utf-8",
    )

    (out_dir / "git_diff.patch").write_text(
        run_git(repo, ["diff", "--stat"]) + "\n\n" + run_git(repo, ["diff"]),
        encoding="utf-8",
    )

    (out_dir / "git_log.txt").write_text(
        run_git(repo, ["log", "--oneline", "-30"]),
        encoding="utf-8",
    )

    handoff = f"""# HANDOFF

## Purpose

This directory was generated from a local Codex session and the current Git repository state. It is intended to let another model or coding agent continue the work without relying on the original Codex provider session.

## Files

1. `CODEX_SESSION_RAW.md` — readable text extracted from the Codex JSONL session.
2. `git_status.txt` — current Git status.
3. `git_diff.patch` — current uncommitted diff.
4. `git_log.txt` — recent commit history.

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
    session = pathlib.Path(args.session).expanduser()
    repo = pathlib.Path(args.repo).expanduser().resolve()
    out_dir = pathlib.Path(args.out_dir).expanduser()

    if not session.exists():
        print(f"Session file not found: {session}")
        return 1

    if not repo.exists():
        print(f"Repository path not found: {repo}")
        return 1

    make_handoff(session, repo, out_dir)
    print(f"Generated handoff directory: {out_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="codex-handoff")
    sub = parser.add_subparsers(dest="cmd", required=True)

    parser_list = sub.add_parser("list", help="List recent local Codex JSONL sessions.")
    parser_list.add_argument("--limit", type=int, default=20)
    parser_list.set_defaults(func=cmd_list)

    parser_export = sub.add_parser("export", help="Export one Codex session JSONL file to Markdown.")
    parser_export.add_argument("session")
    parser_export.add_argument("-o", "--out", default="CODEX_SESSION_RAW.md")
    parser_export.set_defaults(func=cmd_export)

    parser_make = sub.add_parser("make", help="Create a handoff directory from a session and repo state.")
    parser_make.add_argument("session")
    parser_make.add_argument("--repo", default=".")
    parser_make.add_argument("--out-dir", default=".agent_handoff")
    parser_make.set_defaults(func=cmd_make)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
