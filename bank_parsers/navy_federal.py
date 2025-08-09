"""
Navy Federal Credit Union Bank Statement Parser
-----------------------------------------------
Parser for Navy Federal Credit Union PDF statements.
"""

import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from . import BankStatementParser


class NavyFederalParser(BankStatementParser):
    """Parser for Navy Federal Credit Union statements."""
    
    def __init__(self):
        super().__init__()
        self.bank_name = "Navy Federal"
        self.supported_formats = ["PDF"]
    
    def can_parse(self, text: str) -> bool:
        """Check if this is a Navy Federal statement."""
        # Primary Navy Federal identifiers
        primary_indicators = [
            "Navy Federal", "NAVY FEDERAL",
            "Navy Federal Credit Union", "NAVY FEDERAL CREDIT UNION",
            "NFCU"
        ]
        
        # Secondary indicators (with exclusions)
        secondary_indicators = [
            "Navy Federal Online Banking",
            "STMSSCM",  # Common in Navy Federal statement filenames
            "Date Transaction Detail Amount($) Balance($)",  # Transaction table header
        ]
        
        text_upper = text.upper()
        
        # Check for primary indicators first
        for indicator in primary_indicators:
            if indicator.upper() in text_upper:
                return True
        
        # Check secondary indicators (make sure it's not another bank)
        other_bank_exclusions = [
            "CHASE", "JPMORGAN", "CITI", "CITIBANK", "BANK OF AMERICA", "BOA", "CAPITAL ONE"
        ]
        
        # If we find other bank patterns, this is not Navy Federal
        for exclusion in other_bank_exclusions:
            if exclusion in text_upper:
                return False
        
        # Check secondary indicators
        for indicator in secondary_indicators:
            if indicator.upper() in text_upper:
                return True
        
        return False
    
    def extract_transactions(self, text: str) -> List[Dict[str, Any]]:
        """Extract transactions from Navy Federal statement text."""
        transactions = []
        lines = text.split('\n')
        
        # Navy Federal transaction patterns
        patterns = [
            # Credit Card format: MM/DD/YY MM/DD/YY TransactionID Merchant Location $Amount
            # Example: 08/24/24 08/26/24 24269794238500664550107 GREENS DISCOUNT BEVERA GREENVILLE SC $79.68
            r'(\d{2}/\d{2}/\d{2})\s+(\d{2}/\d{2}/\d{2})\s+(\d{20,})\s+(.+?)\s+([A-Z]{2})\s+\$?([\d,]+\.\d{2})\s*$',
            
            # Credit Card format without state code at end
            # Example: 09/06/24 09/09/24 74648934251134831580143 SegPayEU.com*SB 866-450-4000 $289.00
            r'(\d{2}/\d{2}/\d{2})\s+(\d{2}/\d{2}/\d{2})\s+(\d{20,})\s+(.+?)\s+\$?([\d,]+\.\d{2})\s*$',
            
            # Standard checking format: MM-DD Description Amount Balance
            # Example: 07-11 Checking Monthly Service Fee 10.00- 314.26
            r'(\d{2}-\d{2})\s+(.+?)\s+([\d,]+\.\d{2}[-]?)\s+([\d,]+\.\d{2})\s*$',
            
            # Complex transaction with embedded date (still follows same pattern)
            # Example: 06-24 POS Credit Adjustment 0972 Transaction 06-24-25 Zelle*jones Auto Visa Direct AZ 1,200.00 1,806.84
            r'(\d{2}-\d{2})\s+(.+?Transaction\s+\d{2}-\d{2}-\d{2}\s+.+?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$',
            
            # Transfer pattern
            # Example: 06-24 Transfer To Credit Card 600.00- 1,206.84
            r'(\d{2}-\d{2})\s+(Transfer\s+.+?)\s+([\d,]+\.\d{2}[-]?)\s+([\d,]+\.\d{2})\s*$',
            
            # Fee pattern
            # Example: 07-11 Checking Monthly Service Fee 10.00- 314.26
            r'(\d{2}-\d{2})\s+(.+?Fee)\s+([\d,]+\.\d{2}[-]?)\s+([\d,]+\.\d{2})\s*$',
            
            # Dividend pattern
            # Example: 06-30 Dividend 0.08 401.05
            r'(\d{2}-\d{2})\s+(Dividend)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$',
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
                r'Date Transaction Detail Amount',  # Header
                r'Beginning Balance',               # Balance lines
                r'Ending Balance',                  # Balance lines
                r'Average Daily Balance',           # Summary lines
                r'Your account earned',             # Interest summary
                r'annual percentage yield',         # APR lines
                r'dividend period',                 # Dividend period info
                r'Summary of your deposit',         # Account summary
                r'Previous Deposits',               # Summary headers
                r'Totals',                         # Total lines
                r'DEPOSITVOUCHER',                 # Deposit voucher
                r'Page \d+ of \d+',               # Page numbers
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
        # Look for date ranges in Navy Federal format
        year_patterns = [
            r'(\d{2})/(\d{2})/(\d{2})\s*-\s*(\d{2})/(\d{2})/(\d{2})',  # 06/12/25 - 07/11/25
            r'Statement.*Period.*(\d{4})',
            r'(\d{4})\s+Statement',
        ]
        
        for pattern in year_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    # For Navy Federal format like "06/12/25 - 07/11/25"
                    if len(match.groups()) >= 6:
                        year_str = match.group(6)  # Last year in range
                        if len(year_str) == 2:
                            # Convert 2-digit year to 4-digit (assume 20xx)
                            year = 2000 + int(year_str)
                        else:
                            year = int(year_str)
                        return year
                    else:
                        return int(match.group(1))
                except (ValueError, IndexError):
                    continue
        
        # Default to current year
        return datetime.now().year
    
    def _parse_transaction_match(self, match, pattern, year_hint: Optional[int]) -> Optional[Dict[str, Any]]:
        """Parse a regex match into a transaction dictionary."""
        try:
            groups = match.groups()
            
            # Handle different credit card formats
            if len(groups) == 6:  # Credit card format with state: TransDate, PostDate, ID, Merchant, State, Amount
                trans_date_str, post_date_str, transaction_id, description, state, amount_str = groups
                date_str = trans_date_str  # Use transaction date
                description = f"{description} {state}"  # Include state in description
            elif len(groups) == 5:  # Credit card format without state: TransDate, PostDate, ID, Merchant, Amount
                trans_date_str, post_date_str, transaction_id, description, amount_str = groups
                date_str = trans_date_str  # Use transaction date
            elif len(groups) >= 4:  # Checking format: Date, Description, Amount, Balance
                date_str, description, amount_str, balance_str = groups[:4]
            elif len(groups) == 3:  # Date, Description, Amount (no balance)
                date_str, description, amount_str = groups
            else:
                return None
            
            # Skip balance-only lines
            if 'beginning balance' in description.lower() or 'ending balance' in description.lower():
                return None
            
            # Parse Navy Federal date formats
            if re.match(r'\d{2}/\d{2}/\d{2}', date_str):
                # Credit card format: MM/DD/YY -> MM/DD/20YY
                date_str = date_str.replace('/', '/')
                if len(date_str.split('/')[-1]) == 2:
                    year = '20' + date_str.split('/')[-1]
                    date_str = '/'.join(date_str.split('/')[:-1]) + '/' + year
            elif re.match(r'\d{2}-\d{2}', date_str):
                # Checking format: MM-DD -> MM-DD-YYYY
                date_str = f"{date_str}-{year_hint or datetime.now().year}"
            
            # Parse date
            date_obj = self.parse_date(date_str, year_hint)
            if not date_obj:
                return None
            
            # Parse amount - Navy Federal checking uses suffix '-' for debits, credit cards are all debits
            is_debit = amount_str.endswith('-') or len(groups) >= 5  # Credit card transactions are debits
            clean_amount_str = amount_str.rstrip('-')
            
            amount = self.parse_amount(clean_amount_str)
            if amount is None:
                return None
            
            # Clean up description
            description = self._clean_description(description)
            
            # Determine transaction type based on description and amount sign
            tx_type = 'debit' if is_debit else 'credit'
            
            return {
                'date': date_obj,
                'description': description,
                'amount': amount,
                'type': tx_type
            }
            
        except Exception as e:
            return None
    
    def parse_date(self, date_str: str, year_hint: Optional[int] = None) -> Optional[datetime]:
        """Parse Navy Federal date formats."""
        try:
            # Navy Federal uses formats like "MM-DD-YYYY", "MM-DD", "MM/DD/YY", "MM/DD/YYYY"
            date_str = date_str.strip()
            
            # Try Navy Federal formats first
            navy_federal_formats = [
                '%m/%d/%Y',     # 08/24/2024 (credit card full year)
                '%m/%d/%y',     # 08/24/24 (credit card 2-digit year)
                '%m-%d-%Y',     # 06-24-2025 (checking full year)
                '%m-%d',        # 06-24 (checking, need to add year)
            ]
            
            for fmt in navy_federal_formats:
                try:
                    parsed_date = datetime.strptime(date_str, fmt)
                    
                    # If year is missing and we have a hint, use it
                    if year_hint and parsed_date.year == 1900:
                        parsed_date = parsed_date.replace(year=year_hint)
                    
                    # Handle 2-digit years (assume 20xx for years 00-99)
                    if parsed_date.year < 100:
                        parsed_date = parsed_date.replace(year=parsed_date.year + 2000)
                    
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
        
        # Remove common Navy Federal artifacts
        artifacts = [
            r'Transaction\s+\d{2}-\d{2}-\d{2}',  # Embedded transaction dates
            r'0972\s+Transaction',               # Transaction codes
        ]
        
        for artifact in artifacts:
            description = re.sub(artifact, '', description, flags=re.IGNORECASE)
        
        # Clean up extra spaces
        description = ' '.join(description.split())
        
        return description.strip()
    
    def get_account_info(self, text: str) -> Dict[str, Any]:
        """Extract account information from Navy Federal statement."""
        account_info = {
            'bank_name': self.bank_name,
            'account_type': 'Checking/Savings'
        }
        
        # Extract account number (often appears in patterns like account numbers)
        account_patterns = [
            r'(\d{10,})',  # Long account numbers
            r'Account.*?(\d{4,})',
        ]
        
        for pattern in account_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                account_num = match.group(1)
                if len(account_num) >= 4:
                    account_info['account_number'] = f"****{account_num[-4:]}"
                break
        
        # Extract statement period
        period_pattern = r'(\d{2}/\d{2}/\d{2})\s*-\s*(\d{2}/\d{2}/\d{2})'
        period_match = re.search(period_pattern, text)
        if period_match:
            account_info['statement_period'] = f"{period_match.group(1)} - {period_match.group(2)}"
        
        return account_info
