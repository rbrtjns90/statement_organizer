"""
Description Normalizer
---------------------
Cleans raw bank-statement transaction descriptions into a canonical merchant
name so that categorization (keyword matching + AI) sees consistent text.

Why this exists
---------------
Raw descriptions look like:
    "CHECKCARD 1103 LOVES TRAVEL S00004051 BRUNSWICK GA 24164..."
    "LOVE'S #0387 INSIDE8006556837 SC 55432864359200400282699"
    "POS Debit- Debit Card 0972 08-03-24 Ett*chimneysgreenv 801-8775491 TX"
    "12/27 Online payment from CHK 4155 36206005720014323865308"

Both keyword matching and the AI model struggle with this noise, which is why
categorization accuracy has been poor. This normalizer strips:
  - leading transaction/card-prefix noise (CHECKCARD, POS Debit-, VISA DD, ...)
  - leading dates and long reference numbers
  - trailing reference numbers, phone numbers, glued state codes
  - excess punctuation/whitespace

It also offers optional merchant normalization against a vendor cache using
rapidfuzz (falls back to difflib if rapidfuzz is unavailable).

The normalizer is idempotent and never raises - worst case it returns the
original text.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

# Optional fuzzy matching (degrades gracefully to difflib).
try:
    from rapidfuzz import fuzz, process

    HAVE_RAPIDFUZZ = True
except Exception:  # pragma: no cover - optional dep
    import difflib

    HAVE_RAPIDFUZZ = False

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENDOR_CACHE_PATH = os.path.join(_BASE_DIR, "utils", "vendor_cache.json")


# ---------------------------------------------------------------------------
# Noise patterns
# ---------------------------------------------------------------------------
# Leading prefixes banks prepend before the actual merchant name.
_LEADING_PREFIXES = [
    r"checkcard\s+\d*\s*",
    r"purchase\s+authorized\s+on\s+\d{1,2}[/\-]\d{1,2}[/\-]?\d*\s*",  # PURCHASE AUTHORIZED ON 11/03
    r"visa\s*dd\s*\d*\s*",
    r"pos\s+debit[-\s]*debit\s+card\s+\d{4}\s*",  # POS Debit- Debit Card 0972
    r"pos\s+credit\s+adjustment\s+\d*\s*",  # POS Credit Adjustment 0972
    r"pos\s+debit[-\s]*\d*\s*",
    r"pos\s+credit[-\s]*\d*\s*",
    r"debit\s+card\s+(purchase\s+)?\d*\s*",
    r"recurring\s+(card\s+)?(payment|purchase)\s+\d*\s*",
    r"online\s+payment\s+\d*\s*",  # Online payment <ref>
    r"point\s+of\s+sale\s+withdrawal\s+\d*\s*",
    # Leading date in common formats: 12/27, 12/27/2024, 2024-08-03, 08-03-24
    r"\d{1,2}[/\-]\d{1,2}([/\-]\d{2,4})?\s+",
    r"\d{4}[/\-]\d{1,2}[/\-]\d{1,2}\s+",
]

# Compiled (case-insensitive) leading-stripper.
_LEADING_RE = re.compile(
    r"^(?:" + "|".join(_LEADING_PREFIXES) + r")+", re.IGNORECASE
)

# Long digit runs (transaction/reference/ARCs). Keep very short token-like
# sequences such as a store number "#0387" intact where possible.
_LONG_DIGIT_RUN = re.compile(r"\b\d{10,}\b")

# Trailing reference numbers / phone numbers / glued state+long-numeric tail.
# Examples: "... TX 55432864359200400282699", "... 801-8775491 TX"
_TRAILING_NUMERIC = re.compile(
    r"\s+\d{3}[-\s]?\d{3,4}[-\s]?\d{0,4}\s*[A-Z]{2}?\s*$"  # phone-ish
)
_TRAILING_LONG_DIGITS = re.compile(r"\s+\d{8,}\s*$")

# 2-letter US state codes glued to the end of a token ("MOSSY HEADFL",
# "SARALANDAL", "INSIDE8006556837 SC"). We detach a trailing 2-letter code.
_GLUED_STATE = re.compile(r"([A-Z]{2})([A-Z]{2})$")  # WORDSTATE -> WORD STATE

# Phone numbers anywhere.
_PHONE = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")

# Words/segments that are pure noise tokens (long alnum reference blobs).
_ARC_TOKEN = re.compile(r"^[A-Z]?\*?[A-Z0-9]{12,}$")

# Known non-transaction junk lines (summary/total rows). These slip through
# some parsers; flagging them lets categorization skip or bucket them.
JUNK_PATTERNS = [
    r"^previous\s+balance$",
    r"^new\s+balance$",
    r"^ending\s+balance$",
    r"^available\s+(credit|balance)$",
    r"^current\s+balance$",
    r"^past\s+due\s+amount$",
    r"^balance\s+over\s+the\s+credit\s+limit$",
    r"^cash\s+advances?$",
    r"^fees\s+charged$",
    r"^interest\s+charged",
    r"^total\s+(payments|credits|debits|charges|fees|new\s+balance)",
    r"^summary$",
    r"^payments?/other\s+credits$",
    r"^purchases\s+and\s+adjustments?$",
    r"^costco\s+cash\s+back\s+rewards?\s+summary$",
]
_JUNK_RE = [re.compile(p, re.IGNORECASE) for p in JUNK_PATTERNS]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _strip_leading_noise(text: str) -> str:
    return _LEADING_RE.sub("", text, count=1)


def _strip_reference_numbers(text: str) -> str:
    text = _LONG_DIGIT_RUN.sub(" ", text)
    text = _PHONE.sub(" ", text)
    return text


def _strip_trailing_noise(text: str) -> str:
    # Iteratively peel trailing numeric/state noise.
    prev = None
    while prev != text:
        prev = text
        text = _TRAILING_LONG_DIGITS.sub("", text)
        text = _TRAILING_NUMERIC.sub("", text)
        # Drop a lone trailing 2-letter state code.
        text = re.sub(r"\s+[A-Z]{2}\s*$", "", text)
        text = text.rstrip()
    return text


def _split_glued_state(text: str) -> str:
    """Turn 'SARALANDAL' -> 'SARALAND AL' for the last token if it ends in a
    plausible 2-letter state. Conservative: only the final token, only if it
    otherwise ends in a glued uppercase pair."""
    tokens = text.split()
    if not tokens:
        return text
    last = tokens[-1]
    m = _GLUED_STATE.search(last)
    if m and len(last) > 4:
        tokens[-1] = last[: m.start() + 2] + " " + last[m.start() + 2 :]
        return " ".join(tokens)
    return text


def _drop_arc_tokens(tokens: List[str]) -> List[str]:
    """Remove standalone long alphanumeric reference blobs."""
    return [t for t in tokens if not _ARC_TOKEN.match(t)]


def _titlecase_merchant(text: str) -> str:
    """Conservative title-casing that preserves known acronyms (AWS, API, CA)."""
    if not text:
        return text
    out = []
    for word in text.split():
        if not word:
            continue
        # Keep all-caps short tokens (likely acronyms) as-is.
        if word.isupper() and 2 <= len(word) <= 5:
            out.append(word)
        elif word.startswith("#"):
            out.append(word)
        else:
            out.append(word.capitalize())
    return " ".join(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def is_junk_description(description: str) -> bool:
    """True if the line is a known summary/balance/header row, not a real txn."""
    if not description:
        return True
    s = description.strip().lower()
    return any(p.search(s) for p in _JUNK_RE)


def normalize_description(description: str) -> str:
    """Clean a raw bank description into a canonical merchant name.

    Idempotent and exception-safe. Returns "" for empty input.
    """
    if not description or not description.strip():
        return ""
    try:
        text = description.strip()
        # 1. Remove leading bank/date noise.
        text = _strip_leading_noise(text)
        # 2. Remove long reference numbers and phone numbers.
        text = _strip_reference_numbers(text)
        # 3. Detach glued state codes.
        text = _split_glued_state(text)
        # 4. Remove trailing numeric/state noise.
        text = _strip_trailing_noise(text)
        # 5. Drop standalone ARC tokens and collapse whitespace/punctuation.
        tokens = _drop_arc_tokens(re.split(r"\s+", text))
        text = " ".join(tokens)
        text = re.sub(r"\s*[\*/]+\s*", " ", text)  # "*" separators from card prefixes
        text = re.sub(r"\s{2,}", " ", text).strip(" -")
        if not text:
            return description.strip()  # never return empty if we had input
        return text
    except Exception:
        return description.strip()


def clean_for_categorization(description: str) -> str:
    """Lowercased, normalized description optimized for keyword/AI matching."""
    cleaned = normalize_description(description)
    return cleaned.lower()


class MerchantNormalizer:
    """Fuzzy merchant normalization against a vendor cache (optional).

    The cache maps a raw (cleaned) string to a canonical name. On a near-match
    (high similarity), we return the cached canonical name; otherwise we return
    the normalized description unchanged. This is best-effort and degrades to
    plain normalization when no cache / rapidfuzz is present.
    """

    def __init__(self, cache_path: str = _VENDOR_CACHE_PATH, threshold: float = 90.0):
        self.threshold = threshold
        self.cache: Dict[str, str] = {}
        self.canonical_names: List[str] = []
        self._load(cache_path)

    def _load(self, path: str) -> None:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    # The cache maps raw->titlecased; we key on normalized raw
                    # and value on a normalized canonical.
                    for raw, canon in data.items():
                        key = normalize_description(raw)
                        val = normalize_description(canon) or canon
                        if key:
                            self.cache[key] = val
                    self.canonical_names = list(set(self.cache.values()))
        except Exception as exc:  # pragma: no cover
            print(f"⚠️ Could not load vendor cache {path}: {exc}")

    def normalize(self, description: str) -> str:
        """Return the canonical merchant name, or the normalized description."""
        base = normalize_description(description)
        if not base:
            return ""
        # Exact cache hit.
        if base in self.cache:
            return self.cache[base]
        # Fuzzy match against known canonicals (only if we have any).
        if self.canonical_names:
            match = self._best_match(base)
            if match is not None:
                return match
        return base

    def _best_match(self, text: str) -> Optional[str]:
        if HAVE_RAPIDFUZZ:
            result = process.extractOne(
                text, self.canonical_names, scorer=fuzz.token_sort_ratio
            )
            if result and result[1] >= self.threshold:
                return result[0]
            return None
        # difflib fallback.
        best = None
        best_score = 0.0
        for name in self.canonical_names:
            score = difflib.SequenceMatcher(None, text, name).ratio() * 100
            if score > best_score:
                best_score = score
                best = name
        if best is not None and best_score >= self.threshold:
            return best
        return None


# Module-level singleton (cache load is the expensive part).
_normalizer: Optional[MerchantNormalizer] = None


def get_merchant_normalizer() -> MerchantNormalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = MerchantNormalizer()
    return _normalizer
