"""
AI-Based Bank Statement Parser
-------------------------------
Uses multimodal AI to extract transactions from unknown banks.
Integrates TextExtractor and ImageNormalizer for robust text extraction.
"""

from typing import List, Dict, Any, Optional
from . import BankStatementParser
from .ai_detector import extract_transactions_with_ai
from .text_extraction import TextExtractor
from .image_normalization import ImageNormalizer, normalize_for_ocr


class AIBankParser(BankStatementParser):
    """Parser that uses AI to extract transactions from any bank statement."""
    
    def __init__(self):
        super().__init__()
        self.bank_name = "AI Parser"
        self.supported_formats = ["PDF", "PNG", "JPG", "JPEG", "TIFF"]
        self._pdf_path = None
        self._text_extractor = TextExtractor()
    
    def can_parse(self, text: str) -> bool:
        """AI parser can attempt to parse any statement.
        
        This should only be used as a last resort fallback.
        It will be invoked explicitly for unknown banks.
        
        Args:
            text: PDF text content
            
        Returns:
            False - AI parser is never auto-selected, only manually invoked
        """
        return False
    
    def get_account_info(self, text: str) -> Dict[str, str]:
        """Extract account information from PDF text.
        
        Args:
            text: PDF text content
            
        Returns:
            Empty dict - AI parser focuses on transactions only
        """
        return {}
    
    def set_pdf_path(self, pdf_path: str) -> None:
        """Set the PDF path for AI extraction.
        
        Args:
            pdf_path: Path to the PDF file
        """
        self._pdf_path = pdf_path
    
    def extract_transactions(self, text: str) -> List[Dict[str, Any]]:
        """Extract transactions using AI multimodal detection with validation.
        
        Uses TextExtractor for unified text extraction and ImageNormalizer
        for preprocessing images before AI analysis.
        
        Args:
            text: PDF text (not used, AI uses images + text directly from PDF)
        
        Returns:
            List of validated transaction dicts with date, description, amount, category
        """
        if not self._pdf_path:
            print("⚠️ AI parser requires PDF path to be set")
            return []
        
        print(f"🤖 Using AI to extract transactions from {self._pdf_path}")
        
        # Use unified text extraction for better accuracy
        try:
            extraction_result = self._text_extractor.extract(self._pdf_path, prefer_ocr=True)
            print(f"   Extracted {len(extraction_result.text)} chars using {extraction_result.backend}")
            
            if extraction_result.is_scanned:
                print("   📄 Document appears to be scanned/image-based")
        except Exception as e:
            print(f"⚠️ Text extraction warning: {e}")
        
        # Extract transactions with AI
        transactions = extract_transactions_with_ai(self._pdf_path)
        
        if transactions:
            print(f"✅ AI parser extracted {len(transactions)} valid transactions")
        else:
            print("⚠️ AI parser found no transactions")
        
        return transactions
