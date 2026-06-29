"""
Bank Parser Registry Setup
---------------------------
Automatically registers all available bank parsers.
Uses multi-stage bank detection for improved accuracy.
"""

from . import parser_registry
from .bank_of_america import BankOfAmericaParser
from .chase import ChaseParser
from .citibank import CitibankParser
from .capital_one import CapitalOneParser
from .navy_federal import NavyFederalParser
from .generic_regex import GenericRegexParser
from .ml_parser import MLBankParser
from .bank_detection import MultiStageBankDetector


def initialize_parsers():
    """Initialize and register all available bank parsers."""
    # Order matters! More specific parsers should come first
    # Generic parser should be LAST as it's a fallback
    parsers = [
        NavyFederalParser(),   # Check Navy Federal first - very specific format
        CapitalOneParser(),    # Check Capital One second - very specific format
        CitibankParser(),      # Check Citi third - more specific patterns
        BankOfAmericaParser(), # Then BofA
        ChaseParser(),         # Chase has broader patterns
        MLBankParser(),        # ML parser - high accuracy fallback
        GenericRegexParser(),  # Generic fallback parser - LAST
    ]
    
    for parser in parsers:
        parser_registry.register(parser)
    
    return parser_registry


def get_supported_banks():
    """Get list of all supported banks."""
    return parser_registry.list_supported_banks()


# Global detector instance (lazy initialization)
_detector = None

def get_detector():
    """Get or create the multi-stage bank detector."""
    global _detector
    if _detector is None:
        _detector = MultiStageBankDetector()
    return _detector


def detect_bank(pdf_text: str, pdf_path: str = None):
    """Detect which bank parser can handle the given PDF.
    
    Uses multi-stage detection with cascading fallback:
    1. Regex patterns (fast, specific)
    2. Layout fingerprinting (analyzes PDF structure)
    3. AI detection (image + text, most flexible)
    4. Unknown bank fallback
    
    Args:
        pdf_text: Extracted text from the PDF
        pdf_path: Path to the PDF file (for multi-stage detection)
    
    Returns:
        Bank name as string or "Unknown"
    """
    if not pdf_path:
        # Fallback to simple regex detection if no PDF path
        parser = parser_registry.get_parser(pdf_text)
        return parser.bank_name if parser else "Unknown"
    
    # Use multi-stage detector with full pipeline
    detector = get_detector()
    result = detector.detect(pdf_path, pdf_text)
    
    return result.bank_name


def _log_unknown_bank(bank_name: str, pdf_path: str, confidence: int):
    """Log unknown banks for future parser development.
    
    Note: This is now handled automatically by MultiStageBankDetector.
    Kept for backward compatibility.
    """
    pass  # Logging is handled by the detector


def get_all_parsers():
    """Get all registered parsers as a dictionary."""
    return {parser.bank_name: parser for parser in parser_registry._parsers}


def get_parser_for_bank(bank_name: str):
    """Get parser for a specific bank name."""
    for parser in parser_registry._parsers:
        if parser.bank_name == bank_name:
            return parser
    return None


# Auto-initialize when module is imported
initialize_parsers()
