"""Regression guard — Archive nav links must remain removed from user-facing templates.

Spec: docs/superpowers/specs/2026-05-27-archive-nav-hide-design.md
"""
import os
import pytest

PROJECT_DIR = os.path.join(os.path.dirname(__file__), "..")
TEMPLATES_DIR = os.path.join(PROJECT_DIR, "templates")


# Templates that user-facing pages render or include. Each must NOT
# reference archive.html in a clickable nav element.
USER_FACING_TEMPLATES = [
    "_sidebar.html",
    "backtest_template.html",
    "trend_template.html",
    "scanner_unified_template.html",
    "scanner_template.html",
    "detail_template.html",
]


@pytest.mark.parametrize("template_name", USER_FACING_TEMPLATES)
def test_template_has_no_archive_nav_link(template_name):
    """User-facing templates must not contain an <a href="archive.html"> or similar."""
    path = os.path.join(TEMPLATES_DIR, template_name)
    with open(path, encoding="utf-8") as f:
        content = f.read()
    # Allow occurrences in comments / CSS / JS only — but href="archive.html"
    # or Archive>...</...> entries should be gone.
    assert 'href="archive.html"' not in content, (
        f"{template_name}: archive.html link still present"
    )
    # Korean button in scanner_template.html
    assert "📁 아카이브" not in content, (
        f"{template_name}: 📁 아카이브 button still present"
    )
    # nav_archive ctx default fallback (Pattern C in detail_template.html)
    assert "nav_archive|default('../archive.html')" not in content, (
        f"{template_name}: nav_archive default fallback still present"
    )
