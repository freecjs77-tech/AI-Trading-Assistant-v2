"""generate_site copies lifecycle pages mirror portfolio_stops pattern."""
from pathlib import Path


def test_generate_site_copies_lifecycle_pages_block_present():
    src = Path("generate_site.py").read_text(encoding="utf-8")
    assert "lifecycle_*.html" in src
    assert "lifecycle pages" in src.lower()
