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


def test_workflow_restores_momentum_history_files():
    """워크플로우 시작 시 gh-pages에서 momentum history 4개 파일 복원."""
    yml = _read_workflow()
    momentum_files = (
        "scanner_momentum_us_history.json",
        "scanner_momentum_kr_history.json",
        "momentum_backtest_us.json",
        "momentum_backtest_kr.json",
    )
    for fname in momentum_files:
        assert fname in yml, f"missing restore for {fname}"


def test_workflow_restores_data_directory():
    """data/ 디렉토리도 복원 (sector ETF holdings 등)."""
    yml = _read_workflow()
    assert "data/" in yml or "data " in yml, "missing restore for data/ directory"


def test_workflow_uses_pull_rebase_before_push():
    """gh-pages push 전 pull --rebase 안전장치 (1a320422류 사고 재발 방지)."""
    yml = _read_workflow()
    # gh-pages 관련 push 근처에 pull --rebase 패턴
    assert (
        "pull --rebase" in yml or "rebase" in yml
    ), "missing pull --rebase safety guard before push"


def test_workflow_unchanged_secrets():
    """기존 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets 유지."""
    yml = _read_workflow()
    assert "TELEGRAM_BOT_TOKEN" in yml, "missing TELEGRAM_BOT_TOKEN secret"
    assert "TELEGRAM_CHAT_ID" in yml, "missing TELEGRAM_CHAT_ID secret"
