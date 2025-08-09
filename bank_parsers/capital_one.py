"""
Capital One Bank Statement Parser
---------------------------------
Parser for Capital One credit card PDF statements.
"""

import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from . import BankStatementParser


class CapitalOneParser(BankStatementParser):
    """Parser for Capital One credit card statements."""
    
    def __init__(self):
        super().__init__()
        self.bank_name = "Capital One"
        self.supported_formats = ["PDF"]
    
    def can_parse(self, text: str) -> bool:
        """Check if this is a Capital One statement."""
        # Primary Capital One identifiers
        primary_indicators = [
            "Capital One", "CAPITAL ONE",
            "capitalone.com", "CAPITALONE.COM",
            "Capital One Bank", "CAPITAL ONE BANK"
        ]
        
        # Secondary indicators (with exclusions)
        secondary_indicators = [
            "World Mastercard", "WORLD MASTERCARD",
            "Platinum Card", "PLATINUM CARD",
            "Trans Date Post Date", # Transaction table header
        ]
        
        text_upper = text.upper()
        
        # Check for primary indicators first
        for indicator in primary_indicators:
            if indicator.upper() in text_upper:
                return True
        
        # Check secondary indicators (make sure it's not another bank)
        other_bank_exclusions = [
            "CHASE", "JPMORGAN", "CITI", "CITIBANK", "BANK OF AMERICA", "BOA"
        ]
        
        # If we find other bank patterns, this is not Capital One
        for exclusion in other_bank_exclusions:
            if exclusion in text_upper:
                return False
        
        # Check secondary indicators
        for indicator in secondary_indicators:
            if indicator.upper() in text_upper:
                return True
        
        return False
    
    def extract_transactions(self, text: str) -> List[Dict[str, Any]]:
        """Extract transactions from Capital One statement text."""
        transactions = []
        lines = text.split('\n')
        
        # Capital One transaction patterns
        patterns = [
            # Standard format: TransDate PostDate Description Amount
            # Example: Jun 2 Jun 3 BEST BUY 00010371NEWNANGA $194.95
            r'([A-Za-z]{3}\s+\d{1,2})\s+([A-Za-z]{3}\s+\d{1,2})\s+(.+?)\s+\$?([\d,]+\.\d{2})\s*$',
            
            # Payment format: TransDate PostDate Description - Amount
            # Example: May 22 May 22 CAPITAL ONE MOBILE PYMTAuthDate 22-May - $244.23
            r'([A-Za-z]{3}\s+\d{1,2})\s+([A-Za-z]{3}\s+\d{1,2})\s+(.+?)\s+-\s*\$?([\d,]+\.\d{2})\s*$',
            
            # Numeric date format: MM/DD MM/DD Description Amount (if they use this format)
            r'(\d{1,2}/\d{1,2})\s+(\d{1,2}/\d{1,2})\s+(.+?)\s+\$?([\d,]+\.\d{2})\s*$',
            
            # Single date format: TransDate Description Amount
            r'([A-Za-z]{3}\s+\d{1,2})\s+(.+?)\s+\$?([\d,]+\.\d{2})\s*$',
        ]
        
        # Extract statement year for date parsing
        year_hint = self._extract_statement_year(text)
        
        # Process lines
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Skip non-transaction lines
            skip_patterns = [
                r'Trans Date Post Date',  # Header
                r'Total.*for.*Period',    # Summary lines
                r'Interest Charge',       # Interest lines
                r'Annual Percentage',     # APR lines
                r'Page \d+ of \d+',      # Page numbers
                r'ROBERT JONES #\d+:',   # Section headers
                r'Additional Information', # Footer
                r'World Mastercard ending', # Card info
                r'days in Billing Cycle',   # Billing info
            ]
            
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in skip_patterns):
                continue
            
            # Try to match transaction patterns
            for pattern in patterns:
                try:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        transaction = self._parse_transaction_match(match, pattern, year_hint)
                        if transaction:
                            transactions.append(transaction)
                        break
                except re.error:
                    continue
        
        return transactions
    
    def _extract_statement_year(self, text: str) -> Optional[int]:
        """Extract the statement year from the PDF text."""
        # Look for date ranges in Capital One format
        year_patterns = [
            r'([A-Za-z]{3}\s+\d{1,2},\s+(\d{4}))\s*-\s*[A-Za-z]{3}\s+\d{1,2},\s+\d{4}',  # May 22, 2025 - Jun 20, 2025
            r'Statement.*Period.*(\d{4})',
            r'(\d{4})\s+Statement',
        ]
        
        for pattern in year_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(2) if len(match.groups()) > 1 else match.group(1))
                except (ValueError, IndexError):
                    continue
        
        # Default to current year
        return datetime.now().year
    
    def _parse_transaction_match(self, match, pattern, year_hint: Optional[int]) -> Optional[Dict[str, Any]]:
        """Parse a regex match into a transaction dictionary."""
        try:
            groups = match.groups()
            
            if len(groups) == 4:  # TransDate, PostDate, Description, Amount
                trans_date_str, post_date_str, description, amount_str = groups
                date_str = trans_date_str  # Use transaction date
            elif len(groups) == 3:  # Date, Description, Amount
                date_str, description, amount_str = groups
            else:
                return None
            
            # Check if this is a payment/credit by looking for dash in description
            # Capital One shows payments as "DESCRIPTION - $AMOUNT"
            if " - " in description or description.strip().endswith(" -"):
                # This is a payment or credit - skip for expense tracking
                return None
            
            # Parse Capital One date format (e.g., "Jun 2" -> "Jun 2, 2025")
            if re.match(r'[A-Za-z]{3}\s+\d{1,2}', date_str):
                date_str = f"{date_str}, {year_hint or datetime.now().year}"
            
            # Parse date
            date_obj = self.parse_date(date_str, year_hint)
            if not date_obj:
                return None
            
            # Parse amount
            amount = self.parse_amount(amount_str)
            if amount is None:
                return None
            
            # Clean up description
            description = self._clean_description(description)
            
            return {
                'date': date_obj,
                'description': description,
                'amount': amount,
                'type': 'debit'
            }
            
        except Exception as e:
            return None
    
    def parse_date(self, date_str: str, year_hint: Optional[int] = None) -> Optional[datetime]:
        """Parse Capital One date formats."""
        try:
            # Capital One uses formats like "Jun 2, 2025" or "Jun 2"
            date_str = date_str.strip()
            
            # Try Capital One formats first
            capital_one_formats = [
                '%b %d, %Y',    # Jun 2, 2025
                '%b %d',        # Jun 2 (need to add year)
                '%B %d, %Y',    # June 2, 2025
                '%B %d',        # June 2 (need to add year)
            ]
            
            for fmt in capital_one_formats:
                try:
                    parsed_date = datetime.strptime(date_str, fmt)
                    
                    # If year is missing and we have a hint, use it
                    if year_hint and parsed_date.year == 1900:
                        parsed_date = parsed_date.replace(year=year_hint)
                    
                    return parsed_date
                except ValueError:
                    continue
            
            # Fall back to base class method for other formats
            return super().parse_date(date_str, year_hint)
            
        except (ValueError, TypeError):
            return None
    
    def _clean_description(self, description: str) -> str:
        """Clean up transaction description."""
        # Remove extra whitespace
        description = ' '.join(description.split())
        
        # Remove common Capital One artifacts
        artifacts = [
            r'AuthDate\s+\d{1,2}-[A-Za-z]{3}',  # AuthDate 22-May
            r'#\d+:',  # Account number references
        ]
        
        for artifact in artifacts:
            description = re.sub(artifact, '', description, flags=re.IGNORECASE)
        
        # Clean up extra spaces
        description = ' '.join(description.split())
        
        return description.strip()
    
    def get_account_info(self, text: str) -> Dict[str, Any]:
        """Extract account information from Capital One statement."""
        account_info = {
            'bank_name': self.bank_name,
            'account_type': 'Credit Card'
        }
        
        # Extract account number (card ending digits)
        account_patterns = [
            r'World Mastercard ending in (\d{4})',
            r'Platinum Card.*ending in (\d{4})',
            r'#(\d{4}):',
        ]
        
        for pattern in account_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                account_info['account_number'] = f"****{match.group(1)}"
                break
        
        # Extract statement period
        period_pattern = r'([A-Za-z]{3}\s+\d{1,2},\s+\d{4})\s*-\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})'
        period_match = re.search(period_pattern, text)
        if period_match:
            account_info['statement_period'] = f"{period_match.group(1)} - {period_match.group(2)}"
        
        return account_info
