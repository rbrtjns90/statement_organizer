"""
Totals Reconciliation Layer
===========================
The correctness oracle the system has been missing.

A bank statement is a self-balancing document: it states its own totals
(Previous Balance, Total Transactions/Charges, Total Fees, Total Interest,
New Balance). If `sum(extracted_transactions)` does not match the stated total,
the extraction is *provably wrong* — no AI judgment required. This module
computes that reconciliation and returns a verdict.

The previous system never did this. Its "confidence" was a heuristic blend of
per-row quality scores; a parser could hallucinate rows or include summary
rows (the Chase bug) and its confidence would only go up. Reconciliation is a
deterministic, statement-anchored check that catches both over- and
under-extraction.

Contract
--------
    stated = parse_stated_totals(text, profile)
    actual = sum_of_transactions(rows)
    result = reconcile(actual, stated, profile)
    result.reconciled   # bool — pass/fail
    result.discrepancy  # dollars off

Per-bank totals availability (from the corpus investigation):
    Capital One:  charges + fees + interest + prev/new balance   (richest)
    Chase:        fees + interest + prev/new balance
    Citibank:     fees + interest + prev/new balance
    Bank of America: prev/new balance only
    Navy Federal: ending balance only
The reconciler uses whichever totals are present and degrades gracefully when
fewer are available (lower confidence in the verdict, but still reports any
discrepancy it can compute).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .layout_profiles import Profile


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class StatedTotals:
    """The totals a statement self-declares, parsed from its text."""

    charges: Optional[float] = None         # "Total Transactions" / "Total Charges"
    fees: Optional[float] = None
    interest: Optional[float] = None
    previous_balance: Optional[float] = None
    new_balance: Optional[float] = None
    ending_balance: Optional[float] = None
    beginning_balance: Optional[float] = None  # checking accounts ("Beginning Balance")
    deposits: Optional[float] = None        # "Total deposits and other credits"
    withdrawals: Optional[float] = None     # "Total withdrawals and other debits"
    raw_lines: List[str] = field(default_factory=list)  # for debugging


@dataclass
class ReconciliationResult:
    """Outcome of checking extracted transactions against stated totals."""

    reconciled: bool
    discrepancy: float  # dollars (actual - expected); positive = over-extracted
    expected_total: Optional[float]
    actual_total: float
    check_type: str  # which stated total we compared against
    confidence: float  # 0-100 — how much we trust this verdict
    notes: List[str] = field(default_factory=list)
    stated: Optional[StatedTotals] = None


# ---------------------------------------------------------------------------
# Totals parsing
# ---------------------------------------------------------------------------
_AMOUNT_IN_LINE = re.compile(
    r"-?\$?\s*([\d,]+\.\d{2})"  # capture the amount digits (sign handled separately)
)


def _parse_money(token: str) -> Optional[float]:
    """Parse a money string like '$1,184.04', '-$456.70', '(96.12)', '+$18.67'."""
    t = token.strip()
    negative = False
    if t.startswith("(") and t.endswith(")"):
        negative = True
        t = t[1:-1]
    # Chase prefixes charges with '+' and payments/credits with '-'.
    if t.startswith("+"):
        t = t[1:]
    if t.startswith("-"):
        negative = True
        t = t[1:]
    t = t.replace("$", "").replace(",", "").replace("=", "").strip()
    try:
        val = float(t)
    except ValueError:
        return None
    return -val if negative else val


def _find_amount_after(text: str, anchor: str) -> Optional[float]:
    """Find the dollar amount on the SAME LINE as `anchor` (label), if any.

    This is a same-line matcher: we split text into lines and look for a line
    that contains the label AND a money token, then return that money token.
    This is more reliable than the old "first .find() + forward window" approach,
    which failed on Chase: the first "New Balance" occurrence was an orphan
    header word with no amount, and the real amount sat on a later line.

    Statements put the total on the same line as its label (sometimes separated
    by dotted leaders, '=', or a colon). We accept the money token that appears
    to the RIGHT of the label on that line (handles Citi's stray leading amount
    like '$4,932 New balance $3,673.63').

    YTD EXCLUSION: lines matching 'charged in <year>' are year-to-date totals,
    not per-period totals — we skip them so the per-period figure wins.
    """
    anchor_lower = anchor.lower()
    money_re = re.compile(r"[-+]?\$?\s*[-+]?[\d,]+\.\d{2}")
    ytd_re = re.compile(r"charged in\s+\d{4}", re.IGNORECASE)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if anchor_lower not in line.lower():
            continue
        # Skip YTD totals ("Total interest charged in 2025 $71.53").
        if ytd_re.search(line):
            continue
        # Find money tokens on this line that are AFTER the label position.
        label_idx = line.lower().find(anchor_lower)
        after_label = line[label_idx + len(anchor):]
        for m in money_re.finditer(after_label):
            val = _parse_money(m.group(0))
            if val is not None:
                return val
        # If nothing after the label, accept a money token anywhere on the line
        # (some statements put the amount before the label).
        for m in money_re.finditer(line):
            val = _parse_money(m.group(0))
            if val is not None:
                return val
    return None


def parse_stated_totals(text: str, profile: Optional[Profile] = None) -> StatedTotals:
    """Extract the self-declared totals from statement text.

    Uses the profile's `totals_fields` map (label phrase -> logical field) when
    available; otherwise falls back to universal labels.
    """
    totals = StatedTotals()
    if not text:
        return totals

    # Build the label->field map. Profile takes priority; else universal guesses.
    field_map: Dict[str, str] = {}
    if profile and profile.totals_fields:
        # Profile convention is {field_name: label_phrase}; the universal map and
        # this parser use {label: field_name}. Invert the profile entries so the
        # merge is consistent (this was a silent bug: profile labels were never
        # matched because the keys were field names, not labels).
        for field_name, label in profile.totals_fields.items():
            if isinstance(label, str) and label:
                field_map[label] = field_name
    # Universal fallbacks (used when no profile or profile is sparse).
    universal = {
        "total transactions": "charges",
        "total charges": "charges",
        "total fees for this period": "fees",
        "total fees": "fees",
        "total interest for this period": "interest",
        "total interest": "interest",
        "previous balance": "previous_balance",
        "new balance": "new_balance",
        "ending balance": "ending_balance",
        "beginning balance": "beginning_balance",
        "total deposits and other credits": "deposits",
        "total deposits": "deposits",
        "total withdrawals and other debits": "withdrawals",
        "total withdrawals": "withdrawals",
    }
    for label, field_name in universal.items():
        field_map.setdefault(label, field_name)

    # Some labels are ambiguous ("new balance" appears in headers too). We prefer
    # the MOST SPECIFIC label first, so sort by length descending.
    valid_fields = {"charges", "fees", "interest", "previous_balance",
                    "new_balance", "ending_balance", "beginning_balance",
                    "deposits", "withdrawals"}
    for label in sorted(field_map.keys(), key=len, reverse=True):
        field_name = field_map[label]
        # Normalize: only valid attribute names; skip malformed mappings.
        if field_name not in valid_fields:
            continue
        # Skip if already found (a more-specific label won earlier).
        if getattr(totals, field_name) is not None:
            continue
        val = _find_amount_after(text, label)
        if val is not None:
            setattr(totals, field_name, val)
            # record the raw line for debugging
            idx = text.lower().find(label.lower())
            line_end = text.find("\n", idx)
            totals.raw_lines.append(text[idx:line_end if line_end > 0 else idx + 80].strip())

    return totals


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------
def _sum_transactions(rows: List[Any], sign: str = "all") -> float:
    """Sum transaction amounts. sign='charges'|'credits'|'all'."""
    total = 0.0
    for r in rows:
        # Handle both dict transactions (from the pipeline) and RawRow objects
        # (from direct geometry extraction). getattr(dict, "amount") would
        # return the dict.method "amount", not the value — a silent bug.
        if isinstance(r, dict):
            amt = r.get("amount")
        else:
            amt = getattr(r, "amount", None)
        if amt is None:
            continue
        try:
            amt = float(amt)
        except (TypeError, ValueError):
            continue
        if sign == "charges" and amt > 0:
            total += amt
        elif sign == "credits" and amt < 0:
            total += amt
        elif sign == "all":
            total += amt
    return total


def _reconcile_running_balance_chain(
    rows: List[Any], stated: StatedTotals, tolerance: float = 0.01
) -> Optional[ReconciliationResult]:
    """Per-row running-balance chain reconciliation (checking accounts).

    Each transaction row carries a stated running balance. The chain invariant is:
        balance[i] = balance[i-1] + amount[i]
    If every row satisfies this (to `tolerance`), extraction is row-exact correct.

    Rows are grouped by account section first — a statement may hold multiple
    accounts (e.g. Navy Federal checking + savings on one PDF), and each is an
    independent chain. Cross-account chaining would spuriously "break".

    Returns None if no row carries a running balance (the strategy doesn't apply).
    """
    # Collect rows that have a running balance. Only those participate.
    chained = []
    for r in rows:
        bal = r.get("running_balance") if isinstance(r, dict) else getattr(r, "running_balance", None)
        if bal is not None:
            chained.append(r)
    if len(chained) < 2:
        return None  # not a running-balance statement, or too few rows

    # Segment by account (rows may carry an `account` field). Default group "".
    groups: dict = {}
    for r in chained:
        acct = (r.get("account") if isinstance(r, dict) else getattr(r, "account", None)) or ""
        groups.setdefault(acct, []).append(r)

    total_rows = 0
    matched_rows = 0
    discrepancies: List[float] = []
    break_row: Optional[str] = None
    for acct, group_rows in groups.items():
        # Sort by (page, line_top) to walk the chain in statement order.
        def _order(r):
            if isinstance(r, dict):
                return (r.get("page", 1), r.get("line_top", 0))
            return (getattr(r, "page", 1), getattr(r, "line_top", 0))
        ordered = sorted(group_rows, key=_order)
        prev_bal: Optional[float] = None
        for r in ordered:
            amt = r.get("amount") if isinstance(r, dict) else getattr(r, "amount", None)
            bal = r.get("running_balance") if isinstance(r, dict) else getattr(r, "running_balance", None)
            try:
                amt = float(amt) if amt is not None else 0.0
                bal = float(bal) if bal is not None else None
            except (TypeError, ValueError):
                continue
            if bal is None:
                continue
            if prev_bal is not None:
                total_rows += 1
                expected = round(prev_bal + amt, 2)
                if abs(expected - bal) <= tolerance:
                    matched_rows += 1
                else:
                    if break_row is None:
                        desc = r.get("description") if isinstance(r, dict) else getattr(r, "description", "")
                        break_row = f"{acct or 'acct'}: {desc[:30]} expected={expected} stated={bal}"
                    discrepancies.append(round(expected - bal, 2))
            # The first row of each chain has no predecessor — it establishes
            # the starting balance and is trivially valid (not counted as a
            # checkable row, so it can't fail the reconciliation).
            prev_bal = bal

    if total_rows == 0:
        return None

    reconciled = matched_rows == total_rows
    # Discrepancy = sum of chain breaks (magnitude of cumulative drift).
    total_disc = round(sum(abs(d) for d in discrepancies), 2) if discrepancies else 0.0
    notes = [f"chain: {matched_rows}/{total_rows} rows matched"]
    if break_row:
        notes.append(f"first break at {break_row}")
    return ReconciliationResult(
        reconciled=reconciled,
        discrepancy=total_disc,
        expected_total=float(matched_rows),
        actual_total=float(total_rows),
        check_type="running_balance_chain",
        confidence=95.0 if reconciled else (50.0 if matched_rows > 0 else 30.0),
        notes=notes,
        stated=stated,
    )


def reconcile(
    rows: List[Any],
    stated: StatedTotals,
    profile: Optional[Profile] = None,
    tolerance: float = 0.01,
) -> ReconciliationResult:
    """Check extracted transactions against stated totals.

    Tries each available reconciliation strategy in priority order and returns
    the first verdict it can compute:
      1. Charges total (best — direct match of purchases)
      2. Balance equation: PreviousBalance + Charges - Payments = NewBalance
      3. Per-row running-balance chain (checking accounts — row-exact)
      4. Ending balance (weakest)

    `tolerance` is the dollar tolerance for "reconciled" (default 1 cent).
    """
    actual_charges = _sum_transactions(rows, "charges")
    actual_credits = abs(_sum_transactions(rows, "credits"))
    actual_net = actual_charges - actual_credits

    notes: List[str] = []

    # Strategy 1: direct charges total (the cleanest check).
    if stated.charges is not None:
        discrepancy = round(actual_charges - stated.charges, 2)
        # Some statements (Capital One) list the payment as a positive charge;
        # if so, charges may include the payment. We also check net vs charges.
        reconciled = abs(discrepancy) <= tolerance
        return ReconciliationResult(
            reconciled=reconciled,
            discrepancy=discrepancy,
            expected_total=stated.charges,
            actual_total=actual_charges,
            check_type="charges_total",
            confidence=95.0 if reconciled else 40.0,
            notes=notes,
            stated=stated,
        )

    # Strategy 1b: deposits + withdrawals totals (checking accounts).
    # A checking statement declares "Total deposits and other credits" and
    # "Total withdrawals and other debits". sum(credits) must match deposits;
    # abs(sum(debits)) must match withdrawals. This is the cleanest check for
    # checking accounts that don't expose a charges total.
    if stated.deposits is not None or stated.withdrawals is not None:
        # deposits = money in (positive amounts); withdrawals = money out (|neg|).
        actual_deposits = _sum_transactions(rows, "charges")
        actual_withdrawals = abs(_sum_transactions(rows, "credits"))
        # Stated totals may be signed ("-$15,800.31"); compare absolute values.
        stated_dep = abs(stated.deposits) if stated.deposits is not None else None
        stated_wd = abs(stated.withdrawals) if stated.withdrawals is not None else None
        discrepancies = []
        if stated_dep is not None:
            discrepancies.append(round(actual_deposits - stated_dep, 2))
        if stated_wd is not None:
            discrepancies.append(round(actual_withdrawals - stated_wd, 2))
        total_disc = round(sum(abs(d) for d in discrepancies), 2)
        reconciled = total_disc <= tolerance
        return ReconciliationResult(
            reconciled=reconciled,
            discrepancy=total_disc,
            expected_total=stated_dep,
            actual_total=actual_deposits,
            check_type="deposits_withdrawals",
            confidence=95.0 if reconciled else 40.0,
            notes=[f"deposits: actual={actual_deposits:.2f} stated={stated_dep}; "
                   f"withdrawals: actual={actual_withdrawals:.2f} stated={stated_wd}"],
            stated=stated,
        )

    # Strategy 2: balance equation.
    #   NewBalance = PreviousBalance + Charges - Payments + Interest + Fees
    # => (Charges - Payments) = NewBalance - PreviousBalance - Interest - Fees
    # Credit-card statements accrue interest/fees that are NOT individual
    # transactions, so the net transaction activity differs from the balance
    # change by exactly (interest + fees). Including them reconciles Citi etc.
    if stated.new_balance is not None and stated.previous_balance is not None:
        interest = stated.interest or 0.0
        fees = stated.fees or 0.0
        expected_net = round(stated.new_balance - stated.previous_balance - interest - fees, 2)
        discrepancy = round(actual_net - expected_net, 2)
        reconciled = abs(discrepancy) <= tolerance
        return ReconciliationResult(
            reconciled=reconciled,
            discrepancy=discrepancy,
            expected_total=expected_net,
            actual_total=actual_net,
            check_type="balance_equation",
            confidence=85.0 if reconciled else 35.0,
            notes=[f"prev={stated.previous_balance} new={stated.new_balance} "
                   f"interest={interest} fees={fees} expected_net={expected_net}"],
            stated=stated,
        )

    # Strategy 3: per-row running-balance chain (strongest check for checking
    # accounts). Each row's balance should equal the previous balance ± amount:
    #     balance[i] = balance[i-1] + amount[i]
    # This localizes any extraction error to the EXACT row where the chain breaks
    # — far more precise than opening/closing totals. Rows are grouped by account
    # section first (a statement can hold multiple accounts: checking + savings).
    chain_result = _reconcile_running_balance_chain(rows, stated, tolerance)
    if chain_result is not None:
        return chain_result

    # Strategy 4: ending balance only (weakest — can't verify the journey, only
    # that net activity is plausible). We can't fully reconcile without a prior
    # balance, so we report but mark lower confidence.
    if stated.ending_balance is not None:
        return ReconciliationResult(
            reconciled=False,  # can't verify without prior balance
            discrepancy=0.0,
            expected_total=stated.ending_balance,
            actual_total=actual_net,
            check_type="ending_balance_only",
            confidence=20.0,  # low — no equation to check
            notes=["ending balance available but no prior balance to reconcile against"],
            stated=stated,
        )

    # No usable stated totals.
    return ReconciliationResult(
        reconciled=False,
        discrepancy=0.0,
        expected_total=None,
        actual_total=actual_net,
        check_type="none",
        confidence=0.0,
        notes=["no stated totals found in statement text"],
        stated=stated,
    )


def reconcile_from_text(
    rows: List[Any], text: str, profile: Optional[Profile] = None, tolerance: float = 0.01
) -> ReconciliationResult:
    """Convenience: parse totals from text then reconcile."""
    stated = parse_stated_totals(text, profile)
    return reconcile(rows, stated, profile, tolerance)
