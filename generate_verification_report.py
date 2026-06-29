#!/usr/bin/env python3
"""
Verification report generator.

Runs the full pipeline (extract + categorize, local AI) on ONE representative
PDF per bank, then writes a multi-page PDF report. Each section shows:
  - the source PDF filename + detected bank + confidence
  - a table of the extracted transactions (date, description, amount, category)
so a human can visually verify extraction + categorization quality side-by-side
with the original statement.

Usage:
    python generate_verification_report.py
"""
import os
import sys
import json

os.environ["LLAMA_CPP_LOG_LEVEL"] = "3"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collections import Counter

from bank_parsers.reconciliation_pipeline import ReconciliationPipeline
from bank_statement_analyzer import BankStatementAnalyzer

# One representative PDF per bank. Chosen from the corpus.
SAMPLES = [
    ("Bank of America", "Statements/Bank of America/Credit/eStmt_2025-01-12.pdf"),
    ("Capital One", "Statements/Capital One/Statement_012025_9746.pdf"),
    ("Chase", "Statements/Chase/20220124-statements-0225-.pdf"),
    ("Citibank", "Statements/Citibank/April 08.pdf"),
    ("Navy Federal", "Statements/Navy Federal/2024-08-11_STMSSCM.pdf"),
]


def run_extraction():
    """Run the pipeline on each sample. Returns list of result dicts."""
    pipe = ReconciliationPipeline()
    results = []
    for label, path in SAMPLES:
        if not os.path.exists(path):
            print(f"  skipping (missing): {path}")
            continue
        print(f"  processing {label}: {os.path.basename(path)}")
        r = pipe.extract(path)
        analyzer = BankStatementAnalyzer()
        analyzer.transactions = r.transactions
        analyzer.use_ai = True
        analyzer.categorize_transactions(use_multiprocessing=False)
        stats = analyzer._last_categorization_stats
        results.append(
            {
                "label": label,
                "source_file": os.path.basename(path),
                "bank_detected": r.bank,
                "confidence": r.confidence,
                "ai_used": r.ai_repair_used,
                "ai_backend": r.ai_backend,
                "method": r.method,
                "count": len(r.transactions),
                "kw_matches": stats.keyword,
                "ai_matches": stats.ai,
                "default_matches": stats.default,
                "transactions": analyzer.transactions,
            }
        )
    return results


def write_json(results, path):
    """Dump results to JSON (dates -> isoformat) for debugging/reuse."""
    out = []
    for r in results:
        rr = dict(r)
        txns = []
        for t in r["transactions"]:
            tt = dict(t)
            d = tt.get("date")
            if hasattr(d, "isoformat"):
                tt["date"] = d.isoformat()
            txns.append(tt)
        rr["transactions"] = txns
        out.append(rr)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, default=str)


def fmt_date(d):
    if hasattr(d, "strftime"):
        return d.strftime("%m/%d/%Y")
    if d is None:
        return ""
    return str(d)


def fmt_amount(a):
    if a is None:
        return ""
    try:
        return f"${float(a):,.2f}"
    except (TypeError, ValueError):
        return str(a)


def build_pdf(results, out_path):
    """Build the verification PDF with ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    )
    from reportlab.lib.enums import TA_LEFT

    doc = SimpleDocTemplate(
        out_path, pagesize=letter,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        title="Statement Extractor - Verification Report",
        author="Statement Organizer",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=20,
                        textColor=colors.HexColor("#0f172a"), spaceAfter=6)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9,
                         textColor=colors.HexColor("#64748b"), spaceAfter=18)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=15,
                        textColor=colors.HexColor("#1e3a8a"), spaceBefore=10, spaceAfter=4)
    meta = ParagraphStyle("meta", parent=styles["Normal"], fontSize=9,
                          textColor=colors.HexColor("#475569"), spaceAfter=8)
    note = ParagraphStyle("note", parent=styles["Italic"], fontSize=8,
                          textColor=colors.HexColor("#94a3b8"), spaceBefore=4, spaceAfter=10)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8,
                          leading=10, wordWrap="LTR")
    cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")

    story = []
    # ---- Cover / summary ----
    total_txns = sum(r["count"] for r in results)
    story.append(Paragraph("Statement Extractor — Verification Report", h1))
    story.append(Paragraph(
        "One PDF per bank, processed with local Gemma 4 AI. "
        "Cross-check each table against the original statement.",
        sub,
    ))
    story.append(Paragraph(
        f"{len(results)} banks · {total_txns} transactions extracted · "
        f"local model: gemma-4-e2b-it-Q8_0", meta,
    ))
    story.append(Spacer(1, 6))

    # Summary table
    summary_data = [["Bank", "Source File", "Detected", "Conf.", "Txns", "KW", "AI", "Def"]]
    for r in results:
        summary_data.append([
            Paragraph(r["label"], cellb),
            Paragraph(r["source_file"], cell),
            Paragraph(r["bank_detected"], cell),
            Paragraph(f"{r['confidence']:.0f}", cell),
            Paragraph(str(r["count"]), cell),
            Paragraph(str(r["kw_matches"]), cell),
            Paragraph(str(r["ai_matches"]), cell),
            Paragraph(str(r["default_matches"]), cell),
        ])
    avail = letter[0] - 1.2 * inch
    cw = [avail * p for p in [0.13, 0.27, 0.15, 0.09, 0.09, 0.09, 0.09, 0.09]]
    t = Table(summary_data, colWidths=cw, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Paragraph(
        "KW = keyword matches · AI = local-AI categorizations · Def = defaulted to 'Other Business Expenses'",
        note,
    ))
    story.append(PageBreak())

    # ---- One section per bank ----
    for idx, r in enumerate(results):
        story.append(Paragraph(f"{r['label']} — {r['source_file']}", h2))
        story.append(Paragraph(
            f"Detected bank: <b>{r['bank_detected']}</b> · confidence {r['confidence']:.0f}% · "
            f"parser: {r['parser_source']} · "
            f"{r['count']} transactions "
            f"(keyword: {r['kw_matches']}, AI: {r['ai_matches']}, default: {r['default_matches']})"
            + (f" · AI backend used: {r['ai_backend']}" if r["ai_used"] else ""),
            meta,
        ))
        # Transaction table
        header = ["Date", "Description", "Amount", "Category"]
        rows = [[Paragraph(f"<b>{h}</b>", cell) for h in header]]
        for txn in r["transactions"]:
            rows.append([
                Paragraph(fmt_date(txn.get("date")), cell),
                Paragraph(str(txn.get("description", ""))[:70], cell),
                Paragraph(fmt_amount(txn.get("amount")), cell),
                Paragraph(str(txn.get("category", "") or ""), cell),
            ])
        avail = letter[0] - 1.2 * inch
        cw = [avail * p for p in [0.14, 0.46, 0.13, 0.27]]
        tt = Table(rows, colWidths=cw, repeatRows=1)
        tt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.append(tt)
        # Category breakdown
        cc = Counter(txn.get("category") for txn in r["transactions"])
        breakdown = " · ".join(f"{c}: {n}" for c, n in cc.most_common())
        story.append(Paragraph(f"Categories: {breakdown}", note))
        if idx < len(results) - 1:
            story.append(PageBreak())

    doc.build(story)
    return out_path


def main():
    print("=== Running pipeline on one PDF per bank ===")
    results = run_extraction()
    print(f"\n=== Processed {len(results)} banks ===")

    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "verification_results.json")
    write_json(results, json_path)
    print(f"Wrote JSON: {json_path}")

    pdf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "verification_report.pdf")
    build_pdf(results, pdf_path)
    size_mb = os.path.getsize(pdf_path) / 1e6
    print(f"\n✅ Wrote verification PDF: {pdf_path} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    main()
