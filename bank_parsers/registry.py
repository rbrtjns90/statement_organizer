"""
Bank Parser Registry Setup
---------------------------
Automatically registers all available bank parsers.
"""

from . import parser_registry
from .bank_of_america import BankOfAmericaParser
from .chase import ChaseParser
from .citibank import CitibankParser


def initialize_parsers():
    """Initialize and register all available bank parsers."""
    # Order matters! More specific parsers should come first
    parsers = [
        CitibankParser(),      # Check Citi first - more specific patterns
        BankOfAmericaParser(), # Then BofA
        ChaseParser(),         # Chase last - has broader patterns
    ]
    
    for parser in parsers:
        parser_registry.register(parser)
    
    return parser_registry


def get_supported_banks():
    """Get list of all supported banks."""
    return parser_registry.list_supported_banks()


def detect_bank(pdf_text: str):
    """Detect which bank parser can handle the given PDF text."""
    parser = parser_registry.get_parser(pdf_text)
    return parser.bank_name if parser else "Unknown"


# Auto-initialize when module is imported
initialize_parsers()
