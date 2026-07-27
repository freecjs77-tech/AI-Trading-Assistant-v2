"""GitHub Actions workflow YAML validation."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _read_workflow():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        ".github",
        "workflows",
        "daily-report.yml",
    )
    return open(path, encoding="utf-8").read()


def test_workflow_restores_data_directory():
    """data/ 디렉토리도 복원 (sector ETF holdings 등)."""
    yml = _read_workflow()
    assert "data/" in yml or "data " in yml, "missing restore for data/ directory"


def test_workflow_uses_safe_gh_pages_push():
    """gh-pages push 안전장치 (1a320422류 데이터 손실 사고 재발 방지).

    본래 의도: force push 금지 + origin/gh-pages tip 기준 작업.
    구현 방식은 (a) pull --rebase 또는 (b) git worktree origin/gh-pages 둘 다 허용.
    """
    yml = _read_workflow()
    # 1) force push 금지
    assert "push --force" not in yml and "push -f " not in yml, (
        "force push detected — risks data loss like 1a320422"
    )
    # 2) origin/gh-pages tip 기반 작업
    has_worktree = "worktree add" in yml and "origin/gh-pages" in yml
    has_rebase = "pull --rebase" in yml or "rebase" in yml
    assert has_worktree or has_rebase, (
        "missing safety guard: must base on origin/gh-pages tip (worktree or rebase)"
    )


def test_workflow_unchanged_secrets():
    """기존 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets 유지."""
    yml = _read_workflow()
    assert "TELEGRAM_BOT_TOKEN" in yml, "missing TELEGRAM_BOT_TOKEN secret"
    assert "TELEGRAM_CHAT_ID" in yml, "missing TELEGRAM_CHAT_ID secret"
