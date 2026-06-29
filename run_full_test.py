#!/usr/bin/env python3
"""
Full-corpus extraction + categorization test with local AI.

Runs every PDF under Statements/ through the new pipeline (extraction_pipeline
+ categorizer with local Gemma 4), writing per-PDF results and an aggregate
summary to test_results.txt. Designed to run in the background.
"""
import glob
import os
import sys
import time
from collections import Counter

os.environ["LLAMA_CPP_LOG_LEVEL"] = "3"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bank_parsers.extraction_pipeline import ExtractionPipeline
from bank_statement_analyzer import BankStatementAnalyzer

OUTFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_results.txt")


def main():
    pdfs = sorted(glob.glob("Statements/**/*.pdf", recursive=True))
    pipe = ExtractionPipeline()
    lines = []
    lines.append(f"Full-corpus test — {len(pdfs)} PDFs — local AI categorization")
    lines.append(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"{'PDF':<40} {'bank':<14} {'conf':>5} {'cnt':>4} {'kw':>3} {'ai':>3} {'def':>3} {'t(s)':>5}")
    lines.append("-" * 120)

    agg_cats = Counter()
    total_txns = 0
    total_ai = 0
    errors = []
    t0 = time.time()

    for i, path in enumerate(pdfs):
        pdf_t0 = time.time()
        try:
            r = pipe.extract(path)
            a = BankStatementAnalyzer()
            a.transactions = r.transactions
            a.use_ai = True
            a.categorize_transactions(use_multiprocessing=False)
            s = a._last_categorization_stats
            total_txns += r.count
            total_ai += s.ai_calls
            cc = Counter(t["category"] for t in a.transactions)
            for c, n in cc.items():
                agg_cats[c] += n
            elapsed = time.time() - pdf_t0
            lines.append(
                f"{os.path.basename(path)[:39]:<40} {r.bank[:13]:<14} "
                f"{r.confidence:>5.1f} {r.count:>4} {s.keyword:>3} {s.ai:>3} "
                f"{s.default:>3} {elapsed:>5.1f}"
            )
        except Exception as exc:
            elapsed = time.time() - pdf_t0
            errors.append((path, str(exc)))
            lines.append(f"{os.path.basename(path)[:39]:<40} ERROR {type(exc).__name__}: {str(exc)[:50]} (t={elapsed:.1f}s)")
        # Flush progress to file periodically so we can watch it.
        if (i + 1) % 10 == 0 or i == len(pdfs) - 1:
            with open(OUTFILE, "w") as fh:
                fh.write("\n".join(lines) + f"\n  ... ({i+1}/{len(pdfs)} done, {time.time()-t0:.0f}s elapsed)\n")

    lines.append("\n" + "=" * 120)
    lines.append(f"TOTAL: {len(pdfs)} PDFs in {time.time()-t0:.0f}s | txns={total_txns} | AI calls={total_ai}")
    if errors:
        lines.append(f"\n{len(errors)} errors:")
        for p, e in errors[:20]:
            lines.append(f"  {os.path.basename(p)}: {e}")
    lines.append("\nAggregate category distribution:")
    for c, n in agg_cats.most_common():
        lines.append(f"  {c}: {n}")
    with open(OUTFILE, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"Done. Results in {OUTFILE}")


if __name__ == "__main__":
    main()
