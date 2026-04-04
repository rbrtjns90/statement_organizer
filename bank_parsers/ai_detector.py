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
                
                # Try to extract text - first with pdfplumber, then Vision OCR if needed
                page_text = first_page.extract_text() or ""
                
                # If very little text (likely scanned PDF), use Vision OCR
                if len(page_text.strip()) < 50 and VISION_OCR_AVAILABLE:
                    print("🤖 PDF appears scanned, using Vision OCR for text extraction...")
                    try:
                        page_text = vision_extract_text(pdf_path, use_vision_if_scanned=True)
                        # Just get first page text
                        if "--- Page" in page_text:
                            page_text = page_text.split("--- Page")[1] if len(page_text.split("--- Page")) > 1 else page_text
                            page_text = page_text.split("---")[0] if "---" in page_text else page_text
                    except Exception as e:
                        print(f"⚠️ Vision OCR failed: {e}")
                
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


def extract_transactions_with_ai(pdf_path):
    """Extract transactions from PDF using AI line-by-line detection.
    
    This is used for unknown banks where we don't have regex parsers.
    
    Args:
        pdf_path: Path to PDF file
    
    Returns:
        List of transaction dicts with date, description, amount
    """
    detector = get_ai_detector()
    if not detector.client:
        return []
    
    try:
        import pdfplumber
        from datetime import datetime
        
        transactions = []
        
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                # Get page text
                page_text = page.extract_text() or ""
                lines = page_text.split('\n')
                
                # Render page as image for visual context
                pix = page.to_image(resolution=150)
                pil_image = pix.original
                
                # Resize if needed
                max_width = 1200
                if pil_image.width > max_width:
                    ratio = max_width / pil_image.width
                    new_size = (max_width, int(pil_image.height * ratio))
                    pil_image = pil_image.resize(new_size, Image.LANCZOS)
                
                # Convert to base64
                buffered = io.BytesIO()
                pil_image.save(buffered, format="PNG", optimize=True)
                image_b64 = base64.b64encode(buffered.getvalue()).decode()
                
                # Ask AI to extract transactions from this page
                prompt = (
                    f"Extract ALL individual transactions from this bank statement page.\n\n"
                    f"FOCUS ON:\n"
                    f"1. Description: merchant/payee name (most important for categorization)\n"
                    f"2. Amount: exact dollar amount (critical for totals)\n"
                    f"3. Date: approximate date is OK, use 01/01/2024 if unknown\n\n"
                    f"RULES:\n"
                    f"- Extract ONLY actual transactions (purchases, payments, deposits, withdrawals)\n"
                    f"- SKIP summary lines, balances, totals, headers, and fee descriptions\n"
                    f"- Amount must be a valid number - use negative for debits/charges\n"
                    f"- Description should be clear enough to identify the merchant\n\n"
                    f'Respond with JSON array: [{{"date": "MM/DD/YYYY", "description": "merchant name", "amount": -123.45}}]\n\n'
                    f"Page text:\n{page_text[:1000]}"  # First 1000 chars for context
                )
                
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
                        ]
                    }
                ]
                
                # Call AI
                response = detector.client.create_chat_completion(
                    messages=messages,
                    max_tokens=500,  # More tokens for multiple transactions
                    temperature=0
                )
                
                response_text = response["choices"][0]["message"]["content"].strip()
                
                # Parse JSON response
                import re
                json_match = re.search(r'\[.*\]', response_text, re.DOTALL)
                if json_match:
                    try:
                        page_transactions = json.loads(json_match.group(0))
                        
                        # Validate and normalize each transaction
                        for txn in page_transactions:
                            if not isinstance(txn, dict):
                                continue
                                
                            # Check required fields
                            if 'date' not in txn or 'description' not in txn or 'amount' not in txn:
                                print(f"⚠️ Skipping transaction missing required fields: {txn}")
                                continue
                            
                            try:
                                # Parse amount first (most critical)
                                amount_val = txn['amount']
                                if amount_val is None or str(amount_val).strip().lower() in ['none', 'n/a', '']:
                                    print(f"⚠️ Skipping transaction with invalid amount: {amount_val}")
                                    continue
                                
                                amount_str = str(amount_val).replace('$', '').replace(',', '').strip()
                                amount = float(amount_str)
                                
                                # Get description (critical for categorization)
                                description = str(txn['description']).strip()
                                if not description or description.lower() in ['none', 'n/a']:
                                    print(f"⚠️ Skipping transaction with empty description")
                                    continue
                                
                                # Parse date - use fallback if invalid (less critical)
                                from dateutil import parser as date_parser
                                from datetime import date as date_class
                                
                                date_str = str(txn['date']).strip()
                                try:
                                    # Skip obvious placeholders but try to parse anything else
                                    if 'X' in date_str.upper():
                                        # Use fallback date
                                        date_obj = date_class(2024, 1, 1)
                                    else:
                                        date_obj = date_parser.parse(date_str).date()
                                except:
                                    # If date parsing fails, use fallback date
                                    date_obj = date_class(2024, 1, 1)
                                
                                transactions.append({
                                    'date': date_obj,
                                    'description': description,
                                    'amount': amount,
                                    'category': None
                                })
                            except (ValueError, AttributeError, TypeError) as e:
                                print(f"⚠️ Skipping invalid transaction - {type(e).__name__}: {str(e)[:50]}")
                                continue
                    except json.JSONDecodeError:
                        print(f"⚠️ Could not parse AI response as JSON on page {page_num + 1}")
        
        print(f"✅ AI extracted {len(transactions)} transactions")
        return transactions
        
    except Exception as e:
        print(f"❌ AI transaction extraction error: {e}")
        return []
