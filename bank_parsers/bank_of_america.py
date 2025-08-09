"""
Bank of America Statement Parser
--------------------------------
Parser for Bank of America PDF statements.
"""

import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from . import BankStatementParser


class BankOfAmericaParser(BankStatementParser):
    """Parser for Bank of America statements."""
    
    def __init__(self):
        super().__init__()
        self.bank_name = "Bank of America"
        self.supported_formats = ["PDF"]
    
    def can_parse(self, text: str) -> bool:
        """Check if this is a Bank of America statement."""
        indicators = [
            "Bank of America",
            "BANK OF AMERICA",
            "BofA",
            "bankofamerica.com",
            "Member FDIC"
        ]
        
        text_upper = text.upper()
        return any(indicator.upper() in text_upper for indicator in indicators)
    
    def extract_transactions(self, text: str) -> List[Dict[str, Any]]:
        """Extract transactions from Bank of America statement text."""
        transactions = []
        lines = text.split('\n')
        
        # Bank of America transaction patterns
        patterns = [
            # Standard format: MM/DD/YYYY Description Amount
            r'(\d{1,2}/\d{1,2}/\d{2,4})\s+(.+?)\s+([-]?\$?[\d,]+\.?\d*)\s*$',
            # Alternative format with transaction type
            r'(\d{1,2}/\d{1,2}/\d{2,4})\s+(\w+)\s+(.+?)\s+([-]?\$?[\d,]+\.?\d*)\s*$',
            # Format with check number
            r'(\d{1,2}/\d{1,2}/\d{2,4})\s+CHECK\s+(\d+)\s+(.+?)\s+([-]?\$?[\d,]+\.?\d*)\s*$'
        ]
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            for pattern in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    transaction = self._parse_transaction_match(match, pattern)
                    if transaction:
                        transactions.append(transaction)
                    break
        
        return transactions
    
    def _parse_transaction_match(self, match, pattern) -> Optional[Dict[str, Any]]:
        """Parse a regex match into a transaction dictionary."""
        try:
            groups = match.groups()
            
            if len(groups) == 3:  # Date, Description, Amount
                date_str, description, amount_str = groups
            elif len(groups) == 4:  # Date, Type, Description, Amount OR Date, Check, Number, Amount
                if "CHECK" in pattern:
                    date_str, check_type, check_num, amount_str = groups
                    description = f"Check #{check_num}"
                else:
                    date_str, trans_type, description, amount_str = groups
                    description = f"{trans_type} {description}".strip()
            else:
                return None
            
            # Parse date
            date_obj = self.parse_date(date_str)
            if not date_obj:
                return None
            
            # Parse amount
            amount = self.parse_amount(amount_str)
            if amount is None:
                return None
            
            # Skip deposits (positive amounts) - focus on expenses
            if amount > 0:
                return None
            
            amount = abs(amount)  # Make amount positive for expenses
            
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
        
        # Remove common Bank of America prefixes/suffixes
        prefixes_to_remove = [
            'DEBIT CARD PURCHASE ',
            'ONLINE BANKING TRANSFER ',
            'ATM WITHDRAWAL ',
            'CHECK CARD PURCHASE ',
            'RECURRING PAYMENT ',
        ]
        
        for prefix in prefixes_to_remove:
            if description.upper().startswith(prefix):
                description = description[len(prefix):].strip()
        
        # Remove trailing reference numbers (common pattern: #XXXXXXXX)
        description = re.sub(r'\s+#\w+\s*$', '', description)
        
        return description.strip()
    
    def get_account_info(self, text: str) -> Dict[str, str]:
        """Extract account information from Bank of America statement."""
        info = {}
        
        # Account number pattern
        account_match = re.search(r'Account\s+(?:Number\s+)?(\d{4})', text, re.IGNORECASE)
        if account_match:
            info['account_number'] = f"****{account_match.group(1)}"
        
        # Statement period
        period_match = re.search(r'Statement\s+Period[:\s]+(\d{1,2}/\d{1,2}/\d{2,4})\s+(?:to|through|-)\s+(\d{1,2}/\d{1,2}/\d{2,4})', text, re.IGNORECASE)
        if period_match:
            info['period_start'] = period_match.group(1)
            info['period_end'] = period_match.group(2)
        
        # Account type
        if 'CHECKING' in text.upper():
            info['account_type'] = 'Checking'
        elif 'SAVINGS' in text.upper():
            info['account_type'] = 'Savings'
        elif 'CREDIT' in text.upper():
            info['account_type'] = 'Credit Card'
        
        return info
