"""Pre-commit guard: abort if any staged history/*.json loses dict keys vs HEAD.

Catches accidental data loss like 1a320422 (47 dates silently dropped from
portfolio_daily.json during a strategy.md commit).

Bypass:
  ALLOW_HISTORY_SHRINK=1 git commit ...
or include "[history-shrink-ok]" in the commit message (use --allow-empty-message
trick or amend after).
"""
import json
import os
import subprocess
import sys


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, encoding="utf-8", errors="replace")


def _staged_history_files() -> list[str]:
    out = _run(["git", "diff", "--cached", "--name-only", "--diff-filter=AM"])
    files = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("history/") and line.endswith(".json"):
            files.append(line)
    return files


def _load_staged(path: str):
    blob = _run(["git", "show", f":{path}"])
    return json.loads(blob)


def _load_head(path: str):
    try:
        blob = _run(["git", "show", f"HEAD:{path}"])
    except subprocess.CalledProcessError:
        return None  # new file
    return json.loads(blob)


def _real_keys(d: dict) -> set[str]:
    return {k for k in d.keys() if not k.startswith("_")}


def main() -> int:
    if os.environ.get("ALLOW_HISTORY_SHRINK") == "1":
        return 0

    files = _staged_history_files()
    if not files:
        return 0

    violations = []
    for path in files:
        try:
            staged = _load_staged(path)
        except (json.JSONDecodeError, subprocess.CalledProcessError):
            continue
        head = _load_head(path)
        if head is None:
            continue  # newly added file
        if not isinstance(staged, dict) or not isinstance(head, dict):
            continue  # only check dict-shaped histories

        head_keys = _real_keys(head)
        staged_keys = _real_keys(staged)
        removed = head_keys - staged_keys
        if removed:
            violations.append((path, sorted(removed), len(head_keys), len(staged_keys)))

    if not violations:
        return 0

    print("=" * 70, file=sys.stderr)
    print("ERROR: history JSON shrink detected (pre-commit guard)", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    for path, removed, before, after in violations:
        print(f"\n  {path}: {before} -> {after} keys ({len(removed)} removed)", file=sys.stderr)
        sample = removed[:10]
        print(f"    removed: {', '.join(sample)}" + (" ..." if len(removed) > 10 else ""), file=sys.stderr)
    print("\nIf this is intentional (e.g. cleaning bad data), bypass with:", file=sys.stderr)
    print("  ALLOW_HISTORY_SHRINK=1 git commit ...", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
