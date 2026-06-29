#!/usr/bin/env python3
"""
Pipeline Test Harness
---------------------
Runs the new confidence-gated extraction pipeline + categorizer across the
Statements/ corpus and reports, per PDF:
  - detected bank, parser source, confidence
  - transaction count, rejected count
  - whether AI was used (and which backend)
  - categorization breakdown (learned / keyword / AI / default)

Also prints an aggregate summary: total transactions, AI call count (cost
proxy), and category distribution.

Usage:
    python test_pipeline.py                 # all PDFs under Statements/
    python test_pipeline.py --limit 20      # first 20 PDFs (fast smoke test)
    python test_pipeline.py --dir "Statements/Capital One"
"""

import argparse
import glob
import os
import sys
import time
from collections import Counter

# Project root on path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bank_parsers.reconciliation_pipeline import ReconciliationPipeline
from bank_statement_analyzer import BankStatementAnalyzer


def run_on_pdf(pipe: ReconciliationPipeline, pdf_path: str, use_ai: bool) -> dict:
    """Extract + categorize one PDF. Returns a result dict."""
    result = pipe.extract(pdf_path)
    analyzer = BankStatementAnalyzer()
    analyzer.transactions = result.transactions
    analyzer.use_ai = use_ai
    analyzer.categorize_transactions(use_multiprocessing=False)
    stats = getattr(analyzer, "_last_categorization_stats", None)
    return {
        "path": pdf_path,
        "bank": result.bank,
        "source": result.method,
        "confidence": result.confidence,
        "count": len(result.transactions),
        "ai_used": result.ai_repair_used,
        "ai_backend": result.ai_backend,
        "categories": dict(Counter(t["category"] for t in analyzer.transactions)),
        "stats": stats,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="Statements", help="root dir to scan for PDFs")
    ap.add_argument("--limit", type=int, default=0, help="max PDFs to process (0=all)")
    ap.add_argument("--ai", action="store_true", help="enable AI categorization if a backend is available")
    args = ap.parse_args()

    pdfs = sorted(glob.glob(os.path.join(args.dir, "**", "*.pdf"), recursive=True))
    if args.limit:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        print(f"No PDFs found under {args.dir}")
        return

    pipe = ReconciliationPipeline()
    print(f"Processing {len(pdfs)} PDF(s) from {args.dir}\n")
    print(f"{'PDF':<40} {'bank':<14} {'conf':>5} {'cnt':>4} {'rej':>3} {'ai':>3}  categories")
    print("-" * 110)

    agg = Counter()
    total_count = 0
    total_ai_calls = 0
    cat_totals = Counter()
    t0 = time.time()

    for pdf in pdfs:
        try:
            r = run_on_pdf(pipe, pdf, use_ai=args.ai)
        except Exception as exc:
            print(f"{os.path.basename(pdf):<40} ERROR: {exc}")
            continue
        total_count += r["count"]
        agg[r["bank"]] += 1
        if r["stats"]:
            total_ai_calls += r["stats"].ai_calls
        for cat, n in r["categories"].items():
            cat_totals[cat] += n
        top_cats = ", ".join(f"{c}:{n}" for c, n in sorted(r["categories"].items(), key=lambda kv: -kv[1])[:3])
        ai_flag = r["ai_backend"][:3] if r["ai_used"] else "no"
        print(
            f"{os.path.basename(pdf)[:39]:<40} {r['bank'][:13]:<14} "
            f"{r['confidence']:>5.1f} {r['count']:>4} {r['rejected']:>3} {ai_flag:>3}  {top_cats}"
        )

    elapsed = time.time() - t0
    print("\n" + "=" * 110)
    print(f"PDFs processed: {len(pdfs)} in {elapsed:.1f}s")
    print(f"Total transactions: {total_count}")
    print(f"AI calls made (cost proxy): {total_ai_calls}")
    print("\nBanks seen:")
    for bank, n in agg.most_common():
        print(f"  {bank}: {n}")
    print("\nAggregate category distribution:")
    for cat, n in cat_totals.most_common():
        print(f"  {cat}: {n}")


if __name__ == "__main__":
    main()
