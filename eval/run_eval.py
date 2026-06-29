#!/usr/bin/env python3
"""
Ground-Truth Evaluation Harness
===============================
Measures extraction correctness against REAL ground truth, replacing the
self-referential "accuracy" numbers that plagued the old system.

Three sources of truth, strongest first:

1. **Stated-totals reconciliation** (Phase 3 reconciler): the statement itself
   declares its totals. sum(extracted) must match. This is a deterministic,
   statement-anchored check available for EVERY PDF with stated totals — no
   manual labeling needed. This is the metric that actually matters for
   accounting correctness.

2. **CSV ground truth** (e.g. Caterpillar bank exports): when a bank-provided
   CSV accompanies a PDF, we diff extracted rows against it for per-row
   precision/recall. (Requires matching PDFs in the repo.)

3. **Manual labels** (eval/labels/*.json): a hand-labeled held-out set. One-time
   human effort, then permanent. Format:
       [{"date": "01/08/2025", "description": "LOVE'S #0561", "amount": -25.56}, ...]

Metrics reported:
  - reconciliation rate (% of statements that balance to the cent)
  - mean reconciliation discrepancy ($)
  - per-row precision / recall (when labels/CSV available)
  - extraction yield (rows per statement) — informational only

The harness is grouped by bank so you see where the system is strong/weak.

Usage:
    python eval/run_eval.py                       # whole corpus
    python eval/run_eval.py --limit 30            # quick sample
    python eval/run_eval.py --bank "Capital One"
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import List, Optional

os.environ["LLAMA_CPP_LOG_LEVEL"] = "3"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pdfplumber

from bank_parsers.geometry_extractor import extract_from_pdf
from bank_parsers.layout_profiles import get_profile
from bank_parsers.reconciler import reconcile_from_text, parse_stated_totals, ReconciliationResult


# ---------------------------------------------------------------------------
# Ground-truth loaders
# ---------------------------------------------------------------------------
@dataclass
class LabeledRow:
    date: Optional[str]
    description: str
    amount: float


def load_csv_ground_truth(csv_path: str) -> List[LabeledRow]:
    """Load a bank-exported CSV as ground-truth rows."""
    rows = []
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                amt_raw = (r.get("Transaction Amount") or r.get("Amount") or "").replace("USD", "").strip()
                try:
                    amt = float(amt_raw)
                except ValueError:
                    continue
                rows.append(LabeledRow(
                    date=r.get("Transaction Date") or r.get("Date"),
                    description=r.get("Description", ""),
                    amount=amt,
                ))
    except Exception as exc:
        print(f"  ⚠️ could not load CSV {csv_path}: {exc}")
    return rows


def load_manual_labels(json_path: str) -> List[LabeledRow]:
    """Load a hand-labeled JSON ground-truth file."""
    try:
        with open(json_path, encoding="utf-8") as fh:
            data = json.load(fh)
        return [LabeledRow(d.get("date"), d.get("description", ""), float(d.get("amount", 0)))
                for d in data]
    except Exception as exc:
        print(f"  ⚠️ could not load labels {json_path}: {exc}")
        return []


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
@dataclass
class StatementMetrics:
    pdf: str
    bank: str
    row_count: int
    reconciliation: ReconciliationResult
    csv_precision: Optional[float] = None  # when CSV truth available
    csv_recall: Optional[float] = None
    error: Optional[str] = None


def _match_rows(extracted: List, truth: List[LabeledRow], tol: float = 0.01) -> tuple:
    """Greedy amount-based matching for precision/recall (no fuzzy merchant)."""
    truth_amts = sorted((abs(t.amount), t) for t in truth)
    used = [False] * len(truth_amts)
    tp = 0
    for e in extracted:
        e_amt = abs(getattr(e, "amount", 0) or 0)
        for i, (t_amt, _t) in enumerate(truth_amts):
            if not used[i] and abs(e_amt - t_amt) <= tol:
                used[i] = True
                tp += 1
                break
    fp = len(extracted) - tp
    fn = sum(1 for u in used if not u)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return precision, recall


def evaluate_statement(pdf_path: str, csv_path: Optional[str] = None,
                       label_path: Optional[str] = None) -> StatementMetrics:
    """Run extraction + reconciliation + optional row matching for one PDF."""
    bank_guess = _guess_bank_from_path(pdf_path)
    profile = get_profile(bank_guess)
    try:
        rows, _, _ = extract_from_pdf(pdf_path, bank=bank_guess)
    except Exception as exc:
        return StatementMetrics(pdf_path, bank_guess, 0,
                                ReconciliationResult(False, 0, None, 0, "error", 0),
                                error=str(exc))
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    recon = reconcile_from_text(rows, text, profile)

    metrics = StatementMetrics(
        pdf=pdf_path, bank=bank_guess, row_count=len(rows), reconciliation=recon,
    )

    truth: List[LabeledRow] = []
    if csv_path:
        truth = load_csv_ground_truth(csv_path)
    elif label_path:
        truth = load_manual_labels(label_path)
    if truth:
        p, r = _match_rows(rows, truth)
        metrics.csv_precision = p
        metrics.csv_recall = r

    return metrics


def _guess_bank_from_path(path: str) -> Optional[str]:
    p = path.lower()
    for bank in ["Bank of America", "Capital One", "Chase", "Citibank", "Navy Federal"]:
        if bank.lower() in p:
            return bank
    return None


# ---------------------------------------------------------------------------
# Aggregate reporting
# ---------------------------------------------------------------------------
def report(metrics: List[StatementMetrics]) -> None:
    by_bank: dict = defaultdict(list)
    for m in metrics:
        by_bank[m.bank or "Unknown"].append(m)

    print(f"\n{'='*78}")
    print(f"EVALUATION REPORT — {len(metrics)} statements")
    print(f"{'='*78}\n")
    print(f"{'Bank':<18} {'Stmts':>5} {'Recon%':>7} {'MeanDisc':>10} {'AvgRows':>8} {'Errors':>7}")
    print("-" * 78)

    total_reconciled = 0
    total_disc = 0.0
    for bank in sorted(by_bank.keys()):
        ms = by_bank[bank]
        n = len(ms)
        reconciled = sum(1 for m in ms if m.reconciliation.reconciled)
        mean_disc = sum(abs(m.reconciliation.discrepancy) for m in ms) / n
        avg_rows = sum(m.row_count for m in ms) / n
        errors = sum(1 for m in ms if m.error)
        recon_pct = 100.0 * reconciled / n
        print(f"{bank:<18} {n:>5} {recon_pct:>6.1f}% {mean_disc:>9.2f}$ {avg_rows:>8.1f} {errors:>7}")
        total_reconciled += reconciled
        total_disc += sum(abs(m.reconciliation.discrepancy) for m in ms)

    print("-" * 78)
    n = len(metrics)
    print(f"{'TOTAL':<18} {n:>5} {100.0*total_reconciled/n:>6.1f}% {total_disc/n:>9.2f}$")
    print()
    print(f"Statements provably correct (reconciled to the cent): {total_reconciled}/{n}")
    print(f"Statements with extraction errors detected:           "
          f"{n - total_reconciled - sum(1 for m in metrics if m.reconciliation.check_type in ('ending_balance_only','none'))}/{n}")

    # CSV/label precision-recall if available
    csv_metrics = [m for m in metrics if m.csv_precision is not None]
    if csv_metrics:
        mp = sum(m.csv_precision for m in csv_metrics) / len(csv_metrics)
        mr = sum(m.csv_recall for m in csv_metrics) / len(csv_metrics)
        print(f"\nRow-level matching (CSV/label ground truth, {len(csv_metrics)} stmts):")
        print(f"  mean precision = {mp:.1%}   mean recall = {mr:.1%}")

    # Reconciliation check-type distribution
    print(f"\nReconciliation methods used:")
    type_counts = Counter(m.reconciliation.check_type for m in metrics)
    for t, c in type_counts.most_common():
        print(f"  {t}: {c}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="Statements")
    ap.add_argument("--bank", default=None, help="restrict to one bank folder")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    pdfs = sorted(glob.glob(os.path.join(args.dir, "**", "*.pdf"), recursive=True))
    if args.bank:
        pdfs = [p for p in pdfs if args.bank.lower() in p.lower()]
    if args.limit:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        print("No PDFs found.")
        return

    # Map CSVs/labels to PDFs by stem proximity (best-effort).
    csvs = glob.glob(os.path.join(args.dir, "**", "*.csv"), recursive=True)

    metrics: List[StatementMetrics] = []
    for p in pdfs:
        # best-effort CSV match
        stem = os.path.splitext(os.path.basename(p))[0]
        csv_match = next((c for c in csvs if stem in c), None)
        m = evaluate_statement(p, csv_path=csv_match)
        metrics.append(m)
        verdict = "✓" if m.reconciliation.reconciled else ("·" if m.reconciliation.check_type in ("ending_balance_only","none") else "✗")
        print(f"  {verdict} {os.path.basename(p)[:40]:<42} {m.bank or '?':<14} "
              f"rows={m.row_count:>3} disc=${m.reconciliation.discrepancy:>8.2f} ({m.reconciliation.check_type})")

    report(metrics)


if __name__ == "__main__":
    main()
