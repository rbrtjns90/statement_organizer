"""
AI-Based Bank Detection
------------------------
Uses multimodal AI to detect bank from PDF statements.
Includes Vision OCR fallback for scanned documents on macOS.
"""

import os
import json
import base64
import io
from PIL import Image
import pdfplumber
import platform

try:
    from llama_cpp import Llama
    LLAMA_CPP_AVAILABLE = True
except ImportError:
    LLAMA_CPP_AVAILABLE = False
    Llama = None

# Import Vision OCR for scanned PDFs on macOS
VISION_OCR_AVAILABLE = False
if platform.system() == "Darwin":
    try:
        from .vision_ocr import extract_text_from_pdf as vision_extract_text
        VISION_OCR_AVAILABLE = True
    except ImportError:
        vision_extract_text = None


class AIBankDetector:
    """Detects bank using multimodal AI (image + text)."""
    
    @staticmethod
    def _detect_gpu():
        """Detect available GPU acceleration."""
        try:
            # Try to detect Metal (macOS)
            import platform
            if platform.system() == "Darwin":
                # Check for Apple Silicon
                if platform.machine() == "arm64":
                    return "metal", -1  # -1 means use all layers
            
            # Try to detect CUDA (NVIDIA)
            try:
                import torch
                if torch.cuda.is_available():
                    return "cuda", -1
            except ImportError:
                pass
            
            # Try to detect ROCm (AMD)
            try:
                import torch
                if hasattr(torch, 'hip') and torch.hip.is_available():
                    return "rocm", -1
            except (ImportError, AttributeError):
                pass
                
        except Exception as e:
            print(f"⚠️ GPU detection error: {e}")
        
        return None, 0  # CPU-only
    
    def __init__(self, model_path=None):
        """Initialize with local GGUF model."""
        self.model_path = model_path or os.getenv(
            "STATEMENT_ORGANIZER_AI_MODEL_PATH", 
            os.path.join("models", "gemma-4-e2b-it-Q8_0.gguf")
        )
        self.client = None
        self.backend = None
        
        if LLAMA_CPP_AVAILABLE and os.path.exists(self.model_path):
            # Detect GPU acceleration
            gpu_type, n_gpu_layers = self._detect_gpu()
            
            try:
                self.client = Llama(
                    model_path=self.model_path,
                    n_ctx=2048,  # Increased back to 2048 for transaction extraction
                    n_threads=max(1, (os.cpu_count() or 2) - 1),
                    verbose=False,
                    n_gpu_layers=n_gpu_layers,  # Auto-detect GPU layers
                )
                self.backend = "llama_cpp"
                
                if gpu_type:
                    print(f"✅ AI bank detector initialized with {self.model_path} ({gpu_type.upper()} acceleration)")
                else:
                    print(f"✅ AI bank detector initialized with {self.model_path} (CPU-only)")
            except Exception as e:
                print(f"⚠️ Could not initialize AI detector: {e}")
    
    def detect_bank(self, pdf_path):
        """Detect bank using multimodal AI."""
        if not self.client:
            return None
            
        try:
            # Extract first page as image
            with pdfplumber.open(pdf_path) as pdf:
                first_page = pdf.pages[0]
                # Convert to PIL Image with higher resolution
                pix = first_page.to_image(resolution=150)  # Increased from 72 to 150 DPI
                pil_image = pix.original
                
                # Resize image to reduce size (max width 1200px) - increased from 800px
                max_width = 1200
                if pil_image.width > max_width:
                    ratio = max_width / pil_image.width
                    new_size = (max_width, int(pil_image.height * ratio))
                    pil_image = pil_image.resize(new_size, Image.LANCZOS)
                
                # Convert image to base64
                buffered = io.BytesIO()
                pil_image.save(buffered, format="PNG", optimize=True)
                image_b64 = base64.b64encode(buffered.getvalue()).decode()
                
                # Extract text with pdfplumber only (Vision OCR disabled due to crashes)
                page_text = first_page.extract_text() or ""
                
                # Get text excerpt (first 12 lines)
                text_lines = page_text.split('\n')[:12]
                text_excerpt = '\n'.join(text_lines)

            # Build prompt for bank identification with confidence
            # Include both known banks (with parsers) and common banks (for detection)
            known_banks = [
                "Bank of America", "Chase", "Citibank", "Citi", "Capital One", "Navy Federal",
                "Wells Fargo", "US Bank", "PNC Bank", "TD Bank", "Truist",
                "Citizens Bank", "Fifth Third Bank", "KeyBank", "Regions Bank",
                "M&T Bank", "Ally Bank", "Discover Bank", "American Express"
            ]
            prompt = (
                f"Identify the bank from this statement. "
                f"Common banks: {', '.join(known_banks[:10])}. "
                f"Text: {text_excerpt}. "
                f"Respond with JSON: {{\"bank\": \"<exact name>\", \"confidence\": <0-100>}}"
            )

            # Prepare multimodal message
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                    ]
                }
            ]

            # Call the model
            response = self.client.create_chat_completion(
                messages=messages,
                max_tokens=30,  # Increased slightly for JSON response
                temperature=0
            )
            
            response_text = response["choices"][0]["message"]["content"].strip()
            
            # Try to parse JSON response
            try:
                import re
                # Extract JSON object
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                    bank_name = result.get("bank", "")
                    confidence = result.get("confidence", 0)
                else:
                    # Fallback: treat entire response as bank name
                    bank_name = response_text
                    confidence = 50
            except (json.JSONDecodeError, AttributeError):
                # Fallback: treat entire response as bank name
                bank_name = response_text
                confidence = 50
            
            # Validate response and normalize bank names
            # Map aliases to canonical names
            bank_aliases = {
                "Citi": "Citibank",
                "CITI": "Citibank"
            }
            
            # Normalize bank name if it's an alias
            if bank_name in bank_aliases:
                bank_name = bank_aliases[bank_name]
            
            if bank_name in known_banks:
                return {"bank": bank_name, "confidence": confidence}
            else:
                print(f"⚠️ AI returned unrecognized bank: {bank_name}")
                return {"bank": None, "confidence": 0}

        except Exception as e:
            print(f"❌ AI bank detection error: {e}")
            return None


# Global detector instance
_detector = None

def get_ai_detector():
    """Get or create the AI detector instance."""
    global _detector
    if _detector is None:
        _detector = AIBankDetector()
    return _detector

def detect_bank_with_ai(pdf_path, return_confidence=False):
    """Convenience function to detect bank using AI.
    
    Args:
        pdf_path: Path to PDF file
        return_confidence: If True, returns dict with bank and confidence.
                          If False, returns just bank name (backward compatible)
    
    Returns:
        If return_confidence=True: {"bank": str, "confidence": int}
        If return_confidence=False: str (bank name only)
    """
    detector = get_ai_detector()
    result = detector.detect_bank(pdf_path)
    
    if result is None:
        return None if return_confidence else None
    
    if return_confidence:
        return result
    else:
        # Backward compatible: return just bank name
        return result.get("bank") if isinstance(result, dict) else result


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
