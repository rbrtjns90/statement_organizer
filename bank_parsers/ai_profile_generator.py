"""
AI-Assisted Profile Generator
=============================
Generates a layout Profile for an unknown bank by COMBINING two signals:

  1. AI VISION (semantic): the model identifies column ROLES ("Transaction
     Date", "Amount"), the date format, sign convention, and totals labels.
     The model is good at *meaning* but bad at *pixel measurement* (it rounds
     coordinates to neat fractions).

  2. GEOMETRY (precise): deterministic clustering of word x-coordinates
     measures the exact amount-column x1, date-column x0, and balance column.
     Geometry is good at *measurement* but can't tell what a column *means*.

Neither alone produces a usable profile. Together: the AI says "the rightmost
right-aligned column is the Amount", and geometry supplies its exact x1=588.

The generated profile can then be REFINED against reconciliation: if the
statement's totals don't balance, the profile is wrong somewhere, and we can
iterate (e.g. try the second-rightmost column as the amount).

This is how the system bootstraps support for a brand-new bank without a
hand-written profile.
"""

from __future__ import annotations

import base64
import io
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .ai_client import get_ai_client, extract_json
from .geometry_extractor import _looks_like_amount, _group_words_into_lines
from .layout_profiles import Profile


# ---------------------------------------------------------------------------
# AI semantic analysis
# ---------------------------------------------------------------------------
_ANALYSIS_PROMPT = """You are analyzing a bank statement page to identify its layout for automated extraction.

Look at the image carefully. Identify the transaction table's columns and report:
1. Each column's NAME and ALIGNMENT (left or right). Common names: "Transaction Date", "Post Date", "Description", "Amount", "Running Balance".
2. The date format (e.g. "Mon DD" for "Jan 21", "MM/DD/YYYY" for "01/21/2025").
3. The amount sign convention: how are debits/charges marked? (leading minus, trailing dash, parentheses, or unsigned with a separate column)
4. Whether there is a separate RUNNING BALANCE column (yes/no).
5. The exact label phrases used for statement TOTALS (e.g. "Total Transactions", "New Balance", "Previous Balance", "Total deposits and other credits"). List every total-like label you can read.
6. Account type: "credit" (credit card) or "checking" (deposit account).

Return ONLY valid JSON, no prose:
{
  "columns": [{"name": "Transaction Date", "alignment": "left"}, {"name": "Amount", "alignment": "right"}],
  "date_format": "Mon DD",
  "amount_sign": "leading minus",
  "has_running_balance": false,
  "totals_labels": ["Total Transactions", "New Balance"],
  "account_type": "credit"
}"""


@dataclass
class AILayoutAnalysis:
    """Semantic layout analysis from the vision model."""

    column_roles: List[Dict[str, str]]  # [{"name":..., "alignment":...}]
    date_format: str
    amount_sign: str
    has_running_balance: bool
    totals_labels: List[str]
    account_type: str  # "credit" or "checking"
    raw: Optional[dict] = None

    @property
    def bank_type(self) -> str:
        return "checking" if self.account_type == "checking" else "credit"

    @property
    def amount_is_right_aligned(self) -> bool:
        for c in self.column_roles:
            if "amount" in c.get("name", "").lower():
                return c.get("alignment", "right") == "right"
        return True


def analyze_layout_with_ai(image_b64: str) -> Optional[AILayoutAnalysis]:
    """Ask the vision model to semantically analyze a statement page's layout."""
    client = get_ai_client()
    if not client.available:
        return None
    try:
        resp = client.chat_vision(image_b64, _ANALYSIS_PROMPT, max_tokens=600, temperature=0)
        if not resp.success:
            return None
        data = extract_json(resp.text)
        if not isinstance(data, dict):
            return None
        return AILayoutAnalysis(
            column_roles=data.get("columns", []),
            date_format=data.get("date_format", ""),
            amount_sign=data.get("amount_sign", ""),
            has_running_balance=bool(data.get("has_running_balance", False)),
            totals_labels=data.get("totals_labels", []),
            account_type=data.get("account_type", "credit"),
            raw=data,
        )
    except Exception as exc:
        print(f"⚠️ AI layout analysis failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Geometry measurement
# ---------------------------------------------------------------------------
@dataclass
class MeasuredGeometry:
    """Precise column coordinates measured from word positions."""

    amount_x1: Optional[float] = None
    balance_x1: Optional[float] = None
    date_x0: Optional[float] = None
    page_width: float = 612.0
    has_balance_column: bool = False


def measure_geometry(words: List[Dict[str, Any]]) -> MeasuredGeometry:
    """Measure column x-coordinates from a page's words (deterministic)."""
    geo = MeasuredGeometry()
    if not words:
        return geo

    # Page width from the rightmost word.
    geo.page_width = max((w.get("x1", 0) for w in words), default=612.0)

    amounts = [w for w in words if _looks_like_amount(w.get("text", ""))]
    if not amounts:
        return geo

    # Cluster amount x1 values.
    bucket: Dict[int, List[float]] = {}
    for w in amounts:
        key = int(round(w["x1"] / 5.0)) * 5
        bucket.setdefault(key, []).append(w["x1"])
    clusters = sorted(
        ((sum(v) / len(v), len(v)) for v in bucket.values()),
        key=lambda c: c[0],
    )
    max_count = max((c[1] for c in clusters), default=0)
    significant = [c for c in clusters if c[1] >= max(2, int(0.15 * max_count))]

    if len(significant) == 1:
        geo.amount_x1 = significant[0][0]
    elif len(significant) >= 2:
        # Rightmost = balance, second-rightmost = amount (verified on NFCU).
        geo.amount_x1 = significant[-2][0]
        geo.balance_x1 = significant[-1][0]
        geo.has_balance_column = True

    # Date column: leftmost x0 on lines that have an amount.
    lines = _group_words_into_lines(words)
    date_x0s = []
    for line in lines:
        if any(_looks_like_amount(w.get("text", "")) for w in line):
            ws = sorted(line, key=lambda x: x.get("x0", 0))
            if ws:
                date_x0s.append(round(ws[0].get("x0", 0), 1))
    if date_x0s:
        # mode of the date x0s
        counts = Counter(date_x0s)
        geo.date_x0 = counts.most_common(1)[0][0]

    return geo


# ---------------------------------------------------------------------------
# Profile generation (the hybrid)
# ---------------------------------------------------------------------------
def generate_profile(
    ai: AILayoutAnalysis, geo: MeasuredGeometry, bank: str = "Unknown"
) -> Profile:
    """Combine AI semantic analysis + measured geometry into a Profile.

    AI supplies: date_format, sign convention, totals labels, bank_type,
    has_running_balance. Geometry supplies: exact amount_x1, balance_x1,
    date_x0. This is the only way to get a usable profile — the AI can't
    measure pixels, and geometry can't tell what a column means.
    """
    # Map AI totals labels to logical fields (best-effort keyword matching).
    totals_fields: Dict[str, str] = {}
    for label in ai.totals_labels:
        low = label.lower()
        if "total transaction" in low or "total new activity" in low or "new charges" in low or "total charges" in low:
            totals_fields.setdefault("charges", label.lower())
        elif "total fee" in low or "fees charged" in low:
            totals_fields.setdefault("fees", label.lower())
        elif "total interest" in low or "interest charged" in low:
            totals_fields.setdefault("interest", label.lower())
        elif "previous balance" in low:
            totals_fields.setdefault("previous_balance", label.lower())
        elif "new balance" in low or "statement balance" in low:
            totals_fields.setdefault("new_balance", label.lower())
        elif "ending balance" in low:
            totals_fields.setdefault("ending_balance", label.lower())
        elif "beginning balance" in low:
            totals_fields.setdefault("beginning_balance", label.lower())
        elif "deposits" in low and "credit" in low:
            totals_fields.setdefault("deposits", label.lower())
        elif "withdrawals" in low and "debit" in low:
            totals_fields.setdefault("withdrawals", label.lower())

    return Profile(
        bank=bank,
        amount_column_x1=geo.amount_x1,
        balance_column_x1=geo.balance_x1 if ai.has_running_balance else None,
        date_columns=[geo.date_x0] if geo.date_x0 is not None else [],
        bank_type=ai.bank_type,
        summary_keywords=[lbl.lower() for lbl in ai.totals_labels],
        totals_fields=totals_fields,
    )


# ---------------------------------------------------------------------------
# End-to-end: analyze a PDF and produce a profile
# ---------------------------------------------------------------------------
def generate_profile_for_pdf(
    pdf_path: str,
    page_index: int = -1,
    bank: str = "Unknown",
    ocr_words: Optional[List[List[Dict[str, Any]]]] = None,
) -> Tuple[Optional[Profile], Optional[dict]]:
    """Generate a Profile for a PDF by combining AI + geometry analysis.

    Args:
        pdf_path: path to the PDF.
        page_index: which page to analyze (-1 = auto-pick the densest txn page).
        bank: bank name for the profile.
        ocr_words: pre-fetched OCR words per page (for image-only PDFs). If
            None, native text-layer words are used.

    Returns (profile, diagnostics) where diagnostics has the raw AI + geometry.
    """
    import pdfplumber

    diagnostics: Dict[str, Any] = {}

    # --- Pick the transaction page (densest in amount-words) ---
    with pdfplumber.open(pdf_path) as pdf:
        # Get words per page (native or OCR).
        per_page_words: List[List[Dict[str, Any]]] = []
        for i, page in enumerate(pdf.pages):
            if ocr_words and i < len(ocr_words):
                per_page_words.append(ocr_words[i])
            else:
                try:
                    per_page_words.append(page.extract_words())
                except Exception:
                    per_page_words.append([])

        # Choose the page with the most amount-words (the transaction page).
        scores = [
            (i, sum(1 for w in ws if _looks_like_amount(w.get("text", ""))))
            for i, ws in enumerate(per_page_words)
        ]
        scores.sort(key=lambda s: s[1], reverse=True)
        if not scores or scores[0][1] < 3:
            return None, {"error": "no transaction page found"}
        chosen = page_index if page_index >= 0 else scores[0][0]
        page = pdf.pages[chosen]
        words = per_page_words[chosen]

        # --- Geometry measurement (deterministic) ---
        geo = measure_geometry(words)
        diagnostics["geometry"] = {
            "amount_x1": geo.amount_x1,
            "balance_x1": geo.balance_x1,
            "date_x0": geo.date_x0,
            "page_width": geo.page_width,
            "has_balance_column": geo.has_balance_column,
        }

        # --- AI semantic analysis ---
        # Render the chosen page to an image for the vision model.
        try:
            img = page.to_image(resolution=150).original
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            image_b64 = base64.b64encode(buf.getvalue()).decode()
        except Exception as exc:
            diagnostics["error"] = f"could not render page: {exc}"
            return None, diagnostics

        ai = analyze_layout_with_ai(image_b64)
        if ai is None:
            diagnostics["error"] = "AI analysis unavailable"
            # Fall back to a geometry-only profile (no totals/labels).
            ai = AILayoutAnalysis(
                column_roles=[], date_format="", amount_sign="",
                has_running_balance=geo.has_balance_column,
                totals_labels=[], account_type="credit",
            )
        diagnostics["ai"] = {
            "column_roles": ai.column_roles,
            "date_format": ai.date_format,
            "amount_sign": ai.amount_sign,
            "has_running_balance": ai.has_running_balance,
            "totals_labels": ai.totals_labels,
            "account_type": ai.account_type,
        }

        # --- Combine into a profile ---
        profile = generate_profile(ai, geo, bank=bank)
        diagnostics["profile"] = {
            "amount_column_x1": profile.amount_column_x1,
            "balance_column_x1": profile.balance_column_x1,
            "date_columns": profile.date_columns,
            "bank_type": profile.bank_type,
            "totals_fields": profile.totals_fields,
            "summary_keywords": profile.summary_keywords,
        }
        return profile, diagnostics
