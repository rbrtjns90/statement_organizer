"""
Bank Statement Parsers
----------------------
Modular parsers for different bank statement formats.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Any, Optional
import re


class BankStatementParser(ABC):
    """Abstract base class for bank statement parsers."""
    
    def __init__(self):
        self.bank_name = ""
        self.supported_formats = []
    
    @abstractmethod
    def can_parse(self, text: str) -> bool:
        """Check if this parser can handle the given PDF text."""
        pass
    
    @abstractmethod
    def extract_transactions(self, text: str) -> List[Dict[str, Any]]:
        """Extract transactions from PDF text."""
        pass
    
    @abstractmethod
    def get_account_info(self, text: str) -> Dict[str, str]:
        """Extract account information from PDF text."""
        pass
    
    def parse_amount(self, amount_str: str) -> Optional[float]:
        """Parse amount string to float."""
        try:
            # Remove currency symbols, commas, and whitespace
            cleaned = re.sub(r'[$,\s]', '', amount_str.strip())
            
            # Handle negative amounts in parentheses
            if cleaned.startswith('(') and cleaned.endswith(')'):
                cleaned = '-' + cleaned[1:-1]
            
            return float(cleaned)
        except (ValueError, AttributeError):
            return None
    
    def parse_date(self, date_str: str, year_hint: Optional[int] = None) -> Optional[datetime]:
        """Parse date string to datetime object."""
        try:
            # Try common date formats first
            for fmt in ['%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%m-%d-%Y', '%m/%d', '%d/%m/%Y']:
                try:
                    parsed_date = datetime.strptime(date_str.strip(), fmt)
                    
                    # If year is missing and we have a hint, use it
                    if year_hint and parsed_date.year == 1900:
                        parsed_date = parsed_date.replace(year=year_hint)
                    
                    return parsed_date
                except ValueError:
                    continue
            
            return None
        except (ValueError, TypeError):
            return None


class BankParserRegistry:
    """Registry for managing bank statement parsers."""
    
    def __init__(self):
        self._parsers = []
    
    def register(self, parser: BankStatementParser):
        """Register a new parser."""
        self._parsers.append(parser)
    
    def get_parser(self, text: str) -> Optional[BankStatementParser]:
        """Get the appropriate parser for the given PDF text."""
        for parser in self._parsers:
            if parser.can_parse(text):
                return parser
        return None
    
    def list_supported_banks(self) -> List[str]:
        """Get list of supported bank names."""
        return [parser.bank_name for parser in self._parsers]


# Global registry instance
parser_registry = BankParserRegistry()
