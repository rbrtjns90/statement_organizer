"""
Citibank Statement Parser
-------------------------
Parser for Citibank PDF statements.
"""

import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from . import BankStatementParser


class CitibankParser(BankStatementParser):
    """Parser for Citibank statements."""
    
    def __init__(self):
        super().__init__()
        self.bank_name = "Citibank"
        self.supported_formats = ["PDF"]
    
    def can_parse(self, text: str) -> bool:
        """Enhanced Citibank detection with comprehensive patterns."""
        indicators = [
            # Core brand names (case variations)
            "Citibank", "CITIBANK", "CitiBank", "CITI BANK",
            "Citi", "CITI",
            "Citicorp", "CITICORP", 
            "Citigroup", "CITIGROUP",
            
            # Web domains and URLs
            "citibank.com", "citi.com", "online.citi.com",
            "www.citi.com", "WWW.CITI.COM",
            
            # Banking regulatory and service phrases
            "Member FDIC", "MEMBER FDIC", "FDIC",
            "Thank you for banking with Citi",
            "Citi Customer Service", "CITI CUSTOMER SERVICE",
            "CitiPhone Banking", "CITIPHONE BANKING",
            "Citi Cards", "CITI CARDS", "CitiCard", "CITICARD",
            
            # Statement headers and document identifiers
            "Account Summary", "ACCOUNT SUMMARY",
            "Statement Period", "STATEMENT PERIOD", 
            "Citi Statement", "CITI STATEMENT",
            "Checking Account Summary", "CHECKING ACCOUNT SUMMARY",
            "Savings Account Summary", "SAVINGS ACCOUNT SUMMARY",
            
            # Additional Citi-specific terms
            "Citi Online", "CITI ONLINE",
            "Citi Mobile", "CITI MOBILE",
            "CitiBusiness", "CITIBUSINESS",
            "Citi Priority", "CITI PRIORITY"
        ]
        
        text_upper = text.upper()
        
        # Check for any indicator
        for indicator in indicators:
            if indicator.upper() in text_upper:
                return True
        
        # Additional fuzzy matching for "CITI" variations with word boundaries
        citi_variations = [
            "CITI ", " CITI", "CITI\n", "\nCITI", 
            "CITI.", ".CITI", "CITI,", ",CITI",
            "CITI:", ":CITI", "CITI-", "-CITI"
        ]
        for variation in citi_variations:
            if variation in text_upper:
                return True
        
        return False
    
    def extract_transactions(self, text):
        """Extract transactions from Citibank statement text, handling complex multi-line formats."""
        transactions = []
        lines = text.split('\n')
        
        # First pass: Extract complete transactions (standard patterns)
        complete_transactions = self._extract_complete_transactions(lines)
        transactions.extend(complete_transactions)
        
        # Second pass: Handle complex multi-line transactions
        complex_transactions = self._extract_complex_multiline_transactions(lines)
        transactions.extend(complex_transactions)
        
        return transactions
    
    def _extract_complete_transactions(self, lines):
        """Extract transactions that have date, description, and amount on the same line."""
        transactions = []
        
        # Enhanced Citibank transaction patterns for credit card statements
        patterns = [
            # Two-date format: MM/DD MM/DD Description Amount (with optional trailing text)
            r'(\d{1,2}/\d{1,2})\s+(\d{1,2}/\d{1,2})\s+(.+?)\s+\$?([\d,]+\.\d{2})(?:\s+.*)?$',
            
            # AUTOPAY format: MM/DD AUTOPAY ... -$Amount Description
            r'(\d{1,2}/\d{1,2})\s+AUTOPAY\s+.+?\s+-\$?([\d,]+\.\d{2})\s+(.+?)$',
            
            # Primary format: MM/DD Description Amount (most common for Citi credit cards)
            r'(\d{1,2}/\d{1,2})\s+([A-Za-z0-9][^$\d]*?)\s+\$?([\d,]+\.\d{2})\s*$',
            
            # Negative amounts in parentheses: MM/DD Description (Amount)
            r'(\d{1,2}/\d{1,2})\s+([A-Za-z0-9][^(]*?)\s+\(([\d,]+\.\d{2})\)\s*$',
            
            # With year: MM/DD/YYYY Description Amount
            r'(\d{1,2}/\d{1,2}/\d{2,4})\s+([A-Za-z0-9][^$\d]*?)\s+\$?([\d,]+\.\d{2})\s*$',
            
            # Credit card payments and credits: MM/DD Description -Amount
            r'(\d{1,2}/\d{1,2})\s+([A-Za-z0-9][^-]*?)\s+-\$?([\d,]+\.\d{2})\s*$',
            
            # Simple format without dollar sign: MM/DD Description Amount
            r'(\d{1,2}/\d{1,2})\s+([A-Za-z0-9][^\d]*?)\s+([\d,]+\.\d{2})$',
            
            # More flexible description matching (catches more variations)
            r'(\d{1,2}/\d{1,2})\s+([^$\d]+?)\s+([\d,]+\.\d{2})\s*$',
            
            # Handle transactions with multiple spaces or tabs
            r'(\d{1,2}/\d{1,2})\s+(.+?)\s{2,}([\d,]+\.\d{2})\s*$',
        ]
        
        # Extract statement year for date parsing
        year_hint = self._extract_statement_year('\n'.join(lines))
        
        # Process lines with timeout protection
        processed_lines = 0
        max_lines = 10000  # Prevent processing extremely large files
        
        for line in lines:
            processed_lines += 1
            if processed_lines > max_lines:
                break
                
            line = line.strip()
            if not line or len(line) > 500:  # Skip very long lines that might cause issues
                continue
            
            # Quick pre-filter: must contain date pattern and amount pattern
            if not (re.search(r'\d{1,2}/\d{1,2}', line) and re.search(r'[\d,]+\.\d{2}', line)):
                continue
            
            # Skip non-transaction lines (balance statements, headers, etc.)
            skip_patterns = [
                r'New balance as of',
                r'Previous balance',
                r'Payment due',
                r'Minimum payment',
                r'Credit limit',
                r'Available credit',
                r'Statement period',
                r'Account summary',
                r'Total fees',
                r'Interest rate'
            ]
            
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in skip_patterns):
                continue
            
            for pattern in patterns:
                try:
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        transaction = self._parse_transaction_match(match, pattern, year_hint)
                        if transaction:
                            transactions.append(transaction)
                        break
                except re.error:
                    # Skip problematic regex matches
                    continue
        
        return transactions
    
    def _extract_complex_multiline_transactions(self, lines):
        """Extract transactions from complex multi-line formats where transactions span multiple lines."""
        transactions = []
        
        # Find lines that contain multiple dates but no amounts (incomplete transactions)
        incomplete_transactions = []
        orphaned_amounts = []
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # Find lines with multiple dates but no amounts
            date_matches = re.findall(r'\d{2}/\d{2}', line)
            amount_matches = re.findall(r'\$[\d,]+\.\d{2}', line)
            
            if len(date_matches) >= 4 and not amount_matches:  # Multiple transactions crammed together
                # Split the line into individual transactions
                individual_txns = self._split_multiline_transactions(line)
                incomplete_transactions.extend([(i, txn) for txn in individual_txns])
            
            # Find orphaned amounts (lines with just amounts)
            elif amount_matches and not date_matches:
                for amount in amount_matches:
                    orphaned_amounts.append({
                        'line_num': i,
                        'amount': amount.replace('$', ''),
                        'original_line': line
                    })
        
        # Try to match incomplete transactions with nearby orphaned amounts
        for line_num, incomplete_txn in incomplete_transactions:
            # Look for orphaned amounts within 10 lines
            nearby_amounts = [
                amt for amt in orphaned_amounts 
                if abs(amt['line_num'] - line_num) <= 10
            ]
            
            if nearby_amounts:
                # Use the first available amount
                amount_info = nearby_amounts[0]
                
                # Create transaction
                transaction = {
                    'date': self.parse_date(incomplete_txn['date']),
                    'description': incomplete_txn['description'].strip(),
                    'amount': float(amount_info['amount'].replace(',', '')),
                    'type': 'debit'
                }
                
                transactions.append(transaction)
                
                # Remove used amount to avoid double-counting
                orphaned_amounts.remove(amount_info)
        
        return transactions
    
    def _split_multiline_transactions(self, line):
        """Split a line containing multiple transactions into individual transactions."""
        transactions = []
        
        # Pattern to find date + description pairs
        # Look for MM/DD followed by text until the next MM/DD
        pattern = r'(\d{2}/\d{2})\s+(\d{2}/\d{2})\s+([^0-9]+?)(?=\d{2}/\d{2}|$)'
        matches = re.findall(pattern, line)
        
        for match in matches:
            date1, date2, description = match
            transactions.append({
                'date': date1,  # Use first date
                'description': description.strip()
            })
        
        return transactions
    
    def _extract_statement_year(self, text: str) -> Optional[int]:
        """Extract the statement year from the PDF text."""
        year_patterns = [
            r'Statement\s+Period[:\s]+\d{1,2}/\d{1,2}/(\d{4})',
            r'Account\s+Summary\s+as\s+of\s+\w+\s+\d{1,2},\s+(\d{4})',
            r'(\d{4})\s+Account\s+Activity'
        ]
        
        for pattern in year_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except (ValueError, IndexError):
                    continue
        
        return datetime.now().year
    
    def _parse_transaction_match(self, match, pattern, year_hint: Optional[int]) -> Optional[Dict[str, Any]]:
        """Parse a regex match into a transaction dictionary."""
        try:
            groups = match.groups()
            
            if len(groups) == 3:  # Date, Description, Amount OR Date, Amount, Description (AUTOPAY)
                if "AUTOPAY" in pattern:  # AUTOPAY format: Date, Amount, Description
                    date_str, amount_str, description = groups
                    description = f"AUTOPAY {description}".strip()
                else:  # Normal format: Date, Description, Amount
                    date_str, description, amount_str = groups
            elif len(groups) == 4:  # Two-date format: Date1, Date2, Description, Amount
                date_str, date2_str, description, amount_str = groups
                # Use the first date as the transaction date
            else:
                return None
            
            # Parse date (add year if missing)
            if '/' in date_str and len(date_str.split('/')) == 2:
                date_str = f"{date_str}/{year_hint or datetime.now().year}"
            
            date_obj = self.parse_date(date_str, year_hint)
            if not date_obj:
                return None
            
            # Parse amount - handle different formats
            amount_str = amount_str.replace('$', '').replace(',', '').strip()
            
            # Handle parentheses (negative amounts)
            is_negative = False
            if amount_str.startswith('(') and amount_str.endswith(')'):
                amount_str = amount_str[1:-1]
                is_negative = True
            
            # Handle negative sign
            if amount_str.startswith('-'):
                amount_str = amount_str[1:]
                is_negative = True
            
            try:
                amount = float(amount_str)
            except ValueError:
                return None
            
            # Apply negative if needed
            if is_negative:
                amount = -amount
            
            # For credit cards, charges are positive (expenses), payments/credits are negative
            # We want to capture all transactions, not just expenses
            if amount == 0:
                return None
            
            # Clean up description
            description = self._clean_description(description)
            
            return {
                'date': date_obj,
                'description': description,
                'amount': abs(amount),  # Store as positive, track type separately if needed
                'category': None,
                'bank': self.bank_name,
                'transaction_type': 'credit' if amount < 0 else 'debit'
            }
            
        except Exception as e:
            return None
    
    def _clean_description(self, description: str) -> str:
        """Clean up transaction description."""
        # Remove extra whitespace
        description = ' '.join(description.split())
        
        # Remove common Citibank prefixes/suffixes
        prefixes_to_remove = [
            'DEBIT PURCHASE - ',
            'ELECTRONIC PAYMENT - ',
            'ONLINE PAYMENT - ',
            'AUTOMATIC PAYMENT - ',
            'POS PURCHASE - ',
            'ATM WITHDRAWAL - ',
        ]
        
        for prefix in prefixes_to_remove:
            if description.upper().startswith(prefix):
                description = description[len(prefix):].strip()
        
        # Remove trailing reference numbers and authorization codes
        description = re.sub(r'\s+AUTH\s+\w+\s*$', '', description, re.IGNORECASE)
        description = re.sub(r'\s+REF\s+\w+\s*$', '', description, re.IGNORECASE)
        description = re.sub(r'\s+#\w+\s*$', '', description)
        
        return description.strip()
    
    def get_account_info(self, text: str) -> Dict[str, str]:
        """Extract account information from Citibank statement."""
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
        if 'CHECKING' in text.upper():
            info['account_type'] = 'Checking'
        elif 'SAVINGS' in text.upper():
            info['account_type'] = 'Savings'
        elif 'CREDIT CARD' in text.upper() or 'MASTERCARD' in text.upper():
            info['account_type'] = 'Credit Card'
        
        return info
