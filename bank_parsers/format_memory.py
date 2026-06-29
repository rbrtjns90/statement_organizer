"""
Format Memory
-------------
Remembers bank-statement *layouts* the system has successfully handled, so that
future statements with the same layout can be parsed without escalating to AI.

Why this exists
---------------
The confidence-gated pipeline escalates to AI when a deterministic parser can't
handle a statement (Phase 2). That's correct, but for a *recurring* unknown bank
(e.g. every month) it would re-run AI extraction on every statement - slow and
costly. Format memory records a cheap layout fingerprint of any statement the AI
successfully handled; on the next run, if the fingerprint matches, the pipeline
can go straight to AI extraction (skipping the wasted deterministic attempts) or
even to a cached parser hint.

It is deliberately decoupled from the detector: the detector still runs, and
format memory is consulted by the extraction pipeline as a *hint*.

Storage: config/known_formats.json
    {
      "<fingerprint_hash>": {
        "bank": "Wells Fargo",
        "first_seen": "2026-06-29T...",
        "last_seen": "2026-06-29T...",
        "seen_count": 3,
        "sample_path": "...",
        "source": "ai_extraction",
        "signature": { ... lightweight signals ... }
      },
      ...
    }
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FORMATS_PATH = os.path.join(_BASE_DIR, "config", "known_formats.json")


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------
def _signature(text: str) -> Dict[str, Any]:
    """Extract lightweight, stable layout signals from statement text.

    These are designed to be invariant to dates/amounts/merchants (which change
    every statement) but characteristic of the *format* (bank, column layout,
    date style). The HASHABLE part of the signature must exclude any per-statement
    content; the rest is stored for diagnostics only.
    """
    if not text:
        return {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Header tokens: ONLY the first 3 non-empty lines are format-stable (bank
    # name, statement title, account label). Transaction descriptions appear
    # later and change every statement, so they must NOT be hashed in.
    header_tokens = []
    for ln in lines[:3]:
        tok = re.sub(r"[^A-Z]", "", ln.upper())
        if len(tok) >= 3:
            header_tokens.append(tok[:24])
    header = "|".join(header_tokens)

    # Date format frequency (MM/DD/YYYY vs YYYY-MM-DD vs DD MMM).
    date_formats = {
        "mdy": len(re.findall(r"\b\d{1,2}/\d{1,2}/\d{4}\b", text)),
        "ymd": len(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)),
        "dmon": len(re.findall(r"\b\d{1,2}\s[A-Z][a-z]{2}\b", text)),
    }
    dominant_date = max(date_formats, key=date_formats.get) if any(date_formats.values()) else "none"

    # Column-ish signals: count of lines that contain both a date and a number
    # (proxy for "this is a transactions page").
    txn_like = sum(
        1
        for ln in lines
        if re.search(r"\d{1,2}[/\-]\d{1,2}", ln) and re.search(r"\d+\.\d{2}", ln)
    )

    return {
        # --- hashable (format identity) ---
        "header": header,
        "dominant_date_format": dominant_date,
        # --- diagnostic only (NOT hashed) ---
        "txn_like_lines": txn_like,
        "line_count": len(lines),
    }


def fingerprint(text: str) -> str:
    """Return a stable hash for a statement's layout signature.

    Only the format-identity fields (header + date style) are hashed; per-row
    counts are diagnostic-only and excluded so two statements with the same
    layout but different transaction counts hash identically.
    """
    sig = _signature(text)
    hashable = {
        "header": sig.get("header", ""),
        "dominant_date_format": sig.get("dominant_date_format", "none"),
    }
    blob = json.dumps(hashable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def _load() -> Dict[str, Any]:
    try:
        if os.path.exists(_FORMATS_PATH):
            with open(_FORMATS_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
    except Exception as exc:
        print(f"⚠️ Could not read known_formats.json: {exc}")
    return {}


def _save(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(_FORMATS_PATH), exist_ok=True)
        with open(_FORMATS_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"⚠️ Could not write known_formats.json: {exc}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def lookup(text: str) -> Optional[Dict[str, Any]]:
    """Return the recorded format entry for this statement's fingerprint, or None."""
    fp = fingerprint(text)
    return _load().get(fp)


def remember(
    text: str,
    bank: str,
    source: str = "ai_extraction",
    sample_path: str = "",
) -> None:
    """Record (or refresh) a format entry. Called after a successful extraction."""
    fp = fingerprint(text)
    if not fp:
        return
    data = _load()
    now = datetime.now().isoformat(timespec="seconds")
    existing = data.get(fp)
    entry = {
        "bank": bank,
        "first_seen": existing["first_seen"] if existing else now,
        "last_seen": now,
        "seen_count": (existing.get("seen_count", 0) + 1) if existing else 1,
        "sample_path": sample_path or (existing or {}).get("sample_path", ""),
        "source": source,
        "signature": _signature(text),
    }
    data[fp] = entry
    _save(data)


def should_skip_to_ai(text: str) -> Optional[Dict[str, Any]]:
    """Hint for the extraction pipeline.

    If this layout has been seen and was previously handled by AI extraction,
    return the recorded entry so the pipeline can skip the deterministic stages
    and go straight to AI. Returns None otherwise.
    """
    entry = lookup(text)
    if entry and entry.get("source") == "ai_extraction" and entry.get("seen_count", 0) >= 1:
        return entry
    return None
