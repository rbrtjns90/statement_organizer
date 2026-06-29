"""
Geometry-First Extractor
========================
Deterministic transaction extraction based on PDF word *geometry*, not regex.

WHY THIS EXISTS
---------------
The previous per-bank parsers used line-based regex on the raw text layer. That
approach is fragile: it depends on pdfplumber joining words into the exact
string the regex expects, and it cannot reliably separate a transaction amount
from a running balance that happens to sit on the same line.

The investigation showed these statements are borderless (pdfplumber's
extract_tables() returns nothing), BUT transaction amounts reliably
right-align at fixed x-coordinates per bank:

    Capital One: amount   x1 ~ 587.5  (single column)
    Bank of America:      x1 ~ 559    (single column)
    Chase:                x1 ~ 485    (single column, debits negative)
    Citibank:             x1 ~ 386    (single column, mixed w/ side panel)
    Navy Federal: amount  x1 ~ 472 + running balance x1 ~ 594 (TWO columns)

So the robust primitive is: reconstruct physical lines from word `top`
coordinates, cluster the amount-like words by their right edge (x1), identify
which cluster is the *transaction amount* vs the *running balance*, and pull
the date + description from the left region. This is bank-agnostic at the core;
per-bank knowledge lives only in a lightweight Profile (see layout_profiles.py).

The output (RawRow) is then handed to the reconciler (reconciler.py) which
checks sum(amounts) against the statement's stated totals — the real
correctness gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Re-exported so callers don't import Profile directly when they don't need to.
from .layout_profiles import Profile, get_profile, auto_profile


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class RawRow:
    """A candidate transaction line reconstructed from geometry."""

    date: Optional[str]  # raw date string as it appears, pre-parse
    description: str
    amount: Optional[float]
    line_top: float  # y-coordinate of the line (for ordering / debugging)
    amount_x1: Optional[float] = None  # right-edge x of the amount (provenance)
    running_balance: Optional[float] = None  # per-row balance (checking accounts)
    account: Optional[str] = None  # account section identifier (multi-account stmts)
    raw_text: str = ""
    page: int = 1
    source: str = "geometry"
    raw_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "description": self.description,
            "amount": self.amount,
            "page": self.page,
            "source": self.source,
            "line_top": self.line_top,
            "amount_x1": self.amount_x1,
            "raw_data": self.raw_data,
        }


# ---------------------------------------------------------------------------
# Line reconstruction from geometry
# ---------------------------------------------------------------------------
# A "word" from pdfplumber.extract_words() is a dict with keys:
#   text, x0, x1, top, bottom, etc. We group words that share the same vertical
# band (top within a tolerance) into a physical line.
LINE_TOLERANCE = 3.0  # points; words within this vertical band are one line


def _group_words_into_lines(words: List[Dict[str, Any]], tol: float = LINE_TOLERANCE) -> List[List[Dict[str, Any]]]:
    """Group words on the same horizontal line by their `top` coordinate."""
    if not words:
        return []
    # Sort by top, then x0.
    ordered = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_top: Optional[float] = None
    for w in ordered:
        if current_top is None or abs(w["top"] - current_top) <= tol:
            current.append(w)
            if current_top is None:
                current_top = w["top"]
        else:
            lines.append(sorted(current, key=lambda x: x["x0"]))
            current = [w]
            current_top = w["top"]
    if current:
        lines.append(sorted(current, key=lambda x: x["x0"]))
    return lines


# ---------------------------------------------------------------------------
# Amount / date detection helpers
# ---------------------------------------------------------------------------
_AMOUNT_RE = re.compile(r"^-?\(?[\d,]+\.\d{1,2}\)?$|^-?\$?[\d,]+\.\d{1,2}$")


def _looks_like_amount(text: str) -> bool:
    """True if a word is an amount token: digits with a 2-decimal place."""
    t = text.replace("$", "").replace(",", "").replace("(", "").replace(")", "")
    # Allow trailing '-' (Navy Federal convention: '1,297.05-') or leading '-'.
    t = t.lstrip("-").rstrip("-")
    if not t:
        return False
    return bool(re.fullmatch(r"\d+\.\d{1,2}", t))


def _parse_amount(text: str) -> Optional[float]:
    """Parse an amount token to a float, preserving sign conventions."""
    t = text.strip()
    negative = False
    # Parenthesized negatives: (12.34) -> -12.34
    if t.startswith("(") and t.endswith(")"):
        negative = True
        t = t[1:-1]
    # Trailing dash: 12.34- -> -12.34 (Navy Federal)
    if t.endswith("-"):
        negative = True
        t = t[:-1]
    # Leading dash / minus
    if t.startswith("-"):
        negative = True
        t = t[1:]
    t = t.replace("$", "").replace(",", "").strip()
    try:
        val = float(t)
    except ValueError:
        return None
    return -val if negative else val


_DATE_PATTERNS = [
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$"),  # 12/30/2021
    re.compile(r"^\d{1,2}/\d{1,2}$"),          # 12/30
    re.compile(r"^\d{1,2}-\d{1,2}-\d{2,4}$"),  # 07-24-2024
    re.compile(r"^\d{1,2}-\d{1,2}$"),          # 07-24
    re.compile(r"^[A-Z][a-z]{2}\s*\d{1,2}$"),  # Jan 21 (single token)
]
# Month-name token (Capital One uses "Jan 8" as TWO separate words). Restricted
# to ACTUAL month abbreviations — the previous r"^[A-Z][a-z]{2}$" matched any
# 3-letter capitalized word (e.g. "New", "Due"), which caused "New Balance" to
# be parsed as a date and leak the new-balance total in as a fake transaction.
_MONTH_NAMES = {
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}
_DAY_RE = re.compile(r"^\d{1,2}$")


def _looks_like_date(text: str) -> bool:
    return any(p.match(text.strip()) for p in _DATE_PATTERNS)


def _is_date_token(text: str) -> bool:
    """A single token that could be part of a date: '12/30', 'Jan', '8', '07-24'."""
    t = text.strip()
    if _looks_like_date(t):
        return True
    # standalone month abbreviations (Capital One style "Jan 8") and bare day
    # numbers. Month matching is restricted to real month names so words like
    # "New"/"Due"/"Net" aren't misread as dates.
    if t.lower() in _MONTH_NAMES:
        return True
    if _DAY_RE.match(t):
        return True
    return False


# ---------------------------------------------------------------------------
# Column detection (the core of the geometry approach)
# ---------------------------------------------------------------------------
@dataclass
class ColumnPlan:
    """Result of analyzing a page's amount-column layout."""

    amount_x1: Optional[float]  # right edge of the TRANSACTION amount column
    balance_x1: Optional[float] = None  # right edge of running-balance column (if any)
    method: str = "unknown"  # how we decided (profile / mode / multi-col)

    def column_for(self, x1: float, tol: float = 4.0) -> str:
        """Classify a word's x1 as 'amount', 'balance', or 'other'."""
        if self.amount_x1 is not None and abs(x1 - self.amount_x1) <= tol:
            return "amount"
        if self.balance_x1 is not None and abs(x1 - self.balance_x1) <= tol:
            return "balance"
        return "other"


def detect_columns(
    amount_words: List[Dict[str, Any]],
    profile: Optional[Profile] = None,
) -> ColumnPlan:
    """Determine which x1 cluster is the transaction-amount column.

    Priority:
      1. Profile override (known banks).
      2. Auto-detection: cluster x1 values; if one dominant cluster, that's it;
         if multiple, the second-rightmost is the transaction amount (rightmost
         is the running balance).
    """
    # 1. Profile override
    if profile is not None and profile.amount_column_x1 is not None:
        return ColumnPlan(
            amount_x1=profile.amount_column_x1,
            balance_x1=profile.balance_column_x1,
            method="profile",
        )

    if not amount_words:
        return ColumnPlan(amount_x1=None, method="none")

    # 2. Cluster x1 values (1D, ~5pt buckets)
    clusters: List[Tuple[float, int]] = []  # (center, count)
    bucket: Dict[int, List[float]] = {}
    for w in amount_words:
        key = int(round(w["x1"] / 5.0)) * 5
        bucket.setdefault(key, []).append(w["x1"])
    for key, vals in bucket.items():
        center = sum(vals) / len(vals)
        clusters.append((center, len(vals)))
    clusters.sort(key=lambda c: c[0])  # left -> right

    # Keep only clusters with a meaningful share (>=15% of max count).
    if not clusters:
        return ColumnPlan(amount_x1=None, method="none")
    max_count = max(c[1] for c in clusters)
    significant = [c for c in clusters if c[1] >= max(2, int(0.15 * max_count))]

    if len(significant) == 1:
        return ColumnPlan(amount_x1=significant[0][0], method="mode")

    if len(significant) == 0:
        return ColumnPlan(amount_x1=None, method="none")

    # Multiple columns: rightmost is the running balance, second-rightmost is
    # the transaction amount. (Verified on Navy Federal: 472 = amount, 594 = balance.)
    significant.sort(key=lambda c: c[0])
    if len(significant) >= 2:
        return ColumnPlan(
            amount_x1=significant[-2][0],
            balance_x1=significant[-1][0],
            method="multi-col",
        )
    # Only fell through because of edge rounding; treat the lone cluster as amount.
    return ColumnPlan(amount_x1=significant[0][0], method="mode")


# ---------------------------------------------------------------------------
# Line parsing
# ---------------------------------------------------------------------------
def parse_line(
    line_words: List[Dict[str, Any]],
    columns: ColumnPlan,
    profile: Optional[Profile] = None,
) -> Optional[RawRow]:
    """Parse one physical line into a RawRow, or None if it isn't a transaction.

    A transaction line must have: at least one amount word in the 'amount'
    column, and a non-empty description. Date is taken from the leftmost date-
    looking words (or the profile's date columns).
    """
    if not line_words:
        return None

    # Find the amount word(s) in the detected amount column.
    amount_word: Optional[Dict[str, Any]] = None
    for w in line_words:
        if _looks_like_amount(w["text"]) and columns.column_for(w["x1"]) == "amount":
            amount_word = w
            break

    if amount_word is None:
        return None  # no transaction amount on this line

    amount = _parse_amount(amount_word["text"])
    if amount is None:
        return None

    # Sign convention: classify payments/credits vs purchases.
    # On a credit-card statement, a PAYMENT to the card is a credit (reduces the
    # balance), even though it prints as a positive number. A reconciler that
    # compares sum(charges) to "Total Transactions" will catch this if we get it
    # wrong, but we can fix the common cases here deterministically.
    # NOTE: only apply this for CREDIT-CARD profiles. Checking accounts encode
    # sign via the printed amount (trailing dash for debits); applying the card
    # logic there would wrongly negate genuine deposits whose description happens
    # to contain "Credit" (e.g. Navy Federal "POS Credit Adjustment").
    bank_type = getattr(profile, "bank_type", "credit") if profile else "credit"
    if bank_type == "credit":
        desc_preview = " ".join(w["text"] for w in sorted(line_words, key=lambda x: x["x0"])).upper()
        # Payment markers must be SPECIFIC phrases (whole-word-ish), not bare
        # substrings. A bare "PAYMENT" matches ACH descriptors like "DES:PAYMENT"
        # (BofA checking) which are NOT card payments — they're incoming deposits.
        payment_markers = (
            "PAYMENT THANK YOU", "PAYMENT RECEIVED", "PYMT ", "AUTOPAY",
            "AUTO-PMT", "AUTO PMT", "CAPITAL ONE MOBILE PYMT",
            "REFUND", "CREDIT ADJUSTMENT", "STATEMENT CREDIT",
            "NFO PAYMENT", "ONLINE PAYMENT FROM",
        )
        is_payment = any(m in desc_preview for m in payment_markers)
        if is_payment and amount > 0:
            amount = -amount  # payments/credits are negative

    # Date: prefer the FIRST profile date column (transaction date). We also
    # CONSUME the second date column's tokens (post-date) so they don't leak
    # into the description, but only the first date is returned as `date_str`.
    # Handles multi-token dates ("Jan 8" = two words) by collecting contiguous
    # date-component tokens near the column.
    date_str: Optional[str] = None
    date_token_words: List[Dict[str, Any]] = []  # ALL date words consumed (incl. post-date)
    if profile is not None and profile.date_columns:
        for col_idx, col_x in enumerate(profile.date_columns):
            sorted_left = sorted([w for w in line_words if w["x0"] < amount_word["x0"]],
                                 key=lambda x: x["x0"])
            parts = []
            started = False
            for w in sorted_left:
                if abs(w["x0"] - col_x) <= 30 and _is_date_token(w["text"]):
                    parts.append(w["text"])
                    date_token_words.append(w)
                    started = True
                elif started:
                    # allow adjacent continuation (e.g. "Jan"+"8")
                    last = date_token_words[-1]
                    if w["x0"] - last["x1"] <= 12 and _is_date_token(w["text"]):
                        parts.append(w["text"])
                        date_token_words.append(w)
                    else:
                        break
            # only the FIRST date column's tokens become the returned date
            if col_idx == 0 and parts:
                date_str = " ".join(parts)
    if date_str is None:
        # fallback: first contiguous run of date-component words at the far left.
        # Also consume any SECOND adjacent date run (post-date) to keep it out
        # of the description.
        left = [w for w in line_words if w["x0"] < amount_word["x0"]]
        parts = []
        runs = 0
        in_run = False
        for w in sorted(left, key=lambda x: x["x0"]):
            if _is_date_token(w["text"]) and w["x0"] < 200:
                parts.append(w["text"])
                date_token_words.append(w)
                in_run = True
            elif in_run:
                runs += 1
                in_run = False
                if runs >= 2:
                    break
                # allow a gap then a second date run (post-date)
                if w["x0"] < 200 and _is_date_token(w["text"]):
                    parts.append(w["text"])
                    date_token_words.append(w)
        # take only the first run as the date
        if parts:
            # split into runs by gap; first run = date
            first_run = []
            prev = None
            for w in sorted(date_token_words, key=lambda x: x["x0"]):
                if prev is not None and w["x0"] - prev["x1"] > 20:
                    break
                first_run.append(w["text"])
                prev = w
            date_str = " ".join(first_run) if first_run else " ".join(parts)

    # Description: everything between the date and the amount, excluding balance.
    # We drop words consumed as the date (tracked precisely), balance-column
    # tokens, and bare sign markers.
    used_x1 = {amount_word["x0"]}
    consumed = {id(w) for w in date_token_words}
    desc_words = []
    running_balance: Optional[float] = None
    for w in line_words:
        if w is amount_word or id(w) in consumed:
            continue
        if columns.column_for(w["x1"]) == "balance":
            # Capture the running-balance value (for checking-account chain
            # reconciliation) instead of just dropping it.
            if running_balance is None and _looks_like_amount(w["text"]):
                bal = _parse_amount(w["text"])
                if bal is not None:
                    running_balance = abs(bal)  # balances are always positive
            continue  # drop running-balance tokens from description
        if w["x0"] >= amount_word["x0"]:
            continue  # drop anything at/after the amount
        txt = w["text"]
        # skip bare sign markers that some statements use as a debit/credit flag
        if txt in {"+", "-"}:
            continue
        desc_words.append(w)
    desc_words.sort(key=lambda w: w["x0"])
    description = " ".join(w["text"] for w in desc_words).strip()
    # collapse repeated whitespace
    description = re.sub(r"\s+", " ", description)

    # A line with a date + amount but NO description is still a real transaction
    # (some merchants transmit no description text). Use a placeholder rather
    # than dropping it — dropping would under-extract and break reconciliation.
    if not description:
        description = "(no description)"

    # Guard: a line with MULTIPLE amount tokens in the amount column is a summary
    # table row (e.g. BofA "Daily Balance Summary": "02/01 13,865.01 02/12 ..."),
    # not a transaction. Real transaction lines have exactly one amount.
    amount_in_col = sum(
        1 for w in line_words
        if _looks_like_amount(w["text"]) and columns.column_for(w["x1"]) == "amount"
    )
    if amount_in_col > 1:
        return None

    # Guard: a line whose "description" is only dates and amounts (no merchant
    # text) is a summary/balance row, not a transaction. Skip this check when
    # there are no description words (the placeholder case — a real transaction
    # that genuinely lacks a description, which we keep for reconciliation).
    if desc_words and not any(
        not _is_date_token(w["text"]) and not _looks_like_amount(w["text"])
        for w in desc_words
    ):
        return None

    # Bug A fix: a real transaction line on these statements ALWAYS has a date.
    # Summary/overview rows (e.g. Navy Federal page-1 "$72.83 $100.49" account
    # totals) have amount columns but no date token — they slip through the
    # amount-column detector as false transactions. Requiring a date removes them.
    if date_str is None:
        return None

    top = min(w["top"] for w in line_words)
    raw_text = " ".join(w["text"] for w in sorted(line_words, key=lambda x: x["x0"]))

    return RawRow(
        date=date_str,
        description=description,
        amount=amount,
        line_top=top,
        amount_x1=amount_word["x1"],
        running_balance=running_balance,
        raw_text=raw_text,
        raw_data={"amount_token": amount_word["text"]},
    )


# ---------------------------------------------------------------------------
# Summary-row filtering (shared across all banks - fixes the Chase bug)
# ---------------------------------------------------------------------------
def is_summary_row(description: str, profile: Optional[Profile] = None) -> bool:
    """True if a line is a statement summary/header, not a real transaction.

    Uses the profile's summary keywords when available, plus a universal list.
    This logic existed only in generic_regex.py before; centralizing it fixes
    the Chase bug where 'Previous Balance' / 'New Balance' leaked in.
    """
    d = (description or "").strip().lower()
    if not d:
        return True
    keywords = [
        "previous balance", "new balance", "ending balance", "available balance",
        "current balance", "beginning balance", "past due", "over the credit limit",
        "minimum payment", "payment due", "credit limit", "available credit",
        "total fees", "total interest", "total transactions", "total payments",
        "total charges", "total credits", "total debits", "statement balance",
        "account summary", "payments and other credits", "purchases and other charges",
        "fees charged", "interest charged", "subtotal", "year-to-date",
        "amount enclosed", "balance forward", "summary",
        # section-header / total-row markers (often appear with a +/- flag and a
        # dollar figure but are NOT individual transactions)
        "new charges", "new credits", "new payments", "payments and credits",
        "purchases and adjustments", "transactions +", "transactions -",
        "payments -", "payments +", "charges +", "credits -",
        "standard purch", "purchase rate", "annual percentage rate",
        "interest charge", "total interest",
    ]
    if profile is not None and profile.summary_keywords:
        keywords = list(keywords) + list(profile.summary_keywords)
    for kw in keywords:
        if kw in d:
            return True
    # A line whose description is ONLY a sign flag (e.g. "+" or "-") is a marker.
    if d.strip() in {"+", "-", "payments", "transactions", "charges", "credits", "fees", "interest"}:
        return True
    # A line containing an APR/percentage token is a rate disclosure, not a txn.
    if re.search(r"\d{1,2}\.\d{1,2}\s*%", description or ""):
        return True
    return False


# ---------------------------------------------------------------------------
# Top-level extraction
# ---------------------------------------------------------------------------
# Account-header pattern: statements with multiple accounts (e.g. Navy Federal
# checking + savings on one PDF) print a header line like
# "Flagship Checking - 7145495045" before each account's transactions. Tagging
# rows by account lets the reconciler chain each account independently.
_ACCOUNT_HEADER_RE = re.compile(
    r"(checking|savings|money market|flagship|premier)", re.IGNORECASE
)


def _detect_account_header(line_words: List[Dict[str, Any]]) -> Optional[str]:
    """If a line is an account-section header, return the account name."""
    text = " ".join(w["text"] for w in sorted(line_words, key=lambda x: x["x0"]))
    # Must contain an account-type word AND a long account-number-ish token.
    if not _ACCOUNT_HEADER_RE.search(text):
        return None
    # Look for a token that looks like an account number (>= 6 digits) OR a dash
    # separator common in NFCU headers ("Flagship Checking - 7145495045").
    if re.search(r"(\d{6,}|-{1,2}\s*\d{4,})", text):
        return text.strip()[:50]
    return None


def extract_from_page(page: Any, profile: Optional[Profile] = None, page_num: int = 1) -> List[RawRow]:
    """Extract RawRows from a single pdfplumber page using geometry."""
    try:
        words = page.extract_words()
    except Exception:
        return []
    lines = _group_words_into_lines(words)

    # Detect columns from ALL amount-like words on the page.
    amount_words = [w for line in lines for w in line if _looks_like_amount(w["text"])]
    columns = detect_columns(amount_words, profile)
    if columns.amount_x1 is None:
        return []

    # Track the current account section (multi-account statements). When a header
    # line appears, subsequent rows are tagged with that account so the
    # reconciler chains each account independently.
    current_account: Optional[str] = None

    rows: List[RawRow] = []
    for line in lines:
        # Check for an account-section header BEFORE parsing the line.
        header = _detect_account_header(line)
        if header:
            current_account = header
            continue
        row = parse_line(line, columns, profile)
        if row is None:
            continue
        row.page = page_num
        if current_account:
            row.account = current_account
        # Drop summary rows universally.
        if is_summary_row(row.description, profile):
            continue
        rows.append(row)

    # FALLBACK: if a profile was used but yielded NO rows, the statement's
    # layout may have drifted from the hardcoded column (e.g. 2018 vs 2025 BofA
    # use different x-coordinates). Re-run with auto-detected columns (no
    # profile override) so the extractor adapts to the actual page geometry.
    if not rows and profile is not None and profile.amount_column_x1 is not None:
        auto_columns = detect_columns(amount_words, None)  # None = auto-detect
        if auto_columns.amount_x1 is not None and abs(auto_columns.amount_x1 - columns.amount_x1) > 5:
            for line in lines:
                row = parse_line(line, auto_columns, profile)
                if row is None:
                    continue
                row.page = page_num
                if is_summary_row(row.description, profile):
                    continue
                rows.append(row)
    return rows


def extract_from_pdf(pdf_path: str, bank: Optional[str] = None) -> Tuple[List[RawRow], Optional[Profile], ColumnPlan]:
    """Extract from all pages. Returns (rows, profile_used, column_plan).

    If `bank` matches a known profile, that profile is used. For banks with
    MULTIPLE layouts (e.g. Navy Federal checking + Visa), the profile is matched
    by inspecting the PDF's actual amount-column geometry. Otherwise a profile
    is auto-detected from the first transaction page (handles unseen banks).
    """
    import pdfplumber

    # Use geometry-aware profile matching (handles multi-layout banks).
    if bank:
        from .layout_profiles import get_profile_for_pdf
        profile = get_profile_for_pdf(bank, pdf_path=pdf_path)
    else:
        profile = None
    all_rows: List[RawRow] = []
    last_columns = ColumnPlan(amount_x1=None)

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            rows = extract_from_page(page, profile, page_num=i + 1)
            if rows:
                all_rows.extend(rows)
                # Auto-detect profile if none matched and we found rows.
                if profile is None:
                    profile = auto_profile(page, rows)
                # remember the columns for provenance
                words = []
                try:
                    words = page.extract_words()
                except Exception:
                    pass
                aw = [w for w in words if _looks_like_amount(w["text"])]
                last_columns = detect_columns(aw, profile)

    return all_rows, profile, last_columns
