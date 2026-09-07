"""Deterministic parser tests.

These exercise real files from the (local-only) docs/ datasets and skip
cleanly if they aren't present, so CI never hard-depends on them.
"""
from __future__ import annotations

import importlib.resources
from pathlib import Path

import pytest

from app.processing.pdf_parser import parse_pdf

DECK = Path(__file__).resolve().parents[2] / "docs" / "assignment files" / "starter-datasets" / "delhivery" / "03-delhivery-q4-fy24-earnings-presentation.pdf"
AR = Path(__file__).resolve().parents[2] / "docs" / "assignment files" / "starter-datasets" / "delhivery" / "02-delhivery-annual-report-fy24-excerpt.pdf"

needs_dataset = pytest.mark.skipif(
    not DECK.exists() or not AR.exists(),
    reason="local datasets not present",
)


def _tiny_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "tiny.pdf"
    p.write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \ntrailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n0\n%%EOF\n"
    )
    return p


def test_parse_tiny_pdf_empty_page(tmp_path):
    parsed = parse_pdf(_tiny_pdf(tmp_path))
    assert parsed.page_count == 1
    assert parsed.total_blocks == 0
    assert parsed.errors == []


@needs_dataset
def test_parse_earnings_deck():
    parsed = parse_pdf(DECK)
    assert parsed.page_count == 27
    assert parsed.total_blocks > 0
    assert len(parsed.text_blocks) > 0
    # Blocks are page-ordered and numbered per page.
    pages = [b.page_number for b in parsed.text_blocks]
    assert min(pages) >= 1 and max(pages) <= 27
    # At least one real revenue-ish string survives.
    blob = " ".join(b.content for b in parsed.text_blocks[:50]).lower()
    assert any(kw in blob for kw in ("revenue", "ebitda", "margin"))


@needs_dataset
def test_parse_annual_report_has_tables():
    parsed = parse_pdf(AR)
    assert parsed.page_count >= 90
    assert len(parsed.tables) > 0
    # Table cells keep pipe-joined structure.
    combined = "\n".join(t.content for t in parsed.tables)
    assert "|" in combined


def test_parse_missing_file_raises(tmp_path):
    from pathlib import Path as P

    with pytest.raises(FileNotFoundError):
        parse_pdf(tmp_path / "nope.pdf")