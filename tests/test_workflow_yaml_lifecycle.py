"""Workflow restores lifecycle history files from gh-pages."""
from pathlib import Path


def test_workflow_restores_lifecycle_history_files():
    """The restore loop must include lifecycle history files by name.

    The earlier all-or-nothing chained checkout was replaced with a
    per-file loop so that a missing file (e.g. on first deploy when
    lifecycle_history_us.json doesn't exist on gh-pages yet) doesn't
    cascade into all other history files being skipped. The file
    basenames must still appear in the loop.
    """
    yml = Path(".github/workflows/daily-report.yml").read_text(encoding="utf-8")
    assert "lifecycle_history_us.json" in yml
    assert "lifecycle_history_kr.json" in yml


def test_workflow_uses_per_file_restore_loop():
    """Restore step iterates per-file so a missing file never blocks others."""
    yml = Path(".github/workflows/daily-report.yml").read_text(encoding="utf-8")
    # Per-file loop signature (bash for-loop body uses git checkout with $f).
    assert 'git checkout origin/gh-pages -- "history/$f"' in yml
