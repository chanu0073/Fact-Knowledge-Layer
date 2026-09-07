"""Deterministic PDF → block/table extraction.

Purpose: turn a PDF into coarse-grained *evidence blocks* (text runs and tables,
each with page number, order on the page, and page coordinates). This is the
provenance layer: later stages (LLM fact extraction) will reference these blocks
so every fact can point back to ``document + page + block``.

Libraries:
- PyMuPDF (``fitz``): fast text-block extraction with coordinates.
- pdfplumber: table extraction with cell boundaries.

Both are used because they are complementary (PyMuPDF is quick for text runs,
pdfplumber is precise for tables). No LLM is involved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber


@dataclass
class TextBlock:
    """A contiguous text run on a page."""
    page_number: int
    block_index: int
    x0: float
    y0: float
    x1: float
    y1: float
    content: str
    char_count: int = 0

    def to_evidence(self):
        return {
            "kind": "text",
            "bbox": {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1},
        }


@dataclass
class TableBlock:
    """A table extracted from a page (cells + coordinates)."""
    page_number: int
    block_index: int
    x0: float
    y0: float
    x1: float
    y1: float
    rows: list[list[str]] = field(default_factory=list)
    content: str = ""

    def to_evidence(self):
        return {
            "kind": "table",
            "bbox": {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1},
            "rows": self.rows,
        }


@dataclass
class ParsedDocument:
    page_count: int
    text_blocks: list[TextBlock]
    tables: list[TableBlock]
    errors: list[str] = field(default_factory=list)

    @property
    def total_blocks(self) -> int:
        return len(self.text_blocks) + len(self.tables)


def _clean_text(raw: str) -> str:
    """Normalise whitespace/newlines from PDF extraction."""
    if not raw:
        return ""
    text = raw.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _serialize_table(rows: list[list[str]]) -> str:
    """Table → pipe-joined text rows (readable + searchable)."""
    lines = []
    for row in rows:
        cells = [(_clean_text(c or "")) for c in row]
        lines.append(" | ".join(cells))
    return "\n".join(line for line in lines if line)


def parse_pdf(path: str | Path) -> ParsedDocument:
    """Parse a PDF into evidence blocks. Deterministic, no network/LLM."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    errors: list[str] = []
    text_blocks: list[TextBlock] = []
    tables: list[TableBlock] = []

    # Pdfplumber accessor; we iterate over pages interleaved with fitz.
    with pdfplumber.open(str(path)) as plumb:
        plumb_pages = list(plumb.pages)
        with fitz.open(str(path)) as doc:
            for pno, page in enumerate(doc, start=1):
                block_index = 0
                # --- text blocks (PyMuPDF) ---
                for block in page.get_text("blocks"):
                    x0, y0, x1, y1, raw, _bno, btype = block
                    if btype != 0:
                        continue  # images etc.
                    content = _clean_text(raw)
                    if not content:
                        continue
                    text_blocks.append(
                        TextBlock(
                            page_number=pno,
                            block_index=block_index,
                            x0=x0, y0=y0, x1=x1, y1=y1,
                            content=content,
                            char_count=len(content),
                        )
                    )
                    block_index += 1

                # --- tables (pdfplumber) ---
                ppt = plumb_pages[pno - 1] if pno <= len(plumb_pages) else None
                if ppt is not None:
                    try:
                        for found in ppt.find_tables() or []:
                            rows = [[("" if c is None else str(c)) for c in row] for row in found.extract()]
                            x0, top, x1, bottom = found.bbox
                            content = _serialize_table(rows)
                            if not content:
                                continue
                            tables.append(
                                TableBlock(
                                    page_number=pno,
                                    block_index=block_index,
                                    x0=x0, y0=top, x1=x1, y1=bottom,
                                    rows=rows,
                                    content=content,
                                )
                            )
                            block_index += 1
                    except Exception as exc:  # table parse can fail on odd layouts
                        errors.append(f"p{pno}: table parse error: {exc}")

    return ParsedDocument(
        page_count=len(plumb_pages),
        text_blocks=text_blocks,
        tables=tables,
        errors=errors,
    )