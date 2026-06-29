"""
Confidence-Gated Extraction Pipeline
------------------------------------
The single orchestration layer that turns a PDF into a clean, validated list of
transactions. It implements the "use the AI model if you have to" strategy:

    1. Extract text (existing TextExtractor / pdfplumber).
    2. Detect bank (existing multi-stage cascade).
    3. Run the matched deterministic parser (regex -> ML -> generic).
    4. Route ALL results through ValidationPipeline (dedup + quality scoring).
       Previously only the AI path was validated, so regex/ML/generic output
       flowed straight through with duplicates and junk.
    5. Score document confidence from the validation results.
    6. If confidence is low (or no valid transactions), escalate to AI
       extraction - the "if you have to" step.
    7. Merge, final dedup, normalize amount signs, return.

This replaces the inline logic in BankStatementAnalyzer._extract_pdf_worker
(analyzer.py:197) with a testable, instrumented pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .transaction_validation import Transaction, ValidationPipeline


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class ExtractionResult:
    """Outcome of extracting one PDF."""

    transactions: List[Dict[str, Any]] = field(default_factory=list)
    bank: str = "Unknown"
    confidence: float = 0.0  # 0-100
    parser_source: str = ""  # which deterministic parser handled it
    ai_used: bool = False
    ai_backend: str = ""  # which AI backend served the escalation
    rejected_count: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.transactions)


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------
# Weighting for the deterministic-parser confidence score. Tunable but the
# defaults encode: a confident extraction yields many valid rows with high
# per-row quality from a named (non-generic) parser.
_PARSER_TRUST = {
    "Navy Federal": 0.95,
    "Capital One": 0.95,
    "Citibank": 0.90,
    "Bank of America": 0.90,
    "Chase": 0.85,
    # Generic / ML / unknown are weaker signals - that's the whole point of
    # having an AI fallback.
    "MLBank": 0.55,
    "Generic": 0.40,
    "Unknown": 0.30,
}


def score_confidence(
    parser_source: str,
    valid_count: int,
    raw_count: int,
    mean_quality: float,
) -> float:
    """Compute a 0-100 document-confidence score.

    Factors:
      - parser trust (named parsers >> generic/ML fallbacks)
      - yield (how many raw rows survived validation)
      - mean per-row quality score
    """
    if raw_count <= 0:
        return 0.0
    trust = _PARSER_TRUST.get(parser_source, 0.35)
    # Yield ratio: fraction of extracted rows that survived validation.
    yield_ratio = max(0.0, min(1.0, valid_count / max(1, raw_count)))
    # A statement with a single transaction is suspicious; ramp up with count.
    volume_factor = min(1.0, valid_count / 5.0)
    # Mean quality is already 0-100 -> scale to 0-1.
    quality_factor = max(0.0, min(1.0, mean_quality / 100.0))

    score = 100.0 * (
        0.40 * trust
        + 0.20 * yield_ratio
        + 0.15 * volume_factor
        + 0.25 * quality_factor
    )
    # If literally nothing survived validation, there is no confidence.
    if valid_count == 0:
        score = 0.0
    return round(max(0.0, min(100.0, score)), 1)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------
def normalize_amount_sign(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Make amount conventions consistent: expenses are positive floats.

    Different sources use different conventions:
      - generic regex path forces expenses positive via abs() (analyzer.py:286)
      - AI extraction returns negative for debits (ai_detector.py:297)
      - some parsers emit signed amounts
    Downstream code (totals, Schedule C) applies abs() defensively, but
    normalizing once here removes ambiguity.
    """
    for txn in transactions:
        amt = txn.get("amount")
        if isinstance(amt, (int, float)):
            txn["amount"] = abs(float(amt))
        elif amt is None:
            continue
        else:
            # Try to coerce strings.
            try:
                txn["amount"] = abs(float(str(amt).replace("$", "").replace(",", "")))
            except (ValueError, TypeError):
                txn["amount"] = None
    return transactions


def _transactions_to_dicts(transactions: List[Transaction]) -> List[Dict[str, Any]]:
    """Convert validated Transaction dataclasses back to the dict format the rest
    of the system uses (analyzer/GUI/Schedule C all expect dicts)."""
    out = []
    for txn in transactions:
        out.append(
            {
                "date": txn.date,
                "description": txn.description,
                "amount": txn.amount,
                "category": txn.category,
                "source": txn.source,
                "page": txn.page,
                "raw_data": txn.raw_data,
                # Preserve common auxiliary keys parsers may have attached.
                **{
                    k: v
                    for k, v in txn.raw_data.items()
                    if k not in {"date", "description", "amount", "category"}
                },
            }
        )
    return out


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class ExtractionPipeline:
    """Orchestrates deterministic extraction + confidence-gated AI escalation."""

    def __init__(
        self,
        confidence_threshold: Optional[float] = None,
        validation_min_quality: float = 25.0,
        ai_min_quality: float = 20.0,
    ):
        """
        Args:
            confidence_threshold: below this (0-100) we escalate to AI. Reads
                the config default (50) when None.
            validation_min_quality: min quality for deterministic output.
            ai_min_quality: relaxed min quality for AI output.
        """
        from .ai_client import load_ai_settings

        settings = load_ai_settings()
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else float(settings.get("extraction_confidence_threshold", 50))
        )
        self.validation_min_quality = validation_min_quality
        self.ai_min_quality = ai_min_quality
        self.settings = settings

    # -- public entry -------------------------------------------------------
    def extract(self, pdf_path: str, status_callback=None) -> ExtractionResult:
        """Run the full pipeline on one PDF."""
        result = ExtractionResult()
        self._notify = status_callback or (lambda _msg: None)

        # Step 1: text extraction
        text = self._extract_text(pdf_path)
        if not text.strip():
            result.notes.append("no text extracted from PDF")
            self._notify("⚠️ No text could be extracted; attempting AI/vision")
            # Text-less PDF -> jump straight to AI extraction.
            return self._escalate_to_ai(pdf_path, result, force=True)

        # Step 1b: consult format memory. If this layout was previously handled
        # by AI extraction (a recurring unknown bank), skip straight to AI and
        # save the cost of failed deterministic attempts. This is the "learning
        # loop" - the system gets cheaper to run over time.
        try:
            from . import format_memory

            known = format_memory.should_skip_to_ai(text)
            if known:
                result.bank = known.get("bank", "Unknown")
                self._notify(
                    f"🧠 Recognized layout (seen {known.get('seen_count', 1)}x) — "
                    f"using AI extraction directly"
                )
                return self._escalate_to_ai(pdf_path, result, force=True)
        except Exception as exc:
            self._notify(f"⚠️ Format memory check failed: {exc}")

        # Step 2: bank detection
        bank = self._detect_bank(text, pdf_path)
        result.bank = bank
        self._notify(f"🏦 Detected bank: {bank}")

        # Step 3: deterministic parser
        parser_source, raw_transactions = self._run_deterministic_parser(
            text, pdf_path, bank
        )
        result.parser_source = parser_source
        raw_count = len(raw_transactions)

        # Step 3b: universal summary-row + dedup filter.
        # Applied to ALL parser output (Chase, BofA, ML, generic) so junk rows
        # like "Previous Balance" / "New Balance" never leak through. This is the
        # centralized fix for the Chase summary-row bug; previously only the
        # generic parser filtered these.
        from .transaction_filters import clean_transactions

        before_filter = len(raw_transactions)
        raw_transactions = clean_transactions(raw_transactions)
        if before_filter != len(raw_transactions):
            self._notify(
                f"🧹 Filtered {before_filter - len(raw_transactions)} "
                f"summary/junk rows"
            )
            raw_count = len(raw_transactions)

        # Step 4: validate (universal - the key fix)
        valid_txns, mean_quality = self._validate(
            raw_transactions, source=parser_source, min_quality=self.validation_min_quality
        )
        result.rejected_count = max(0, raw_count - len(valid_txns))

        # Step 5: confidence score
        result.confidence = score_confidence(
            parser_source, len(valid_txns), raw_count, mean_quality
        )

        # Step 6: escalate to AI if low confidence / no valid txns
        if len(valid_txns) == 0 or result.confidence < self.confidence_threshold:
            self._notify(
                f"🤖 Low confidence ({result.confidence}/100) — escalating to AI extraction"
            )
            return self._escalate_to_ai(
                pdf_path,
                result,
                prior_transactions=_transactions_to_dicts(valid_txns),
            )

        # Step 7: finalize (dicts + normalized amounts)
        result.transactions = normalize_amount_sign(_transactions_to_dicts(valid_txns))
        self._notify(
            f"✅ Extracted {result.count} transactions "
            f"(confidence {result.confidence}/100) via {parser_source}"
        )
        return result

    # -- steps --------------------------------------------------------------
    def _extract_text(self, pdf_path: str) -> str:
        """Use pdfplumber (matches the production path; Vision OCR is disabled)."""
        try:
            import pdfplumber

            parts = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    parts.append(page.extract_text() or "")
            return "\n".join(parts)
        except Exception as exc:
            self._notify(f"⚠️ Text extraction failed: {exc}")
            return ""

    def _detect_bank(self, text: str, pdf_path: str) -> str:
        try:
            from .registry import detect_bank

            return detect_bank(text, pdf_path)
        except Exception as exc:
            self._notify(f"⚠️ Bank detection failed: {exc}")
            return "Unknown"

    def _run_deterministic_parser(
        self, text: str, pdf_path: str, bank: str
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Try the registry first, then a bank-specific lookup. Returns (source, txns)."""
        from . import parser_registry

        parser = parser_registry.get_parser(text)
        if parser is None and bank != "Unknown":
            try:
                from .registry import get_parser_for_bank

                parser = get_parser_for_bank(bank)
            except Exception:
                parser = None

        if parser is not None:
            try:
                txns = parser.extract_transactions(text) or []
                return (parser.bank_name or "Unknown", txns)
            except Exception as exc:
                self._notify(f"⚠️ Parser '{parser.bank_name}' failed: {exc}")

        # Final fallback: the analyzer's inline generic extractor.
        return ("Generic", self._generic_fallback(text))

    def _validate(
        self, raw_transactions: List[Dict[str, Any]], source: str, min_quality: float
    ) -> Tuple[List[Transaction], float]:
        """Run the validation pipeline. Returns (valid, mean_quality)."""
        if not raw_transactions:
            return [], 0.0
        pipeline = ValidationPipeline(min_quality_score=min_quality)
        valid = pipeline.validate_extraction_result(raw_transactions, source=source)
        if valid:
            # Recover per-transaction quality scores for confidence math.
            qualities = []
            if pipeline.validator is not None:
                # Re-score the survivors cheaply (validator already deduped).
                for txn in valid:
                    res = pipeline.validator.validate(txn)
                    qualities.append(res.quality_score)
            mean_q = sum(qualities) / len(qualities) if qualities else 50.0
        else:
            mean_q = 0.0
        return valid, mean_q

    def _generic_fallback(self, text: str) -> List[Dict[str, Any]]:
        """Thin wrapper around the analyzer's static generic extractor, so the
        pipeline can stand alone without importing the heavy GUI/categorization
        machinery. Mirrors BankStatementAnalyzer._extract_generic_transactions_static."""
        import re
        from datetime import datetime

        transactions = []
        patterns = [
            r"(\d{1,2}/\d{1,2}/\d{2,4})\s+(.+?)\s+([-]?\$?[\d,]+\.?\d*)\s*$",
            r"(\d{1,2}/\d{1,2})\s+(.+?)\s+([-]?\$?[\d,]+\.?\d*)\s*$",
            r"(\d{4}-\d{1,2}-\d{1,2})\s+(.+?)\s+([-]?\$?[\d,]+\.?\d*)\s*$",
        ]
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            for pattern in patterns:
                match = re.search(pattern, line)
                if not match:
                    continue
                try:
                    date_str, description, amount_str = (
                        match.group(1),
                        match.group(2).strip(),
                        match.group(3),
                    )
                    if "/" in date_str:
                        if len(date_str.split("/")) == 2:
                            date_str += f"/{datetime.now().year}"
                        date_obj = datetime.strptime(date_str, "%m/%d/%Y")
                    else:
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                    cleaned = amount_str.replace("$", "").replace(",", "")
                    if cleaned.startswith("(") and cleaned.endswith(")"):
                        amount = -float(cleaned[1:-1])
                    else:
                        amount = float(cleaned)
                    transactions.append(
                        {
                            "date": date_obj,
                            "description": description,
                            "amount": abs(amount),
                            "category": None,
                            "bank": "Generic",
                        }
                    )
                    break
                except (ValueError, IndexError):
                    continue
        return transactions

    # -- AI escalation ------------------------------------------------------
    def _escalate_to_ai(
        self,
        pdf_path: str,
        result: ExtractionResult,
        prior_transactions: Optional[List[Dict[str, Any]]] = None,
        force: bool = False,
    ) -> ExtractionResult:
        """Fall back to AI extraction and merge with any prior transactions."""
        prior_transactions = prior_transactions or []

        from .ai_client import get_ai_client

        client = get_ai_client()
        if not client.available:
            result.notes.append("AI extraction requested but no backend available")
            self._notify("⚠️ No AI backend available; returning best deterministic result")
            result.transactions = normalize_amount_sign(prior_transactions)
            result.confidence = result.confidence or 0.0
            return result

        try:
            from .ai_detector import extract_transactions_with_ai

            ai_txns = extract_transactions_with_ai(pdf_path)
        except Exception as exc:
            result.notes.append(f"AI extraction error: {exc}")
            self._notify(f"❌ AI extraction failed: {exc}")
            ai_txns = []

        if ai_txns:
            result.ai_used = True
            result.ai_backend = client.active_backend
            self._notify(
                f"🤖 AI extracted {len(ai_txns)} transactions ({result.ai_backend})"
            )
            # Learning loop: remember this layout so the next identical-format
            # statement skips straight to AI (no wasted deterministic attempts).
            try:
                from . import format_memory

                text = self._extract_text(pdf_path)
                if text.strip():
                    format_memory.remember(
                        text,
                        bank=result.bank or "Unknown",
                        source="ai_extraction",
                        sample_path=pdf_path,
                    )
            except Exception:
                pass  # memory is best-effort; never block extraction

        # Merge AI output with any prior deterministic transactions, then dedup.
        merged = list(prior_transactions) + list(ai_txns)
        merged = self._merge_and_dedup(merged)
        result.transactions = normalize_amount_sign(merged)

        # Recompute confidence from the merged set (AI path).
        if ai_txns and not prior_transactions:
            result.parser_source = result.parser_source or "AI"
        result.confidence = max(result.confidence, 70.0 if ai_txns else 0.0)
        self._notify(
            f"✅ Final: {result.count} transactions after AI merge (confidence {result.confidence}/100)"
        )
        return result

    def _merge_and_dedup(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Dedup merged transactions using the validator's fingerprint logic."""
        if not transactions:
            return []
        import re

        seen = {}
        out = []
        for txn in transactions:
            desc = str(txn.get("description", "")).lower()
            desc_norm = re.sub(r"[^\w]", "", desc)
            amount = txn.get("amount")
            amount_key = f"{abs(float(amount)):.2f}" if isinstance(amount, (int, float)) else "0.00"
            d = txn.get("date")
            if hasattr(d, "strftime"):
                date_key = d.strftime("%Y-%m")
            else:
                date_key = "unknown"
            fp = f"{desc_norm}_{amount_key}_{date_key}"
            if fp in seen:
                # Prefer the entry that already has more metadata (source, page).
                existing = out[seen[fp]]
                if len(str(existing.get("source", ""))) < len(str(txn.get("source", ""))):
                    out[seen[fp]] = txn
                continue
            seen[fp] = len(out)
            out.append(txn)
        return out
