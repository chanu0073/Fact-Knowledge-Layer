"""Deterministic, offline extractor used in ``sample`` mode.

It is deliberately generic — regex heuristics over evidence blocks, no
document/product-specific rules — so the full pipeline can run without any
API key and the test suite never spends tokens.
"""
from __future__ import annotations

import hashlib
import math
import re

from app.llm.base import EMBEDDING_DIM, EvidenceBlockSpec, ExtractedFact
from app.processing.parse import (
    detect_unit_and_currency,
    first_money,
    infer_entity,
    infer_observation_type,
    infer_period,
    strip_noise_prefix,
)

SKIP_METRICS = {"", "page number", "for the year ended"}

TOKEN_RE = re.compile(r"[a-z0-9]+")


class SampleEmbedder:
    """Deterministic offline embedder (hashing trick, signed random projection).

    Maps every alphanumeric token to a signed `EMBEDDING_DIM`-dim coordinate via md5. Text
    that shares tokens (e.g. the same metric in two documents) gets cosine
    neighbours, so offline candidate retrieval still works — degraded quality,
    same wiring.
    """
    name = "sample"
    dim = EMBEDDING_DIM
    batch_size = 500

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_embed_cached(t, self.dim) for t in texts]


def _embed_cached(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    for tok in TOKEN_RE.findall(text.lower()):
        d = hashlib.md5(tok.encode("utf-8")).digest()
        idx = int.from_bytes(d[:8], "big") % dim
        sign = 1.0 if (d[8] & 1) == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class SampleExtractor:
    name = "sample"

    @staticmethod
    def extractable(blocks: list[EvidenceBlockSpec]) -> list[EvidenceBlockSpec]:
        from app.processing.parse import has_number

        return [b for b in blocks if b.evidence_type == "table" or (has_number(b.content) and len(b.content) > 6)]

    async def extract(self, blocks: list[EvidenceBlockSpec]) -> list[ExtractedFact]:
        from app.processing.parse import has_number

        candidates = [b for b in blocks if b.evidence_type == "table" or (has_number(b.content) and len(b.content) > 6)]
        if not candidates:
            return []

        entity = infer_entity([b.content for b in blocks if b.evidence_type == "text"])
        facts: list[ExtractedFact] = []

        for block in candidates:
            content = block.content
            if block.evidence_type == "table":
                facts.extend(self._from_table(entity, block, content))
            else:
                f = self._from_text(entity, block, content)
                if f is not None:
                    facts.append(f)
        return facts

    # -- helpers -----------------------------------------------------------

    def _from_table(self, entity, block, content) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []
        unit, currency = detect_unit_and_currency(content)
        period = infer_period(content)
        period_raw = period["period_raw"]

        for line in content.splitlines():
            cells = [c.strip() for c in line.split("|")]
            cells = [c for c in cells if c]
            if len(cells) < 2:
                continue
            # First numeric cell (left to right) is the value; the cell to its
            # left (or the row's first cell) is the label.
            numeric_idx = -1
            value_cell = ""
            for i, c in enumerate(cells):
                if first_money(c)[0]:
                    numeric_idx = i
                    value_cell = c
                    break
            if numeric_idx < 0:
                continue
            label = cells[max(0, numeric_idx - 1)].strip()
            if not label:
                label = cells[0].strip()
            metric = strip_noise_prefix(label)
            if not metric or len(metric) > 90:
                continue

            raw_value = value_cell.strip()
            num, suffix = first_money(raw_value)
            numeric_value = None
            raw_value_num = (num[0] if num else "").replace(",", "").replace("−", "-")
            try:
                numeric_value = float(raw_value_num) if num else None
            except ValueError:
                numeric_value = None
            if numeric_value is None and not raw_value:
                continue

            value_type = "percent" if suffix and "%" in suffix else "absolute"
            is_percent = value_type == "percent"

            facts.append(ExtractedFact(
                entity=entity,
                metric=metric,
                definition="",
                raw_value=raw_value,
                numeric_value=numeric_value,
                unit=unit if not is_percent else "percent",
                currency=currency,
                value_type=value_type,
                period_raw=period_raw,
                period_type=period["period_type"],
                fiscal_year_label=period["fiscal_year_label"],
                observation_type=infer_observation_type(content + " " + metric),
                qualifiers={"grounding": "block", "extractor": "sample", "table_row": cells},
                confidence=0.6,
                source_block_indices=[block.index],
            ))
        return facts

    def _from_text(self, entity, block, content) -> ExtractedFact | None:
        from app.processing.parse import best_money, clean_number

        money, matched = best_money(content)
        if money is None or matched is None:
            return None
        num_token, suffix = money
        numeric_value = clean_number(num_token)

        num_pos = content.find(matched)
        head = strip_noise_prefix(content[:num_pos] if num_pos > 0 else "").strip()
        if not head:
            return None

        is_percent = bool(suffix and "%" in suffix)
        unit, currency = detect_unit_and_currency(content)
        period = infer_period(content)

        return ExtractedFact(
            entity=entity,
            metric=(head or matched)[:90],
            definition="",
            raw_value=matched.strip(),
            numeric_value=numeric_value,
            unit=unit if not is_percent else "percent",
            currency=currency,
            value_type="percent" if is_percent else "absolute",
            period_raw=period["period_raw"],
            period_type=period["period_type"],
            fiscal_year_label=period["fiscal_year_label"],
            observation_type=infer_observation_type(content),
            qualifiers={"grounding": "block", "extractor": "sample"},
            confidence=0.6,
            source_block_indices=[block.index],
        )