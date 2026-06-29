"""
Bank Layout Profiles
====================
Declarative per-bank knowledge for the geometry extractor.

Each bank's transaction layout is described by a *data* structure (Profile),
not bespoke parser code. The geometry_extractor uses the profile to know:
  - where the date column(s) sit (x0)
  - where the transaction-amount column right-edge is (x1)
  - whether there's a separate running-balance column (and where)
  - which summary keywords to filter out
  - which "total" fields the statement self-declares (for the reconciler)

Adding a new bank = adding one entry to PROFILES + its totals map. No new class.

When no profile matches a detected bank, the geometry extractor auto-detects
columns (see geometry_extractor.detect_columns) so unseen banks still work.

Coordinates are in PDF points (1/72 inch). Tolerances of ~4-8pt absorb
sub-pixel rendering and font-width variance, so exact values aren't critical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Profile:
    """Layout description for one bank's transaction pages."""

    bank: str
    # Right-edge (x1) of the transaction-amount column. The strongest signal.
    amount_column_x1: Optional[float] = None
    # Right-edge of the running-balance column, if the statement shows one.
    # (Navy Federal, some checking statements.) None = no balance column.
    balance_column_x1: Optional[float] = None
    # x0 of date column(s). Some statements show trans-date + post-date.
    date_columns: List[float] = field(default_factory=list)
    # Summary/header keyword phrases to filter as non-transactions.
    summary_keywords: List[str] = field(default_factory=list)
    # Map of logical total -> the label phrase the statement uses.
    # e.g. {"charges": "total transactions", "fees": "total fees", ...}
    # The reconciler reads the dollar figure that follows each phrase.
    totals_fields: Dict[str, str] = field(default_factory=dict)
    # Account type: "credit" (card statements) or "checking" (deposit accounts).
    # Drives sign handling: credit-card payments are credits (negated); checking
    # statements encode sign via the printed amount (trailing dash for debits).
    bank_type: str = "credit"
    # A coarse tolerance for matching x1 (overridden globally in the extractor).
    x_tolerance: float = 6.0


# ---------------------------------------------------------------------------
# Known bank profiles
# ---------------------------------------------------------------------------
# Values derived from real word-geometry inspection of the corpus (see plan).
# The extractor clusters x1 robustly, so these are hints, not exact matches.
PROFILES: Dict[str, Profile] = {
    "Capital One": Profile(
        bank="Capital One",
        amount_column_x1=588.0,
        date_columns=[45.0, 105.0],  # trans date, post date
        summary_keywords=[
            "previous balance", "new balance", "total transactions",
            "total fees", "total interest", "statement balance",
            "payments, credits and adjustments", "amount enclosed",
            "credit limit", "available credit",
        ],
        totals_fields={
            "charges": "total transactions",
            "fees": "total fees for this period",
            "interest": "total interest for this period",
            "previous_balance": "previous balance",
            "new_balance": "new balance",
        },
    ),
    "Bank of America": Profile(
        bank="Bank of America",
        amount_column_x1=560.0,
        date_columns=[28.0, 63.0],
        summary_keywords=[
            "previous balance", "new balance", "account summary",
            "total payments and other credits", "total purchases and other charges",
            "payments and other credits", "purchases and other charges",
            "interest charged", "fees charged",
        ],
        totals_fields={
            "previous_balance": "previous balance",
            "new_balance": "new balance",
        },
    ),
    "Chase": Profile(
        bank="Chase",
        amount_column_x1=486.0,
        date_columns=[26.6],
        summary_keywords=[
            "previous balance", "new balance", "statement balance",
            "total fees", "total interest", "minimum payment",
            "payment due", "past due", "cash advances", "fees charged",
            "interest charged", "payment, credits",
            "balance over the credit limit", "total interest for this period",
            "total fees charged in", "total interest charged in",
        ],
        totals_fields={
            # Per-period labels (NOT the YTD "Total X charged in YYYY" lines).
            # The same-line matcher picks the amount on the matching line.
            "fees": "fees charged",
            "interest": "interest charged",
            "previous_balance": "previous balance",
            "new_balance": "new balance",
        },
    ),
    "Citibank": Profile(
        bank="Citibank",
        amount_column_x1=386.0,
        date_columns=[40.0],
        summary_keywords=[
            "previous balance", "new balance", "total fees", "total interest",
            "amount enclosed", "minimum payment", "payment due", "credit limit",
            "costco cash", "rewards summary",
            # subtotal/section lines that previously leaked as transactions
            "new charges", "payments", "credits", "interest charged",
            "payments, credits and adjustments", "fees charged",
        ],
        totals_fields={
            "charges": "new charges",
            "fees": "total fees for this period",
            "interest": "total interest for this period",
            "previous_balance": "previous balance",
            "new_balance": "new balance",
        },
    ),
    "Navy Federal": Profile(
        bank="Navy Federal",
        amount_column_x1=473.0,   # transaction amount
        balance_column_x1=594.0,  # running balance
        date_columns=[14.4],
        bank_type="checking",     # sign via trailing dash, not card-payment logic
        summary_keywords=[
            "beginning balance", "ending balance", "available balance",
            "current balance", "total deposits", "total withdrawals",
            "total deposits and additions", "subtotal", "totals",
            "average daily balance",
        ],
        totals_fields={
            "ending_balance": "ending balance",
            "beginning_balance": "beginning balance",
        },
    ),
}


# ---------------------------------------------------------------------------
# Additional layouts for banks that emit MULTIPLE statement formats.
# Navy Federal is the canonical case: a checking statement (above) and a Visa
# credit-card statement have completely different layouts. Keyed separately so
# the geometry matcher can pick the right one per PDF.
# ---------------------------------------------------------------------------
EXTRA_LAYOUTS: Dict[str, List[Profile]] = {
    "Navy Federal": [
        # Checking layout (also kept in PROFILES for backward compat) — amount
        # column x1≈473, separate running-balance column at x1≈594, checking type.
        Profile(
            bank="Navy Federal",
            amount_column_x1=473.0,
            balance_column_x1=594.0,
            date_columns=[14.4],
            bank_type="checking",
            summary_keywords=[
                "beginning balance", "ending balance", "available balance",
                "current balance", "total deposits", "total withdrawals",
                "total deposits and additions", "subtotal", "totals",
                "average daily balance",
            ],
            totals_fields={
                "ending_balance": "ending balance",
                "beginning_balance": "beginning balance",
            },
        ),
        # Visa credit-card layout — single amount column at x1≈540 (no running
        # balance), credit-card prev/new-balance totals. (x1 derived from the
        # 2025-05 Visa statement investigation.)
        Profile(
            bank="Navy Federal",
            amount_column_x1=540.0,
            balance_column_x1=None,
            date_columns=[40.0],
            bank_type="credit",
            summary_keywords=[
                "previous balance", "new balance", "total fees", "total interest",
                "minimum payment", "payment due", "past due", "credit limit",
                "available credit", "total new activity", "total payments",
                "total payments and credits", "fees charged", "interest charged",
                "nfo payment", "cash advances",
            ],
            totals_fields={
                "charges": "total new activity",
                "previous_balance": "previous balance",
                "new_balance": "new balance",
                "fees": "fees charged",
                "interest": "interest charged",
            },
        ),
    ],
}


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------
def _all_profiles_for_bank(bank: str) -> List[Profile]:
    """All profiles for a bank (PROFILES entry + any EXTRA_LAYOUTS)."""
    out: List[Profile] = []
    if bank in PROFILES:
        out.append(PROFILES[bank])
    out.extend(EXTRA_LAYOUTS.get(bank, []))
    return out


def get_profile(bank: Optional[str]) -> Optional[Profile]:
    """Look up the DEFAULT profile by bank name. None if unknown.

    For banks with multiple layouts (see EXTRA_LAYOUTS), this returns the first
    (primary) one. Use get_profile_for_pdf() to match by geometry when a bank
    has more than one layout.
    """
    if not bank:
        return None
    # Exact, then case-insensitive, then substring.
    if bank in PROFILES:
        return PROFILES[bank]
    lower = bank.lower()
    for name, prof in PROFILES.items():
        if name.lower() == lower:
            return prof
    for name, prof in PROFILES.items():
        if name.lower() in lower or lower in name.lower():
            return prof
    return None


def get_profile_for_pdf(bank: Optional[str], pdf_path: Optional[str] = None,
                        text: Optional[str] = None) -> Optional[Profile]:
    """Match the right profile for a bank by inspecting the PDF's geometry.

    A bank may emit multiple statement layouts (e.g. Navy Federal checking vs
    Visa). We pick the profile whose amount_column_x1 best matches the actual
    amount-column cluster on the transaction pages. Falls back to the default
    profile (get_profile) when there's only one layout or no PDF to inspect.
    """
    if not bank:
        return None
    candidates = _all_profiles_for_bank(bank)
    if len(candidates) <= 1:
        return candidates[0] if candidates else get_profile(bank)

    # First try TEXT markers — the most reliable disambiguator. A checking
    # statement's text contains "Beginning Balance"/"Ending Balance"; a credit
    # statement contains "Previous Balance"/"New Balance". This avoids the
    # geometry trap where a checking statement's balance column (x1≈594) is more
    # populous than its amount column (x1≈473), which fooled the pure-geometry
    # matcher into picking the credit profile.
    #
    # IMPORTANT: the marker must appear on a line WITH a dollar amount (a real
    # total line). Markers also appear in legal disclosure prose (e.g. a Visa
    # statement's interest-calculation text mentions "beginning balance"), which
    # falsely triggered the checking match. Requiring an amount on the same line
    # distinguishes a real total from boilerplate.
    if text is None and pdf_path:
        text = _read_text(pdf_path)
    if text:
        import re as _re
        money_re = _re.compile(r"\$?\s*[\d,]+\.\d{2}")
        def _has_total_line(markers):
            """True if any line contains a marker AND a money token."""
            for line in text.splitlines():
                ll = line.lower()
                if any(m in ll for m in markers) and money_re.search(line):
                    return True
            return False
        for prof in candidates:
            # Checking statements declare Beginning/Ending Balance on a total line.
            if prof.bank_type == "checking" and _has_total_line(
                ["beginning balance", "ending balance"]
            ):
                return prof
            if prof.bank_type == "credit" and _has_total_line(
                ["previous balance", "new balance"]
            ):
                return prof

    # Fall back to geometry: inspect the PDF's amount-column x1 to disambiguate.
    detected_x1 = _detect_amount_x1(pdf_path, text)
    if detected_x1 is None:
        return candidates[0]  # can't disambiguate; default

    # Pick the candidate whose amount_column_x1 is closest to the detected one.
    best = min(candidates, key=lambda p: abs((p.amount_column_x1 or 0) - detected_x1))
    return best


def _read_text(pdf_path: str) -> Optional[str]:
    """Read a PDF's text layer (best-effort, for profile disambiguation)."""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception:
        return None


def _detect_amount_x1(pdf_path: Optional[str], text: Optional[str]) -> Optional[float]:
    """Find the dominant amount-column right-edge (x1) in the PDF's transaction
    pages. Used to disambiguate multi-layout banks. Returns None if unavailable.
    """
    if not pdf_path:
        return None
    try:
        import pdfplumber
        from .geometry_extractor import _looks_like_amount
        from collections import Counter

        best_x1 = None
        best_score = 0.0  # cluster share × count
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:6]:  # first 6 pages is plenty
                words = page.extract_words()
                amounts = [w for w in words if _looks_like_amount(w["text"])]
                if len(amounts) < 5:
                    continue
                counts = Counter(round(w["x1"]) for w in amounts)
                top_x1, top_n = counts.most_common(1)[0]
                share = top_n / len(amounts)
                # A real transaction page has a DOMINANT single column (>60% of
                # its amounts at one x1). A summary page scatters amounts across
                # many x positions (low share). Score by share × count so we pick
                # the columnar transaction page, not the busy summary page.
                score = share * top_n
                if score > best_score:
                    best_score = score
                    best_x1 = float(top_x1)
        return best_x1
    except Exception:
        return None


def auto_profile(page: Any, sample_rows: List[Any]) -> Optional[Profile]:
    """Build a generic Profile from auto-detected columns (for unseen banks).

    The geometry extractor already detected columns to produce `sample_rows`;
    we just package them into a Profile so downstream (reconciler) has a hook.
    """
    if not sample_rows:
        return None
    # Reuse the detected amount x1 from the first row.
    amount_x1 = getattr(sample_rows[0], "amount_x1", None)
    return Profile(
        bank="Unknown (auto-detected)",
        amount_column_x1=amount_x1,
        summary_keywords=[],  # rely on the universal list
        totals_fields={},
    )
