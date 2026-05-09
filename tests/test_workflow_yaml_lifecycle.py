"""Workflow restores lifecycle history files from gh-pages."""
from pathlib import Path


def test_workflow_restores_lifecycle_history_files():
    yml = Path(".github/workflows/daily-report.yml").read_text(encoding="utf-8")
    assert "history/lifecycle_history_us.json" in yml
    assert "history/lifecycle_history_kr.json" in yml
