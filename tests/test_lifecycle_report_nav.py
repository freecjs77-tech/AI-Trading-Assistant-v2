"""Lifecycle nav links surface in the main portfolio report."""
from pathlib import Path


def test_generate_report_accepts_lifecycle_kwargs():
    import inspect
    from report_generator import generate_report
    sig = inspect.signature(generate_report)
    assert "lifecycle_us" in sig.parameters
    assert "lifecycle_kr" in sig.parameters


def test_template_contains_lifecycle_nav_link():
    """Sanity: the sidebar partial (included in report_template) should reference
    lifecycle_us / kr nav links. The sidebar is a shared partial, so we check
    both report_template.html (for the include) and _sidebar.html (for the var)."""
    report_src = Path("templates/report_template.html").read_text(encoding="utf-8")
    sidebar_src = Path("templates/_sidebar.html").read_text(encoding="utf-8")
    # report_template should include the sidebar partial
    assert "_sidebar.html" in report_src
    # sidebar partial should wire lifecycle nav vars
    assert "lifecycle_us_page" in sidebar_src or "lifecycle_us" in sidebar_src
