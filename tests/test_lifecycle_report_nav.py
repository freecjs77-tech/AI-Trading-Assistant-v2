"""Lifecycle nav links surface in the main portfolio report."""
from pathlib import Path


def test_generate_report_accepts_lifecycle_kwargs():
    import inspect
    from report_generator import generate_report
    sig = inspect.signature(generate_report)
    assert "lifecycle_us" in sig.parameters
    assert "lifecycle_kr" in sig.parameters


def test_template_contains_lifecycle_nav_link():
    """Sanity: report_template.html should reference lifecycle_us / kr when
    pages exist. We only check the template wires the var; rendering is
    integration-tested in the e2e suite."""
    src = Path("templates/report_template.html").read_text(encoding="utf-8")
    assert "lifecycle_us_page" in src or "lifecycle_us" in src
