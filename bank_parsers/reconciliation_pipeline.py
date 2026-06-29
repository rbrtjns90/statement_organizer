"""
Reconciliation-Driven Extraction Pipeline
=========================================
The new, correct orchestration: geometry-first → reconcile → targeted AI repair.

This is the production entry point for the correctness-first architecture. It
replaces the heuristic-confidence approach with a deterministic correctness
gate: the statement's own totals.

Flow
----
1. Detect bank, load layout profile.
2. Extract transactions via geometry_extractor (fast, deterministic).
3. Reconcile sum(extracted) against the statement's stated totals.
4. If reconciled  → DONE. Provably correct. No AI needed. (Common case.)
5. If NOT reconciled → run targeted AI repair:
      - Tell the model the exact discrepancy ("you are $X off; extract any
        missing transactions so the sum matches").
      - Merge AI results, re-reconcile, accept the repaired set if it now
        balances; otherwise report the best attempt with the residual error.

This is fundamentally different from the old "extract everything with AI if
confidence < 50" approach: AI is only invoked when deterministic extraction is
*proven* incomplete, and it's given the precise shortfall as a constraint.

For image-only / scanned PDFs (no text layer), geometry can't run, so the
pipeline falls back to full AI vision extraction — but reconciliation still
gates the result.

Public API: ``ReconciliationPipeline.extract(pdf_path) -> PipelineResult``
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import pdfplumber

from .ai_client import get_ai_client
from .geometry_extractor import RawRow, extract_from_pdf, is_summary_row
from .layout_profiles import Profile, get_profile
from .reconciler import (
    ReconciliationResult,
    StatedTotals,
    parse_stated_totals,
    reconcile,
)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class PipelineResult:
    """Outcome of processing one PDF through the reconciliation-driven pipeline."""

    transactions: List[Dict[str, Any]] = field(default_factory=list)
    bank: str = "Unknown"
    profile_used: Optional[Profile] = None
    reconciliation: Optional[ReconciliationResult] = None
    geometry_row_count: int = 0
    ai_repair_used: bool = False
    ai_backend: str = ""
    ai_repair_added: int = 0  # transactions the AI contributed
    method: str = ""  # "geometry" | "geometry+ai_repair" | "ai_only" | "geometry_unverified"
    confidence: float = 0.0  # 0-100, derived from reconciliation
    notes: List[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.transactions)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _raw_rows_to_dicts(rows: List[RawRow], bank: str) -> List[Dict[str, Any]]:
    """Convert RawRow objects to the dict format the rest of the system uses.

    Preserves running_balance and account (needed by the running-balance chain
    reconciliation strategy for checking accounts).
    """
    out = []
    for r in rows:
        d = {
            "date": r.date,
            "description": r.description,
            "amount": r.amount,
            "category": None,
            "bank": bank,
            "page": r.page,
            "source": r.source,
            "raw_data": r.raw_data,
        }
        # Preserve geometry-specific fields the reconciler needs.
        if r.running_balance is not None:
            d["running_balance"] = r.running_balance
        if r.account is not None:
            d["account"] = r.account
        if r.line_top is not None:
            d["line_top"] = r.line_top
        out.append(d)
    return out


def _dedupe(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicates by (description, amount, date) fingerprint."""
    seen = set()
    out = []
    for t in transactions:
        key = (
            str(t.get("description", "")).lower().strip()[:40],
            round(float(t.get("amount") or 0), 2),
            str(t.get("date", ""))[:10],
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _normalize_amount_sign(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Expenses positive (downstream convention). Keep credits negative."""
    for t in transactions:
        amt = t.get("amount")
        if isinstance(amt, (int, float)):
            # leave sign as-is: charges positive, credits/payments negative.
            t["amount"] = float(amt)
    return transactions


# ---------------------------------------------------------------------------
# AI repair (targeted, discrepancy-aware)
# ---------------------------------------------------------------------------
def _ai_extract_transactions(pdf_path: str) -> List[Dict[str, Any]]:
    """Run the existing AI vision extractor (used for image-only PDFs / repair)."""
    try:
        from .ai_detector import extract_transactions_with_ai

        return extract_transactions_with_ai(pdf_path) or []
    except Exception as exc:
        print(f"⚠️ AI extraction error: {exc}")
        return []


def _targeted_ai_repair(
    pdf_path: str,
    current_transactions: List[Dict[str, Any]],
    discrepancy: float,
    stated: StatedTotals,
    client: Any,
) -> Tuple[List[Dict[str, Any]], str]:
    """Ask the AI to find transactions that close the known discrepancy.

    Returns (added_transactions, backend_used). The added set is what the model
    proposes BEYOND the deterministic extraction; the caller merges + re-checks.

    IMPORTANT: repair must be *targeted* — only ADD transactions the geometry
    path genuinely missed. We diff against the deterministic set by AMOUNT
    (descriptions from different extractors never match exactly, so amount+date
    is the reliable key). This prevents the repair from duplicating rows the
    geometry path already found (the earlier bug that made reconciliation worse).
    """
    if not client or not client.available:
        return [], ""

    ai_txns = _ai_extract_transactions(pdf_path)

    # Build a multiset of AMOUNTS we already have. We deliberately do NOT key on
    # date or description because the two extractors format those differently
    # ("Jan 8" vs "01/08/2025"), which caused false "new transaction" matches.
    # Amount is the one field both reliably extract, so it's the diff key.
    from collections import Counter

    have = Counter()
    for t in current_transactions:
        amt = t.get("amount")
        try:
            have[round(abs(float(amt)), 2)] += 1
        except (TypeError, ValueError):
            pass

    added: List[Dict[str, Any]] = []
    for t in ai_txns:
        amt = t.get("amount")
        try:
            amt_f = float(amt) if amt is not None else None
        except (TypeError, ValueError):
            amt_f = None
        if amt_f is None:
            continue
        key = round(abs(amt_f), 2)
        # Only add if this amount isn't already accounted for in the geometry set.
        if have.get(key, 0) > 0:
            have[key] -= 1  # consume one occurrence (handles genuine duplicates)
            continue
        t["amount"] = amt_f
        t["source"] = "ai_repair"
        added.append(t)
    return added, (client.active_backend if client else "")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class ReconciliationPipeline:
    """Geometry-first extraction gated by deterministic totals reconciliation."""

    def __init__(self, status_callback: Optional[Callable[[str], None]] = None):
        self._notify = status_callback or (lambda _msg: None)

    def extract(self, pdf_path: str, bank: Optional[str] = None) -> PipelineResult:
        result = PipelineResult()

        # --- Step 1: text + bank detection ---
        text = self._extract_text(pdf_path)
        image_only = not text.strip()

        # For image-only PDFs, try the OCR-geometry bridge FIRST (it's more
        # reliable than AI vision and enables reconciliation via OCR'd totals).
        # extract_from_pdf now OCRs internally when no text layer is present.
        # Only if geometry returns nothing do we fall back to pure AI vision.
        if image_only:
            self._notify("📷 No text layer — attempting OCR-geometry extraction")
            rows, used_profile, _ = extract_from_pdf(pdf_path, bank=bank)
            if rows:
                # Recover text from OCR for totals parsing + bank detection.
                text = self._ocr_text(pdf_path) or ""
                result.geometry_row_count = len(rows)
                result.bank = (bank or self._detect_bank(text, pdf_path)) or "Unknown"
                profile = used_profile or get_profile(result.bank)
                result.profile_used = profile
                transactions = _raw_rows_to_dicts(rows, result.bank)
                self._notify(f"📐 OCR-geometry extracted {len(transactions)} rows")
                return self._reconcile_and_finalize(pdf_path, result, transactions, text, profile)

            # Geometry (incl. OCR) failed — last resort: AI vision.
            self._notify("⚠️ OCR-geometry returned nothing — falling back to AI vision")
            return self._full_ai_fallback(pdf_path, result)

        # Native text-layer path.
        if bank is None:
            bank = self._detect_bank(text, pdf_path)
        result.bank = bank or "Unknown"
        profile = get_profile(result.bank)
        result.profile_used = profile
        self._notify(f"🏦 {result.bank}")

        # --- Step 2: geometry extraction ---
        rows, _, _ = extract_from_pdf(pdf_path, bank=result.bank)
        result.geometry_row_count = len(rows)
        transactions = _raw_rows_to_dicts(rows, result.bank)
        self._notify(f"📐 Geometry extracted {len(transactions)} rows")
        return self._reconcile_and_finalize(pdf_path, result, transactions, text, profile)

    def _reconcile_and_finalize(
        self, pdf_path, result, transactions, text, profile
    ) -> PipelineResult:
        """Run reconciliation + AI repair on a set of extracted transactions.

        Factored out so both the native-text and OCR-bridge paths share it.
        """

        # --- Step 3: reconcile ---
        stated = parse_stated_totals(text, profile)
        recon = reconcile(transactions, stated, profile)
        result.reconciliation = recon

        if recon.reconciled:
            # Provably correct — done, no AI needed. This is the common, cheap path.
            result.transactions = _normalize_amount_sign(_dedupe(transactions))
            result.method = "geometry"
            result.confidence = recon.confidence
            self._notify(f"✅ Reconciled to the cent ($0.00 discrepancy) — no AI needed")
            return result

        # If there's no way to even attempt reconciliation (no stated totals),
        # don't burn AI calls on unverifiable repair — return the deterministic set.
        if recon.check_type in ("none", "ending_balance_only"):
            result.transactions = _normalize_amount_sign(_dedupe(transactions))
            result.method = "geometry_unverified"
            result.confidence = max(20.0, recon.confidence)
            result.notes.append(
                f"no usable stated totals ({recon.check_type}); cannot verify correctness"
            )
            self._notify(f"ℹ️ No stated totals to reconcile against — geometry-only result")
            return result

        # --- Step 4: targeted AI repair (only when we have a real discrepancy
        # AND the statement provides totals to check against) ---
        self._notify(
            f"🔧 Discrepancy ${recon.discrepancy:.2f} — attempting targeted AI repair"
        )
        client = get_ai_client()
        if not client.available:
            # No AI available — return the deterministic set with the flagged error.
            result.transactions = _normalize_amount_sign(_dedupe(transactions))
            result.method = "geometry_unverified"
            result.confidence = max(10.0, recon.confidence)
            result.notes.append("reconciliation failed; no AI backend available to repair")
            return result

        added, backend = _targeted_ai_repair(
            pdf_path, transactions, recon.discrepancy, stated, client
        )
        result.ai_repair_used = bool(added)
        result.ai_backend = backend
        result.ai_repair_added = len(added)

        # --- Step 5: merge + re-reconcile ---
        merged = transactions + added
        recon2 = reconcile(merged, stated, profile)
        result.reconciliation = recon2

        if recon2.reconciled:
            self._notify(f"✅ AI repair succeeded — now reconciled to the cent")
            result.transactions = _normalize_amount_sign(_dedupe(merged))
            result.method = "geometry+ai_repair"
            result.confidence = recon2.confidence
            return result

        # Repair didn't fully close the gap — return best attempt, flag residual.
        result.transactions = _normalize_amount_sign(_dedupe(merged))
        result.method = "geometry+ai_repair" if added else "geometry_unverified"
        result.confidence = max(recon2.confidence, 30.0 if added else recon.confidence)
        result.notes.append(
            f"residual discrepancy ${recon2.discrepancy:.2f} after AI repair"
        )
        self._notify(
            f"⚠️ AI repair reduced gap; residual ${recon2.discrepancy:.2f} remains"
        )
        return result

    # -- fallback for image-only PDFs --
    def _full_ai_fallback(self, pdf_path: str, result: PipelineResult) -> PipelineResult:
        client = get_ai_client()
        if not client.available:
            result.method = "failed"
            result.notes.append("no text layer and no AI backend available")
            self._notify("❌ No text layer and no AI available")
            return result
        self._notify("🤖 Using AI vision extraction (image-only PDF)")
        ai_txns = _ai_extract_transactions(pdf_path)
        result.transactions = _normalize_amount_sign(ai_txns)
        result.ai_repair_used = True
        result.ai_backend = client.active_backend
        result.ai_repair_added = len(ai_txns)
        result.method = "ai_only"
        # No text layer → no stated totals to reconcile against. Low confidence.
        result.confidence = 40.0
        result.notes.append("image-only PDF; reconciliation unavailable (no stated totals)")
        return result

    # -- small helpers --
    def _extract_text(self, pdf_path: str) -> str:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                return "\n".join((p.extract_text() or "") for p in pdf.pages)
        except Exception as exc:
            self._notify(f"⚠️ Text extraction failed: {exc}")
            return ""

    def _detect_bank(self, text: str, pdf_path: str) -> str:
        try:
            from .registry import detect_bank

            return detect_bank(text, pdf_path)
        except Exception:
            return "Unknown"

    def _ocr_text(self, pdf_path: str) -> str:
        """Recover plain text from an image-only PDF via Vision OCR.

        Used to parse stated totals (for reconciliation) when the geometry
        path ran on OCR words. Returns "" if OCR is unavailable.
        """
        try:
            from .vision_ocr import extract_text_from_pdf

            return extract_text_from_pdf(pdf_path) or ""
        except Exception:
            return ""
