"""
Logging Utilities
-----------------
Tiny append-then-rotate helper for the AI diagnostic logs.

The previous code appended to ai_errors.txt and ai_invalid_categories.txt with
no cap, which let ai_errors.txt grow to ~481KB (mostly a single recurring
error). This module caps each log at a maximum number of entries (keeping the
most recent) so they stay useful and bounded.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import List

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_MAX_BYTES = 512 * 1024  # 512 KB per log file


def _resolve(path: str) -> str:
    if os.path.isabs(path):
        return path
    # Resolve relative to project root so the log lands next to the other logs
    # regardless of the current working directory.
    return os.path.join(_BASE_DIR, path)


def append_capped(path: str, message: str, max_bytes: int = DEFAULT_MAX_BYTES) -> None:
    """Append a message to a log file, rotating it if it exceeds max_bytes.

    On rotation we keep the tail (most recent entries) up to max_bytes/2 and
    drop the older half, so the log never grows unbounded but recent context
    is preserved.
    """
    full = _resolve(path)
    try:
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        existing = ""
        if os.path.exists(full):
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                existing = fh.read()
        if len(existing.encode("utf-8")) > max_bytes:
            # Keep the most recent half (by bytes).
            keep = existing.encode("utf-8")[-(max_bytes // 2):]
            existing = keep.decode("utf-8", errors="replace").split("\n", 1)[-1]
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(existing)
            if not existing.endswith("\n") and existing:
                fh.write("\n")
            fh.write(message)
            if not message.endswith("\n"):
                fh.write("\n")
    except Exception as exc:  # logging must never break the caller
        print(f"⚠️ Could not write log {path}: {exc}")


def log_ai_error(error_msg: str, description: str = "", amount=None) -> None:
    """Append an AI error entry (rotated)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"[{ts}] AI ERROR\n"
        f"  Error: {error_msg}\n"
        f"  Transaction: '{description}'\n"
        f"  Amount: ${amount}\n"
        + "-" * 80 + "\n"
    )
    append_capped("ai_errors.txt", msg)


def log_invalid_ai_category(
    invalid_category: str, description: str = "", amount=None, categories=None
) -> None:
    """Append an invalid-AI-category entry (rotated)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cats = ", ".join(list(categories.keys())[:30]) if isinstance(categories, dict) else ""
    msg = (
        f"[{ts}] INVALID CATEGORY\n"
        f"  AI Returned: '{invalid_category}'\n"
        f"  Transaction: '{description}'\n"
        f"  Amount: ${amount}\n"
        f"  Valid Categories: {cats}\n"
        + "-" * 80 + "\n"
    )
    append_capped("ai_invalid_categories.txt", msg)
