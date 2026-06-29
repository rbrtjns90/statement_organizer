"""
Transaction Categorizer
-----------------------
Clean reimplementation of the categorization cascade. Replaces the tangled
static/instance mix in BankStatementAnalyzer that:
  - ran keyword matching against *raw* noisy descriptions,
  - discarded AI results unless they EXACTLY matched a category key,
  - broke under multiprocessing with a recurring '_build_ai_prompt' AttributeError
    (the 481KB ai_errors.txt is mostly that one error).

Categorization order (highest priority first):
    1. Learned categories   - merchant -> category persisted from user edits
    2. Normalized keywords  - keyword/substring match on the CLEANED description
    3. AI categorization    - unified AIClient (local -> OpenAI), fuzzy accept
    4. Default              - "Other Business Expenses"

Key fixes vs. the old code:
  * Descriptions are normalized first (description_normalizer) so "CHECKCARD
    1103 LOVES TRAVEL ..." matches the "love's" keyword.
  * AI results are accepted via fuzzy match against the valid category set, not
    exact match, eliminating the "AI Returned: '' -> discard" waste.
  * The batch AI path uses the unified client and JSON helpers - no more
    _build_ai_prompt AttributeError.
  * AI is only called for transactions keyword matching couldn't place, so cost
    stays low and matches the "use the AI model if you have to" strategy.
"""

from __future__ import annotations

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .ai_client import AIClient, get_ai_client, extract_json_object
from .description_normalizer import (
    clean_for_categorization,
    get_merchant_normalizer,
    is_junk_description,
)

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CATEGORIES_PATH = os.path.join(_BASE_DIR, "config", "business_categories.json")
_LEARNED_PATH = os.path.join(_BASE_DIR, "config", "learned_categories.json")

DEFAULT_CATEGORY = "Other Business Expenses"


# ---------------------------------------------------------------------------
# Category loading
# ---------------------------------------------------------------------------
def load_categories(path: str = _CATEGORIES_PATH) -> Dict[str, List[str]]:
    """Load category->keywords from JSON. Falls back to a minimal default."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            # Normalize: every value must be a list of keyword strings.
            return {str(k): [str(x) for x in (v or [])] for k, v in data.items()}
    except Exception as exc:
        print(f"⚠️ Could not load categories from {path}: {exc}")
    return {DEFAULT_CATEGORY: []}


def load_learned(path: str = _LEARNED_PATH) -> Dict[str, str]:
    """Load learned merchant->category map. Never raises."""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
    except Exception as exc:
        print(f"⚠️ Could not load learned categories: {exc}")
    return {}


def save_learned(learned: Dict[str, str], path: str = _LEARNED_PATH) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(learned, fh, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"⚠️ Could not save learned categories: {exc}")


# ---------------------------------------------------------------------------
# Fuzzy category acceptance
# ---------------------------------------------------------------------------
try:
    from rapidfuzz import process, fuzz

    _HAVE_RF = True
except Exception:  # pragma: no cover - optional
    import difflib

    _HAVE_RF = False


def match_category(candidate: Optional[str], categories: Dict[str, List[str]]) -> Optional[str]:
    """Accept an AI/keyword candidate category, allowing fuzzy near-matches.

    Returns the canonical category name, or None if no good match. Old code did
    a strict ``category in categories`` check and threw away e.g. "Office
    Supplies " (trailing space) or "office expenses" vs "Office Supplies".
    """
    if not candidate:
        return None
    candidate = candidate.strip()
    if not candidate:
        return None
    keys = list(categories.keys())
    # 1. Exact.
    if candidate in keys:
        return candidate
    # 2. Case-insensitive exact.
    lowered = {k.lower(): k for k in keys}
    if candidate.lower() in lowered:
        return lowered[candidate.lower()]
    # 3. Fuzzy nearest (>=90 keeps it strict - we don't want to mis-bucket).
    if _HAVE_RF:
        result = process.extractOne(candidate, keys, scorer=fuzz.WRatio)
        if result and result[1] >= 90:
            return result[0]
    else:
        best, best_score = None, 0.0
        for k in keys:
            score = difflib.SequenceMatcher(None, candidate.lower(), k.lower()).ratio()
            if score > best_score:
                best, best_score = k, score
        if best is not None and best_score >= 0.9:
            return best
    return None


# ---------------------------------------------------------------------------
# Keyword matching (normalized)
# ---------------------------------------------------------------------------
def _keyword_match(description: str, categories: Dict[str, List[str]]) -> Optional[str]:
    """Keyword/substring match on the CLEANED description.

    Most-specific categories first (most keywords), longest keywords first.
    """
    if not description:
        return None
    text = clean_for_categorization(description)
    if not text:
        return None
    sorted_categories = sorted(
        categories.items(), key=lambda kv: len(kv[1]), reverse=True
    )
    for category, keywords in sorted_categories:
        for kw in sorted(keywords, key=len, reverse=True):
            if kw and kw.lower() in text:
                return category
    return None


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------
@dataclass
class CategorizationStats:
    total: int = 0
    learned: int = 0
    keyword: int = 0
    ai: int = 0
    default: int = 0
    ai_calls: int = 0
    ai_backend: str = ""


# ---------------------------------------------------------------------------
# Categorizer
# ---------------------------------------------------------------------------
class Categorizer:
    """Owns the categorization cascade for a batch of transactions."""

    def __init__(
        self,
        categories: Optional[Dict[str, List[str]]] = None,
        learned: Optional[Dict[str, str]] = None,
        use_ai: Optional[bool] = None,
        ai_client: Optional[AIClient] = None,
        status_callback=None,
    ):
        self.categories = categories if categories is not None else load_categories()
        if DEFAULT_CATEGORY not in self.categories:
            self.categories[DEFAULT_CATEGORY] = []
        self.learned = learned if learned is not None else load_learned()
        self.merchant_normalizer = get_merchant_normalizer()
        self.status_callback = status_callback or (lambda _msg: None)

        self.ai_client = ai_client if ai_client is not None else get_ai_client()
        # Default: enable AI only if a backend is actually available.
        if use_ai is None:
            use_ai = self.ai_client.available
        self.use_ai = bool(use_ai)

    # -- public -------------------------------------------------------------
    def categorize(
        self,
        transactions: List[Dict[str, Any]],
        parallel: bool = True,
    ) -> CategorizationStats:
        """Categorize a list of transaction dicts in place. Returns stats."""
        stats = CategorizationStats(total=len(transactions))
        # First pass: cheap deterministic resolution (learned + keyword).
        ai_candidates: List[int] = []
        for i, txn in enumerate(transactions):
            category = self._deterministic_category(txn)
            if category is not None:
                txn["category"] = category
                if category != DEFAULT_CATEGORY:
                    if self._matched_learned(txn):
                        stats.learned += 1
                    else:
                        stats.keyword += 1
                else:
                    stats.default += 1
            else:
                # Leave category unset; queue for AI.
                ai_candidates.append(i)

        # Second pass: AI for the remainder (only if enabled + available).
        if ai_candidates and self.use_ai and self.ai_client.available:
            stats.ai_backend = self.ai_client.active_backend
            if parallel and len(ai_candidates) > 8:
                self._categorize_with_ai_parallel(transactions, ai_candidates, stats)
            else:
                self._categorize_with_ai_sequential(transactions, ai_candidates, stats)

        # Anything still uncategorized -> default.
        for txn in transactions:
            if not txn.get("category"):
                txn["category"] = DEFAULT_CATEGORY
                stats.default += 1

        self.status_callback(
            f"🏷️ Categorized {stats.total} txns: "
            f"{stats.learned} learned, {stats.keyword} keyword, "
            f"{stats.ai} AI, {stats.default} default"
        )
        return stats

    # -- deterministic ------------------------------------------------------
    def _matched_learned(self, txn: Dict[str, Any]) -> bool:
        """True if the transaction's category came from learned_categories."""
        cat = txn.get("category")
        return cat in self.learned.values()

    def _deterministic_category(self, txn: Dict[str, Any]) -> Optional[str]:
        """Resolve via learned + keyword. Returns None to defer to AI."""
        description = txn.get("description") or ""
        if is_junk_description(description):
            return DEFAULT_CATEGORY

        text = clean_for_categorization(description)

        # 1. Learned categories (merchant substring match on normalized text).
        for merchant, category in self.learned.items():
            if merchant and merchant.lower() in text:
                # Validate the learned category still exists.
                if category in self.categories:
                    return category

        # 2. Keyword matching on cleaned text.
        kw = _keyword_match(description, self.categories)
        if kw is not None:
            return kw

        # None => caller decides (AI or default).
        return None

    # -- AI -----------------------------------------------------------------
    def _categorize_with_ai_sequential(
        self,
        transactions: List[Dict[str, Any]],
        indices: List[int],
        stats: CategorizationStats,
    ) -> None:
        max_tokens = int(self.ai_client.settings.get("max_tokens_categorization", 400))
        batch_size = int(
            self.ai_client.settings.get("categorization_batch_size", 20)
        )
        for start in range(0, len(indices), batch_size):
            batch_idx = indices[start : start + batch_size]
            batch = [(i, transactions[i]) for i in batch_idx]
            results = self._categorize_batch_ai(batch, max_tokens)
            stats.ai_calls += 1
            for idx, category, used in results:
                transactions[idx]["category"] = category
                if used:
                    stats.ai += 1
                else:
                    stats.default += 1

    def _categorize_with_ai_parallel(
        self,
        transactions: List[Dict[str, Any]],
        indices: List[int],
        stats: CategorizationStats,
    ) -> None:
        """Parallelize AI categorization. OpenAI calls are I/O-bound so we use
        threads; the local llama_cpp backend is serialized internally by the
        AIClient's lock, so threads are still safe (just not faster for local)."""
        max_tokens = int(self.ai_client.settings.get("max_tokens_categorization", 400))
        batch_size = int(
            self.ai_client.settings.get("categorization_batch_size", 20)
        )
        chunks = [indices[i : i + batch_size] for i in range(0, len(indices), batch_size)]
        # Cap workers - OpenAI rate limits, and local is lock-serialized anyway.
        workers = min(4, len(chunks))

        def process_chunk(chunk_indices):
            batch = [(i, transactions[i]) for i in chunk_indices]
            return self._categorize_batch_ai(batch, max_tokens)

        with ThreadPoolExecutor(max_workers=workers) as executor:
            for results in executor.map(process_chunk, chunks):
                stats.ai_calls += 1
                for idx, category, used in results:
                    transactions[idx]["category"] = category
                    if used:
                        stats.ai += 1
                    else:
                        stats.default += 1

    def _categorize_batch_ai(
        self, batch: List[Tuple[int, Dict[str, Any]]], max_tokens: int
    ) -> List[Tuple[int, str, bool]]:
        """Categorize one batch via the unified AIClient. Returns (idx, cat, ai_used)."""
        # Build the batch prompt using NORMALIZED descriptions.
        txn_lines = []
        for i, (idx, txn) in enumerate(batch):
            desc = normalize_description_for_ai(txn.get("description") or "")
            amt = txn.get("amount")
            txn_lines.append(f"{i + 1}. {desc[:60]} | ${amt}")
        category_list = list(self.categories.keys())
        prompt = (
            "Categorize each business transaction into exactly ONE category "
            "from the allowed list.\n\n"
            f"Allowed categories: {', '.join(category_list)}\n\n"
            "Transactions:\n"
            + "\n".join(txn_lines)
            + "\n\nReturn ONLY a JSON object mapping the transaction number to its "
            'category, e.g. {"1": "Office Supplies", "2": "Meals & Entertainment"}. '
            f"If unsure, use \"{DEFAULT_CATEGORY}\"."
        )

        results: List[Tuple[int, str, bool]] = []
        payload = None
        try:
            resp = self.ai_client.chat_text(prompt, max_tokens=max_tokens, temperature=0)
            if resp.success:
                payload = extract_json_object(resp.text)
        except Exception as exc:
            self.status_callback(f"⚠️ AI categorization error: {exc}")

        for i, (idx, txn) in enumerate(batch):
            category = None
            if isinstance(payload, dict):
                # Try numeric and string keys.
                raw = payload.get(str(i + 1)) or payload.get(i + 1)
                if isinstance(raw, dict):
                    raw = raw.get("category")
                category = match_category(raw, self.categories)
            if category is not None:
                results.append((idx, category, True))
            else:
                # AI missed it -> default (keyword already tried in pass 1).
                results.append((idx, DEFAULT_CATEGORY, False))
        return results

    # -- learning -----------------------------------------------------------
    def learn(self, merchant: str, category: str) -> None:
        """Persist a merchant->category mapping (called on user correction).

        Stores the NORMALIZED merchant so future matches are stickier than the
        old raw-substring approach.
        """
        if not merchant or category not in self.categories:
            return
        key = clean_for_categorization(merchant)
        if not key:
            return
        self.learned[key] = category
        save_learned(self.learned)


def normalize_description_for_ai(description: str) -> str:
    """Description prep for the AI prompt: normalized + lightly title-cased.

    We reuse the normalizer so the model sees 'SHELL OIL' rather than
    'SHELL OIL 226002200QPSSARALANDAL'.
    """
    cleaned = get_merchant_normalizer().normalize(description)
    if not cleaned:
        return description.strip()
    return cleaned
