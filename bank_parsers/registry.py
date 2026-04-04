"""
Bank Parser Registry Setup
---------------------------
Automatically registers all available bank parsers.
"""

from . import parser_registry
from .bank_of_america import BankOfAmericaParser
from .chase import ChaseParser
from .citibank import CitibankParser
from .capital_one import CapitalOneParser
from .navy_federal import NavyFederalParser
from .generic_regex import GenericRegexParser
from .ml_parser import MLBankParser
from .ai_detector import detect_bank_with_ai


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


def detect_bank(pdf_text: str, pdf_path: str = None):
    """Detect which bank parser can handle the given PDF text.
    
    Handles both known and unknown banks intelligently:
    - Known banks with parsers: Use regex or AI
    - Unknown banks: Detect via AI, log for future parser development
    
    Args:
        pdf_text: Extracted text from the PDF
        pdf_path: Path to the PDF file (for AI detection)
    
    Returns:
        Bank name as string or "Unknown"
    """
    import os
    import json
    from datetime import datetime
    
    # Banks to exclude from AI detection (use regex only)
    AI_EXCLUSION_LIST = ["Navy Federal"]
    
    # Minimum confidence threshold for AI detection
    MIN_CONFIDENCE = 70
    
    # Try regex detection first
    parser = parser_registry.get_parser(pdf_text)
    detected_bank = parser.bank_name if parser else None
    
    # If regex succeeded and it's an excluded bank, return immediately
    if detected_bank and detected_bank in AI_EXCLUSION_LIST:
        print(f"📋 Regex detected excluded bank: {detected_bank} (skipping AI)")
        return detected_bank
    
    # If regex succeeded for any bank, return it
    if detected_bank:
        return detected_bank
    
    # If regex failed and we have the file path, try AI detection
    if pdf_path:
        from bank_parsers.ai_detector import detect_bank_with_ai
        result = detect_bank_with_ai(pdf_path, return_confidence=True)
        
        if result:
            ai_bank = result.get("bank")
            confidence = result.get("confidence", 0)
            
            if ai_bank and confidence >= MIN_CONFIDENCE:
                # Check if we have a parser for this bank
                known_banks = [p.bank_name for p in parser_registry._parsers]
                
                if ai_bank in known_banks:
                    # Known bank detected by AI
                    print(f"🤖 AI detected known bank: {ai_bank} (confidence: {confidence}%)")
                    return ai_bank
                else:
                    # Unknown bank detected - log it for future development
                    print(f"🆕 AI detected UNKNOWN bank: {ai_bank} (confidence: {confidence}%)")
                    _log_unknown_bank(ai_bank, pdf_path, confidence)
                    return ai_bank
            elif confidence < MIN_CONFIDENCE:
                print(f"⚠️ AI detection low confidence ({confidence}%), using generic parser")
        else:
            print("🤖 AI bank detection failed, using generic parser")
    
    return "Unknown"


def _log_unknown_bank(bank_name: str, pdf_path: str, confidence: int):
    """Log unknown banks for future parser development."""
    import os
    import json
    from datetime import datetime
    
    log_file = "config/unknown_banks.json"
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # Load existing log
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r') as f:
                log_data = json.load(f)
        except:
            log_data = {}
    else:
        log_data = {}
    
    # Add entry
    if bank_name not in log_data:
        log_data[bank_name] = {
            "first_seen": datetime.now().isoformat(),
            "count": 0,
            "samples": []
        }
    
    log_data[bank_name]["count"] += 1
    log_data[bank_name]["last_seen"] = datetime.now().isoformat()
    
    # Keep up to 5 sample paths
    if len(log_data[bank_name]["samples"]) < 5:
        log_data[bank_name]["samples"].append({
            "path": pdf_path,
            "confidence": confidence,
            "date": datetime.now().isoformat()
        })
    
    # Save log
    with open(log_file, 'w') as f:
        json.dump(log_data, f, indent=2)
    
    print(f"   📝 Logged to {log_file} (total occurrences: {log_data[bank_name]['count']})")


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
