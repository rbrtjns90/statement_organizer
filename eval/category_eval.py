#!/usr/bin/env python3
"""
Category Evaluation
===================
Measures categorization accuracy on VERIFIED transactions (those that pass
reconciliation) and emits a label template for human review.

Two modes:
  1. ``--report``  : run extraction+reconciliation+categorization, print the
     category distribution and flag merchants the AI categorized that might be
     wrong (gas-station names in non-Travel categories, etc.) using a small set
     of sanity heuristics.
  2. ``--template`` : write a JSON template (one entry per verified transaction
     with a blank "expected_category") that a human fills in. Once filled, it
     becomes ground truth for measuring categorizer accuracy in future runs.

The point: categorization can only be improved when it's measured. This gives
you the measurement loop.

Usage:
    python eval/category_eval.py --pdf "Statements/Capital One/Statement_012025_9746.pdf" --report
    python eval/category_eval.py --pdf "...pdf" --template --out eval/labels/capital_one.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

os.environ["LLAMA_CPP_LOG_LEVEL"] = "3"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bank_parsers.reconciliation_pipeline import ReconciliationPipeline
from bank_statement_analyzer import BankStatementAnalyzer


# ---------------------------------------------------------------------------
# Sanity heuristics — flag likely mis-categorizations without human labels.
# These are NOT ground truth; they surface suspicious AI decisions to review.
# ---------------------------------------------------------------------------
GAS_STATION_TOKENS = {
    "love's", "loves", "flying j", "pilot", "shell", "chevron", "exxon",
    "petro", "marathon", "circle k", "qt ", "spinx", "murphy", "speedway",
    "race trac", "racetrac", "ta #", "7-eleven", "bp ", "sunoco", "valero",
    "mobil ",  # note trailing space: avoids matching "mobile"
}
RESTAURANT_TOKENS = {
    "mcdonald", "starbucks", "subway", "arby", "chick-fil-a", "chickfila",
    "doordash", "grubhub", "ubereats", "taco bell", "dickeys", "bbq",
    "restaurant", "cafe", "coffee",
}
OFFICE_TOKENS = {"staples", "office depot", "office max"}

TRAVEL_CAT = "Travel & Transportation"
MEALS_CAT = "Meals & Entertainment"
OFFICE_CAT = "Office Supplies"


def _lower(desc: str) -> str:
    return (desc or "").lower()


def flag_suspect_categories(transactions) -> list:
    """Return [(description, assigned_category, suspected_category, reason)]."""
    suspects = []
    for t in transactions:
        desc = _lower(t.get("description", ""))
        cat = t.get("category", "")
        if not desc or not cat:
            continue
        # Gas station token in a non-Travel category
        if any(tok in desc for tok in GAS_STATION_TOKENS) and cat != TRAVEL_CAT:
            suspects.append((t.get("description"), cat, TRAVEL_CAT, "gas-station name"))
        # Restaurant token in a non-Meals category
        elif any(tok in desc for tok in RESTAURANT_TOKENS) and cat not in (MEALS_CAT, TRAVEL_CAT):
            suspects.append((t.get("description"), cat, MEALS_CAT, "restaurant name"))
        # Office token in a non-Office category
        elif any(tok in desc for tok in OFFICE_TOKENS) and cat != OFFICE_CAT:
            suspects.append((t.get("description"), cat, OFFICE_CAT, "office-supply name"))
    return suspects


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(pdf_path: str, use_ai: bool = True):
    """Extract → verify → categorize. Returns (result, analyzer)."""
    pipe = ReconciliationPipeline()
    result = pipe.extract(pdf_path)
    analyzer = BankStatementAnalyzer()
    analyzer.transactions = result.transactions
    analyzer.use_ai = use_ai
    analyzer.categorize_transactions(use_multiprocessing=False)
    return result, analyzer


def report(pdf_path: str, use_ai: bool = True) -> None:
    result, analyzer = run(pdf_path, use_ai)
    recon = result.reconciliation
    print(f"\n{'='*70}")
    print(f"CATEGORY EVAL — {os.path.basename(pdf_path)}")
    print(f"{'='*70}")
    print(f"Bank: {result.bank}   Method: {result.method}")
    print(f"Verified: {result.count} txns   Reconciled: "
          f"{recon.reconciled if recon else '?'} (disc=${recon.discrepancy:.2f})")
    if not (recon and recon.reconciled):
        print("⚠️ Transactions are NOT reconciled — categorization eval is on unverified data.")

    cc = Counter(t["category"] for t in analyzer.transactions)
    print(f"\nCategory distribution:")
    for cat, n in cc.most_common():
        print(f"  {cat}: {n}")

    suspects = flag_suspect_categories(analyzer.transactions)
    if suspects:
        print(f"\n🚩 Suspect categorizations ({len(suspects)} — review these):")
        for desc, assigned, suspected, reason in suspects:
            print(f"  '{desc[:40]}'  assigned={assigned}  suspected={suspected}  ({reason})")
    else:
        print("\n✓ No suspect categorizations flagged by heuristics.")


def write_template(pdf_path: str, out_path: str) -> None:
    """Write a human-fillable label template for the PDF's verified transactions."""
    result, _ = run(pdf_path, use_ai=False)  # no AI; we just want the txns
    template = []
    for t in result.transactions:
        template.append({
            "date": str(t.get("date") or "")[:10],
            "description": t.get("description"),
            "amount": t.get("amount"),
            "expected_category": "",  # human fills this
        })
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(template, fh, indent=2)
    print(f"Wrote label template: {out_path} ({len(template)} transactions)")
    print("Fill in 'expected_category' for each, then run accuracy_eval.py.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--template", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-ai", action="store_true")
    args = ap.parse_args()

    if args.template:
        out = args.out or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "labels",
            os.path.splitext(os.path.basename(args.pdf))[0] + ".json",
        )
        write_template(args.pdf, out)
    else:
        report(args.pdf, use_ai=not args.no_ai)


if __name__ == "__main__":
    main()
