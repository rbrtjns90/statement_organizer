"""
Chase Bank Statement Parser
---------------------------
Parser for Chase Bank PDF statements.
"""

import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from . import BankStatementParser


class ChaseParser(BankStatementParser):
    """Parser for Chase Bank statements."""
    
    def __init__(self):
        super().__init__()
        self.bank_name = "Chase"
        self.supported_formats = ["PDF"]
    
    def can_parse(self, text: str) -> bool:
        """Check if this is a Chase statement with specific patterns."""
        # Primary Chase identifiers (most specific)
        primary_indicators = [
            "JPMorgan Chase", "JPMORGAN CHASE",
            "J.P. Morgan", "JP MORGAN",
            "chase.com", "CHASE.COM"
        ]
        
        # Secondary Chase identifiers (need to exclude Citi)
        secondary_indicators = [
            "Chase", "CHASE",
            "TRANSACTIONS THIS CYCLE",  # Common Chase statement phrase
            "CARD ENDING IN",           # Chase card identifier
            "ROBERT JONES",             # User's name (if this appears with transaction format)
        ]
        
        text_upper = text.upper()
        
        # First check for primary indicators (definitive Chase)
        for indicator in primary_indicators:
            if indicator.upper() in text_upper:
                return True
        
        # For secondary indicators, make sure it's not a Citi statement
        citi_exclusions = [
            "CITI", "CITIBANK", "CITICORP", "CITIGROUP",
            "CITI.COM", "CITIBANK.COM"
        ]
        
        # If we find Citi patterns, this is not a Chase statement
        for exclusion in citi_exclusions:
            if exclusion in text_upper:
                return False
        
        # Now check secondary Chase indicators
        for indicator in secondary_indicators:
            if indicator.upper() in text_upper:
                return True
        
        return False
    
    def extract_transactions(self, text: str) -> List[Dict[str, Any]]:
        """Extract transactions from Chase statement text."""
        transactions = []
        lines = text.split('\n')
        
        # Chase transaction patterns
        patterns = [
            # Standard format: MM/DD Description Amount
            r'(\d{1,2}/\d{1,2})\s+(.+?)\s+([-]?\$?[\d,]+\.\d{2})\s*$',
            # With year: MM/DD/YY Description Amount
            r'(\d{1,2}/\d{1,2}/\d{2})\s+(.+?)\s+([-]?\$?[\d,]+\.\d{2})\s*$',
            # No date format: Description Amount (for continuation lines or missing dates)
            r'^([A-Z][A-Z0-9\s\-#&\*\.\(\)]+?)\s+([-]?\$?[\d,]+\.\d{2})\s*$',
            # Check format: MM/DD Check #### Description Amount
            r'(\d{1,2}/\d{1,2})\s+Check\s+(\d+)\s+(.+?)\s+([-]?\$?[\d,]+\.\d{2})\s*$',
            # ACH/Transfer format: MM/DD ACH/TRANSFER Description Amount
            r'(\d{1,2}/\d{1,2})\s+(ACH|TRANSFER|DEPOSIT)\s+(.+?)\s+([-]?\$?[\d,]+\.\d{2})\s*$'
        ]
        
        # Extract statement year for date parsing
        year_hint = self._extract_statement_year(text)
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            for pattern in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    transaction = self._parse_transaction_match(match, pattern, year_hint)
                    if transaction:
                        transactions.append(transaction)
                    break
        
        return transactions
    
    def _extract_statement_year(self, text: str) -> Optional[int]:
        """Extract the statement year from the PDF text."""
        # Look for statement period or date patterns
        year_patterns = [
            r'Statement\s+Period[:\s]+\d{1,2}/\d{1,2}/(\d{4})',
            r'(\d{4})\s+Statement',
            r'Account\s+Summary\s+for\s+\w+\s+(\d{4})'
        ]
        
        for pattern in year_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except (ValueError, IndexError):
                    continue
        
        # Default to current year if not found
        return datetime.now().year
    
    def _parse_transaction_match(self, match, pattern, year_hint: Optional[int]) -> Optional[Dict[str, Any]]:
        """Parse a regex match into a transaction dictionary."""
        try:
            groups = match.groups()
            
            if len(groups) == 2:  # No date format: Description, Amount
                description, amount_str = groups
                # Use a default date (first of statement month) for transactions without dates
                date_obj = datetime(year_hint or datetime.now().year, 1, 1)
            elif len(groups) == 3:  # Date, Description, Amount
                date_str, description, amount_str = groups
                # Parse date (Chase often omits year)
                if '/' in date_str and len(date_str.split('/')) == 2:
                    # Add year if missing
                    date_str = f"{date_str}/{year_hint or datetime.now().year}"
                
                date_obj = self.parse_date(date_str, year_hint)
                if not date_obj:
                    return None
            elif len(groups) == 4:
                if "Check" in pattern:  # Date, Check, Number, Amount
                    date_str, check_word, check_num, amount_str = groups
                    description = f"Check #{check_num}"
                else:  # Date, Type, Description, Amount
                    date_str, trans_type, description, amount_str = groups
                    description = f"{trans_type} {description}".strip()
                
                # Parse date (Chase often omits year)
                if '/' in date_str and len(date_str.split('/')) == 2:
                    # Add year if missing
                    date_str = f"{date_str}/{year_hint or datetime.now().year}"
                
                date_obj = self.parse_date(date_str, year_hint)
                if not date_obj:
                    return None
            else:
                return None
            
            # Parse amount
            amount = self.parse_amount(amount_str)
            if amount is None:
                return None
            
            # For Chase credit cards, positive amounts are expenses/charges
            # Negative amounts are payments/credits
            if amount < 0:
                # This is a payment or credit - skip for expense tracking
                return None
            
            # amount is already positive for expenses
            
            # Clean up description
            description = self._clean_description(description)
            
            return {
                'date': date_obj,
                'description': description,
                'amount': amount,
                'category': None,
                'bank': self.bank_name
            }
            
        except Exception as e:
            return None
    
    def _clean_description(self, description: str) -> str:
        """Clean up transaction description."""
        # Remove extra whitespace
        description = ' '.join(description.split())
        
        # Remove common Chase prefixes/suffixes
        prefixes_to_remove = [
            'PURCHASE AUTHORIZED ON ',
            'AUTOMATIC PAYMENT - ',
            'ONLINE PAYMENT - ',
            'RECURRING PAYMENT - ',
            'CHECKCARD ',
            'DEBIT CARD ',
        ]
        
        for prefix in prefixes_to_remove:
            if description.upper().startswith(prefix):
                description = description[len(prefix):].strip()
        
        # Remove trailing reference numbers and dates
        description = re.sub(r'\s+\d{2}/\d{2}\s*$', '', description)  # Remove trailing dates
        description = re.sub(r'\s+#\w+\s*$', '', description)  # Remove reference numbers
        
        return description.strip()
    
    def get_account_info(self, text: str) -> Dict[str, str]:
        """Extract account information from Chase statement."""
        info = {}
        
        # Account number pattern
        account_match = re.search(r'Account\s+(?:Number\s+)?[:\-\s]*(\d{4})', text, re.IGNORECASE)
        if account_match:
            info['account_number'] = f"****{account_match.group(1)}"
        
        # Statement period
        period_match = re.search(r'Statement\s+Period[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})\s+(?:to|through|-)\s+(\d{1,2}/\d{1,2}/\d{2,4})', text, re.IGNORECASE)
        if period_match:
            info['period_start'] = period_match.group(1)
            info['period_end'] = period_match.group(2)
        
        # Account type
        if 'TOTAL CHECKING' in text.upper() or 'CHECKING ACCOUNT' in text.upper():
            info['account_type'] = 'Checking'
        elif 'SAVINGS' in text.upper():
            info['account_type'] = 'Savings'
        elif 'CREDIT CARD' in text.upper():
            info['account_type'] = 'Credit Card'
        
        return info
