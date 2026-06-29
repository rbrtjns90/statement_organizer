"""
AI-Based Bank Detection
------------------------
Detects the issuing bank from a PDF statement using the unified AIClient
(local model first, OpenAI fallback). This module no longer loads its own
Llama instance directly — all AI calls route through ai_client.py so that
backend selection, fallback, caching, and cost tracking are consistent.
"""

import base64
import io
import json
import os
import re

from PIL import Image
import pdfplumber

# Known banks (for prompt context + response validation)
KNOWN_BANKS = [
    "Bank of America", "Chase", "Citibank", "Citi", "Capital One", "Navy Federal",
    "Wells Fargo", "US Bank", "PNC Bank", "TD Bank", "Truist",
    "Citizens Bank", "Fifth Third Bank", "KeyBank", "Regions Bank",
    "M&T Bank", "Ally Bank", "Discover Bank", "American Express",
]

# Alias normalization
_BANK_ALIASES = {
    "Citi": "Citibank",
    "CITI": "Citibank",
}


def detect_bank_with_ai(pdf_path, return_confidence=False):
    """Detect the issuing bank from a PDF using the unified AIClient.

    Args:
        pdf_path: Path to the PDF file.
        return_confidence: If True, returns {"bank": str, "confidence": int}.
                          If False, returns just the bank name string.

    Returns:
        Bank name (str), or {"bank": ..., "confidence": ...} dict, or None.
    """
    from .ai_client import get_ai_client, extract_json

    client = get_ai_client()
    if not client.available:
        return None

    try:
        with pdfplumber.open(pdf_path) as pdf:
            first_page = pdf.pages[0]
            image_b64, text_excerpt = _render_first_page(first_page)
    except Exception as exc:
        print(f"AI bank detection render error: {exc}")
        return None

    prompt = (
        f"Identify the bank from this statement. "
        f"Common banks: {', '.join(KNOWN_BANKS[:10])}. "
        f"Text: {text_excerpt}. "
        f'Respond with JSON: {{"bank": "<exact name>", "confidence": <0-100>}}'
    )

    try:
        resp = client.chat_vision(image_b64, prompt, max_tokens=30, temperature=0)
        if not resp.success:
            return None
        response_text = resp.text.strip()
    except Exception as exc:
        print(f"AI bank detection error: {exc}")
        return None

    # Parse the JSON response
    payload = extract_json(response_text)
    if isinstance(payload, dict) and "bank" in payload:
        bank_name = payload["bank"]
        confidence = int(payload.get("confidence", 50))
    else:
        # Fallback: treat the whole response as a bank name
        bank_name = response_text.strip()
        confidence = 50

    # Normalize aliases
    bank_name = _BANK_ALIASES.get(bank_name, bank_name)

    if bank_name in KNOWN_BANKS:
        result = {"bank": bank_name, "confidence": confidence}
    else:
        print(f"AI returned unrecognized bank: {bank_name}")
        result = {"bank": None, "confidence": 0}

    if return_confidence:
        return result
    return result.get("bank") if isinstance(result, dict) else result


def _render_first_page(page, max_width=1200, resolution=150):
    """Render a page to base64 PNG + extract a short text excerpt.

    Returns (image_b64, text_excerpt).
    """
    pix = page.to_image(resolution=resolution)
    pil_image = pix.original
    if pil_image.width > max_width:
        ratio = max_width / pil_image.width
        pil_image = pil_image.resize((max_width, int(pil_image.height * ratio)), Image.LANCZOS)
    buffered = io.BytesIO()
    pil_image.save(buffered, format="PNG", optimize=True)
    image_b64 = base64.b64encode(buffered.getvalue()).decode()
    page_text = page.extract_text() or ""
    text_excerpt = "\n".join(page_text.split("\n")[:12])
    return image_b64, text_excerpt


def _render_page_image(page, max_width=1200, resolution=150):
    """Render a pdfplumber page to a base64 PNG string for vision models.

    Reused by bank detection and transaction extraction. Capped at max_width so
    large statements don't blow up token cost.
    """
    pix = page.to_image(resolution=resolution)
    pil_image = pix.original
    if pil_image.width > max_width:
        ratio = max_width / pil_image.width
        new_size = (max_width, int(pil_image.height * ratio))
        pil_image = pil_image.resize(new_size, Image.LANCZOS)
    buffered = io.BytesIO()
    pil_image.save(buffered, format="PNG", optimize=True)
    return base64.b64encode(buffered.getvalue()).decode()


def _build_extraction_prompt(page_text):
    """Tightened transaction-extraction prompt.

    Compared to the original this:
      - asks for transaction_type (debit/credit) so sign conventions are explicit,
      - has explicit anti-hallucination rules (no inventing merchants/totals),
      - demands strict JSON with no commentary,
      - explains how to handle amounts (negative=debit) consistently.
    """
    return (
        "You are extracting transactions from a bank statement page. "
        "Look at the image and the text below.\n\n"
        "Extract EVERY individual transaction line. For each transaction return:\n"
        '  - "date": the transaction date as MM/DD/YYYY (use the page/statement '
        "year if the line only shows month/day; if truly unknown, use 01/01/2024)\n"
        '  - "description": the merchant/payee name, cleaned of reference numbers '
        "and card prefixes\n"
        '  - "amount": the dollar amount as a number. NEGATIVE for charges/'
        "debits/purchases, POSITIVE for deposits/payments/refunds\n"
        '  - "transaction_type": "debit" or "credit"\n\n'
        "RULES:\n"
        "- Include ONLY real transactions (purchases, payments, deposits, "
        "withdrawals, fees, transfers).\n"
        "- EXCLUDE summary lines, running balances, totals, column headers, "
        "page footers, and account-info blocks.\n"
        "- Do NOT invent transactions. If a row is unreadable, skip it.\n"
        "- Do NOT include the ending balance or any total row.\n"
        "- Return ONLY a JSON array, no prose, no code fences.\n\n"
        'Schema: [{"date":"MM/DD/YYYY","description":"string","amount":-123.45,'
        '"transaction_type":"debit"}]\n\n'
        f"Page text for reference:\n{page_text[:1500]}"
    )


def extract_transactions_with_ai(pdf_path):
    """Extract transactions from a PDF using AI (the "if you have to" path).

    Uses the unified AIClient so it transparently runs on a local model first
    and falls back to OpenAI. Vision is preferred (image + text); if the active
    backend isn't vision-capable, it falls back to text-only extraction.

    All results pass through ValidationPipeline (dedup + quality scoring) before
    being returned, matching the previous behavior.

    Args:
        pdf_path: Path to PDF file.

    Returns:
        List of validated transaction dicts (date, description, amount, category).
    """
    # Unified client (local -> OpenAI fallback). Bail out only if neither works.
    from .ai_client import get_ai_client
    from .transaction_validation import ValidationPipeline

    client = get_ai_client()
    if not client.available:
        print("⚠️ AI extraction requested but no backend is available")
        return []

    settings = client.settings
    max_tokens = int(settings.get("max_tokens_extraction", 2000))

    try:
        import pdfplumber

        raw_transactions = []

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                if not page_text.strip() and not client._openai.available:
                    # No text and no vision-capable backend -> nothing to do here.
                    continue

                prompt = _build_extraction_prompt(page_text)
                page_txns = None

                # Prefer vision (image + text) when a backend supports it.
                if client.active_backend == "openai" or client._local.supports_vision:
                    try:
                        image_b64 = _render_page_image(page)
                        parsed = client.chat_vision_json(
                            image_b64,
                            prompt,
                            max_tokens=max_tokens,
                            temperature=0,
                        )
                        if isinstance(parsed, list):
                            page_txns = parsed
                    except Exception as exc:
                        print(f"⚠️ Vision extraction failed on page {page_num + 1}: {exc}")

                # Fallback: text-only extraction.
                if not page_txns:
                    parsed = client.chat_text_json(prompt, max_tokens=max_tokens, temperature=0)
                    if isinstance(parsed, list):
                        page_txns = parsed
                    elif isinstance(parsed, dict):
                        page_txns = [parsed]

                if not page_txns:
                    print(f"⚠️ No transactions parsed from AI response on page {page_num + 1}")
                    continue

                for txn in page_txns:
                    if isinstance(txn, dict):
                        txn["page"] = page_num + 1
                        txn["source"] = "ai_extraction"
                        raw_transactions.append(txn)

        # Validate all extracted transactions (relaxed threshold for AI output).
        if raw_transactions:
            print(f"🔍 Validating {len(raw_transactions)} AI-extracted transactions...")
            validator = ValidationPipeline(min_quality_score=20.0)
            valid_transactions = validator.validate_extraction_result(
                raw_transactions, source="ai_extraction", statement_date=None
            )
            print(
                f"✅ AI extracted {len(valid_transactions)} valid transactions "
                f"({len(raw_transactions) - len(valid_transactions)} rejected) "
                f"via {client.active_backend}"
            )
            return [
                {
                    "date": txn.date,
                    "description": txn.description,
                    "amount": txn.amount,
                    "category": txn.category,
                    "source": txn.source,
                    "page": txn.page,
                }
                for txn in valid_transactions
            ]

        return []

    except Exception as e:
        print(f"❌ AI transaction extraction error: {e}")
        import traceback

        traceback.print_exc()
        return []
