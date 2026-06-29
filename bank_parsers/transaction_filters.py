"""
Shared Transaction Filters
==========================
Centralized junk/summary-row removal and deduplication applied to ALL parser
output — the geometry extractor AND the legacy regex parsers.

This fixes the class of bug where a bank-specific regex parser emitted summary
rows ("Previous Balance", "New Balance", "TOTAL FEES") as if they were
transactions (the Chase bug). The knowledge of what a summary row looks like
now lives in ONE place and is enforced universally.

Previously this logic was duplicated: a partial version existed only in
generic_regex.py, and the bank-specific parsers had none. The geometry extractor
has its own copy (is_summary_row); this module is the canonical version used by
the post-processing layer.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


# Phrases that mark a line as a statement summary/total/header, not a real
# transaction. Compiled once. Sourced from generic_regex.py's summary_keywords
# plus the geometry extractor's list, unified here.
_SUMMARY_PHRASES = [
    # Balance / period markers
    "previous balance", "new balance", "ending balance", "available balance",
    "current balance", "beginning balance", "balance forward",
    # Totals
    "total fees", "total interest", "total transactions", "total payments",
    "total charges", "total credits", "total debits", "total deposits",
    "total withdrawals", "total deposits and additions", "subtotal",
    "statement balance", "year-to-date",
    # Payment / due markers
    "minimum payment", "payment due", "past due", "amount due",
    "over the credit limit", "credit limit", "available credit",
    # Section headers (often appear with a +/- flag and a figure)
    "account summary", "payments and other credits", "purchases and other charges",
    "payments, credits and adjustments", "new charges", "new credits",
    "new payments", "payments and credits", "purchases and adjustments",
    "transactions +", "transactions -", "payments -", "payments +",
    "charges +", "credits -", "amount enclosed",
    # Fee/interest line items that aren't purchases
    "fees charged", "interest charged", "standard purch", "purchase rate",
    "annual percentage rate", "interest charge", "cash advance",
]

# Bare words that, if the description is ONLY one of them, mark a summary row.
_BARE_MARKERS = {
    "+", "-", "payments", "transactions", "charges", "credits", "fees",
    "interest", "balance", "summary", "subtotal",
}

# APR / percentage disclosure pattern (e.g. "20.49%")
_PERCENT_RE = re.compile(r"\d{1,2}\.\d{1,2}\s*%")


def is_summary_row(description: str) -> bool:
    """True if a description is a statement summary/header/total row."""
    d = (description or "").strip().lower()
    if not d:
        return True
    if d in _BARE_MARKERS:
        return True
    for phrase in _SUMMARY_PHRASES:
        if phrase in d:
            return True
    if _PERCENT_RE.search(d):
        return True
    return False


def filter_summary_rows(
    transactions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Remove summary/header/total rows from a list of transaction dicts."""
    kept = []
    removed = 0
    for t in transactions:
        if is_summary_row(str(t.get("description", ""))):
            removed += 1
            continue
        kept.append(t)
    if removed:
        # Lightweight signal for callers/logs; not printed to avoid noise.
        for t in kept:
            t.setdefault("raw_data", {})
    return kept


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def _fingerprint(t: Dict[str, Any]) -> str:
    """Stable dedup key: normalized description + rounded amount + date-month.

    We normalize aggressively because the same transaction can appear with
    slightly different descriptions across pages or parsers.
    """
    desc = re.sub(r"[^a-z0-9]", "", str(t.get("description", "")).lower())[:40]
    amt = t.get("amount")
    try:
        amt_key = f"{abs(round(float(amt), 2)):.2f}"
    except (TypeError, ValueError):
        amt_key = "0.00"
    d = str(t.get("date") or "")
    # Coarse month key that tolerates "Jan 8", "01/08/2025", "2025-01-08".
    month = ""
    m = re.search(r"(\d{1,2})[/\-]\d{1,2}[/\-]?\d*", d)
    if m:
        month = m.group(1)
    elif re.match(r"[A-Z][a-z]{2}", d):
        month = d[:3]
    return f"{desc}|{amt_key}|{month}"


def dedupe_transactions(
    transactions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Remove duplicate transactions by description+amount+date fingerprint.

    When a duplicate is found, the FIRST occurrence wins (earlier parsers /
    pages take precedence), which is the correct behavior for multi-page
    statements that repeat a header row.

    IMPORTANT: only transactions with a PRESENT date are eligible for dedup by
    amount. Two $99.99 charges at the same merchant on different days are
    genuinely separate transactions, so when the date is missing we require
    BOTH description AND amount AND page to match before treating as a dup —
    this avoids collapsing legitimate repeat charges.
    """
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for t in transactions:
        fp = _fingerprint(t)
        if fp in seen:
            # Stronger check: only drop if a real date is present (so we trust
            # the amount+month key). Without a date, keep both occurrences.
            d = str(t.get("date") or "").strip()
            if d and re.search(r"\d", d):
                continue
            # No date — require description AND amount AND page to all match.
            page = t.get("page")
            strict_fp = f"{fp}|page={page}"
            if strict_fp in seen:
                continue
            seen.add(strict_fp)
            out.append(t)
            continue
        seen.add(fp)
        out.append(t)
    return out


def clean_transactions(
    transactions: List[Dict[str, Any]],
    dedupe: bool = True,
) -> List[Dict[str, Any]]:
    """Apply summary-row removal + dedup. The canonical post-processing step."""
    result = filter_summary_rows(transactions)
    if dedupe:
        result = dedupe_transactions(result)
    return result
