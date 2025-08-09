"""
Generic Bank Statement Parser using K-means clustering and regex pattern detection
----------------------------------------------------------------------------------
This parser uses machine learning to automatically detect transaction patterns
in bank statements without requiring bank-specific rules.

"""

import re
import math
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from sklearn.cluster import KMeans
import pdfplumber

from . import BankStatementParser


@dataclass
class Token:
    text: str
    x0: float
    x1: float
    y0: float
    y1: float


@dataclass
class Line:
    tokens: List[Token]
    y: float
    text: str


class GenericRegexParser(BankStatementParser):
    """Generic parser using K-means clustering to detect transaction patterns."""
    
    def __init__(self):
        super().__init__()
        self.bank_name = "Generic (Auto-detect)"
        self.supported_formats = ["PDF"]
        
        # Regex patterns for common financial data
        self.RE_MONEY = re.compile(r"[+\-]?\$?\d{1,3}(?:,\d{3})*\.\d{2}")
        self.RE_DATE = re.compile(
            r"""(?ix)
            (?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)     # 01/31[/2025]
            | (?:\d{4}[/-]\d{1,2}[/-]\d{1,2})          # 2025-01-31
            | (?:\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})    # 31 Jan 2025
            | (?:[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4})  # Jan 31, 2025
            | (?:[A-Za-z]{3,9}\s+\d{1,2})              # Jan 31
            """
        )
        
        # Keywords that indicate non-transaction lines
        self.summary_keywords = [
            'previous balance', 'new balance', 'minimum payment', 'payment due',
            'credit limit', 'past due', 'fees charged', 'cash advance', 
            'balance transfer', 'messages for details', 'over the credit limit',
            'customer service', 'website', 'phone', 'autopay', 'account message',
            'www.', '.com', 'http', 'total', 'subtotal'
        ]
    
    def can_parse(self, text: str) -> bool:
        """
        This is a fallback parser - it can attempt to parse any statement
        but should be used as last resort after specific parsers fail.
        """
        # Check if text contains basic financial statement indicators
        indicators = [
            'statement', 'account', 'balance', 'transaction', 'payment',
            'deposit', 'withdrawal', 'credit', 'debit'
        ]
        
        text_lower = text.lower()
        indicator_count = sum(1 for indicator in indicators if indicator in text_lower)
        
        # Also check for money and date patterns
        has_money = bool(self.RE_MONEY.search(text))
        has_dates = bool(self.RE_DATE.search(text))
        
        # This parser can handle statements with financial indicators, money, and dates
        return indicator_count >= 2 and has_money and has_dates
    
    def load_page_lines(self, page) -> List[Line]:
        """Reconstruct lines from page.chars, grouping by similar y and merging chars into words/tokens."""
        if not hasattr(page, 'chars') or not page.chars:
            return []
        
        chars = page.chars
        if not chars:
            return []
        
        # Group chars by similar y-coordinate (within 2 points)
        y_groups = {}
        for char in chars:
            y = round(char['y0'], 1)
            found_group = False
            for existing_y in y_groups:
                if abs(y - existing_y) <= 2:
                    y_groups[existing_y].append(char)
                    found_group = True
                    break
            if not found_group:
                y_groups[y] = [char]
        
        lines = []
        for y, group_chars in y_groups.items():
            if not group_chars:
                continue
            
            # Sort chars by x position
            group_chars.sort(key=lambda c: c['x0'])
            
            # Merge chars into tokens (words)
            tokens = []
            current_token_chars = []
            
            for i, char in enumerate(group_chars):
                if not current_token_chars:
                    current_token_chars = [char]
                else:
                    # Check if this char is close enough to be part of the same token
                    prev_char = current_token_chars[-1]
                    gap = char['x0'] - prev_char['x1']
                    
                    if gap <= 3:  # Characters are close enough to be same word
                        current_token_chars.append(char)
                    else:
                        # Finish current token and start new one
                        if current_token_chars:
                            token_text = ''.join(c['text'] for c in current_token_chars)
                            token = Token(
                                text=token_text,
                                x0=current_token_chars[0]['x0'],
                                x1=current_token_chars[-1]['x1'],
                                y0=current_token_chars[0]['y0'],
                                y1=current_token_chars[0]['y1']
                            )
                            tokens.append(token)
                        current_token_chars = [char]
            
            # Don't forget the last token
            if current_token_chars:
                token_text = ''.join(c['text'] for c in current_token_chars)
                token = Token(
                    text=token_text,
                    x0=current_token_chars[0]['x0'],
                    x1=current_token_chars[-1]['x1'],
                    y0=current_token_chars[0]['y0'],
                    y1=current_token_chars[0]['y1']
                )
                tokens.append(token)
            
            if tokens:
                line_text = ' '.join(token.text for token in tokens)
                line = Line(tokens=tokens, y=y, text=line_text)
                lines.append(line)
        
        # Sort lines by y position (top to bottom)
        lines.sort(key=lambda l: -l.y)  # Negative for top-to-bottom
        return lines
    
    def line_features(self, line: Line, page_width: float) -> Dict[str, Any]:
        """Extract features from a line for clustering."""
        text = line.text
        
        # Basic text features
        n_tokens = len(line.tokens)
        n_chars = len(text)
        n_digits = sum(1 for c in text if c.isdigit())
        n_letters = sum(1 for c in text if c.isalpha())
        
        # Financial pattern features
        has_money = bool(self.RE_MONEY.search(text))
        money_matches = self.RE_MONEY.findall(text)
        n_money = len(money_matches)
        
        has_date = bool(self.RE_DATE.search(text))
        date_matches = self.RE_DATE.findall(text)
        n_dates = len(date_matches)
        
        # Position features
        if line.tokens:
            leftmost_x = min(token.x0 for token in line.tokens)
            rightmost_x = max(token.x1 for token in line.tokens)
            x_span = rightmost_x - leftmost_x
            x_center = (leftmost_x + rightmost_x) / 2
        else:
            leftmost_x = rightmost_x = x_span = x_center = 0
        
        # Normalize position features
        left_ratio = leftmost_x / page_width if page_width > 0 else 0
        center_ratio = x_center / page_width if page_width > 0 else 0
        span_ratio = x_span / page_width if page_width > 0 else 0
        
        return {
            'n_tokens': n_tokens,
            'n_chars': n_chars,
            'n_digits': n_digits,
            'n_letters': n_letters,
            'has_money': int(has_money),
            'n_money': n_money,
            'has_date': int(has_date),
            'n_dates': n_dates,
            'left_ratio': left_ratio,
            'center_ratio': center_ratio,
            'span_ratio': span_ratio,
            'digit_ratio': n_digits / max(n_chars, 1),
            'letter_ratio': n_letters / max(n_chars, 1),
        }
    
    def cluster_transactions(self, lines: List[Line], page_width: float) -> Tuple[List[int], List[Dict[str, Any]]]:
        """Cluster lines to identify transaction patterns."""
        if len(lines) < 2:
            return [0] * len(lines), []
        
        # Extract features for each line
        features = [self.line_features(line, page_width) for line in lines]
        
        # Convert to numpy array for clustering
        feature_names = ['n_tokens', 'n_chars', 'n_digits', 'n_letters', 'has_money', 
                        'n_money', 'has_date', 'n_dates', 'left_ratio', 'center_ratio', 
                        'span_ratio', 'digit_ratio', 'letter_ratio']
        
        X = np.array([[f[name] for name in feature_names] for f in features])
        
        # Determine optimal number of clusters (between 2 and 8)
        n_clusters = min(max(2, len(lines) // 5), 8)
        
        try:
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            labels = kmeans.fit_predict(X)
        except Exception:
            # Fallback: simple clustering based on money presence
            labels = [1 if f['has_money'] else 0 for f in features]
        
        return labels.tolist(), features
    
    def evaluate_clusters(self, labels: np.ndarray, features: List[Dict[str, Any]], lines: List[Line]) -> Tuple[float, int]:
        """Score each cluster and return the best one for transactions."""
        unique_labels = list(set(labels))
        best_score = -1
        best_cluster = 0
        
        for label in unique_labels:
            cluster_indices = [i for i, l in enumerate(labels) if l == label]
            cluster_features = [features[i] for i in cluster_indices]
            cluster_lines = [lines[i] for i in cluster_indices]
            
            if not cluster_features:
                continue
            
            # Score based on transaction-like characteristics
            money_rate = np.mean([f['has_money'] for f in cluster_features])
            date_rate = np.mean([f['has_date'] for f in cluster_features])
            avg_tokens = np.mean([f['n_tokens'] for f in cluster_features])
            avg_chars = np.mean([f['n_chars'] for f in cluster_features])
            
            # Check for summary/header content
            summary_rate = 0
            for line in cluster_lines:
                text_lower = line.text.lower()
                if any(keyword in text_lower for keyword in self.summary_keywords):
                    summary_rate += 1
            summary_rate /= len(cluster_lines)
            
            # Score: prioritize clusters with money, dates, reasonable length, and low summary content
            score = (money_rate * 0.4 + 
                    date_rate * 0.3 + 
                    min(avg_tokens / 10, 1) * 0.1 + 
                    min(avg_chars / 50, 1) * 0.1 + 
                    (1 - summary_rate) * 0.1)
            
            if score > best_score:
                best_score = score
                best_cluster = label
        
        return best_score, best_cluster
    
    def derive_regex_template(self, lines: List[Line]) -> str:
        """Build a generic regex for the transaction cluster."""
        date = r"(?:(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)|(?:\d{4}[/-]\d{1,2}[/-]\d{1,2})|(?:\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})|(?:[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4})|(?:[A-Za-z]{3,9}\s+\d{1,2}))"
        money = r"[+\-]?\$?\d{1,3}(?:,\d{3})*\.\d{2}"
        
        # Filter lines to only those that look like actual transactions
        filtered_lines = []
        for line in lines:
            text_lower = line.text.lower()
            has_date = bool(self.RE_DATE.search(line.text))
            has_money = bool(self.RE_MONEY.search(line.text))
            is_summary = any(keyword in text_lower for keyword in self.summary_keywords)
            
            if has_date and has_money and len(line.text.strip()) > 10 and not is_summary:
                filtered_lines.append(line)
        
        if not filtered_lines:
            filtered_lines = lines
        
        # Check patterns in the filtered lines
        has_date_rate = np.mean([bool(self.RE_DATE.search(L.text)) for L in filtered_lines])
        multiple_dates = np.mean([len(self.RE_DATE.findall(L.text)) >= 2 for L in filtered_lines])
        
        # Build date part
        if multiple_dates > 0.5:
            date_part = rf"{date}\s+{date}\s+" if has_date_rate > 0.6 else rf"(?:{date}\s+{date}\s+)?"
        else:
            date_part = rf"{date}\s+" if has_date_rate > 0.6 else rf"(?:{date}\s+)?"
        
        # Check for multiple money amounts (amount + balance)
        n_money_counts = [len(self.RE_MONEY.findall(L.text)) for L in filtered_lines]
        two_money_rate = np.mean([c >= 2 for c in n_money_counts]) if n_money_counts else 0
        
        if two_money_rate >= 0.5:
            pattern = rf"^\s*{date_part}(.+?)\s+({money})\s+({money})\s*$"
        else:
            pattern = rf"^\s*{date_part}(.+?)\s+({money})\s*$"
        
        return pattern
    
    def extract_transactions(self, text: str) -> List[Dict[str, Any]]:
        """Extract transactions using K-means clustering and regex pattern detection."""
        transactions = []
        
        try:
            # Use pdfplumber to parse the PDF text more accurately
            # For now, we'll work with the provided text and simulate the PDF parsing
            # In a real implementation, we'd need the actual PDF file
            
            # Split text into lines and create mock Line objects
            text_lines = text.split('\n')
            lines = []
            
            for i, line_text in enumerate(text_lines):
                if line_text.strip():
                    # Create a mock Line object
                    line = Line(
                        tokens=[],  # We don't have token info from plain text
                        y=float(i),  # Use line number as y position
                        text=line_text.strip()
                    )
                    lines.append(line)
            
            if not lines:
                return transactions
            
            # Cluster the lines
            page_width = 612.0  # Standard PDF width
            labels, features = self.cluster_transactions(lines, page_width)
            
            # Find the best cluster for transactions
            score, chosen_cluster = self.evaluate_clusters(np.array(labels), features, lines)
            
            # Get transaction lines from the chosen cluster
            txn_lines = [line for line, label in zip(lines, labels) if label == chosen_cluster]
            
            if not txn_lines:
                return transactions
            
            # Generate regex pattern for this cluster
            pattern = self.derive_regex_template(txn_lines)
            regex = re.compile(pattern)
            
            # Extract transactions using the learned pattern
            for line in txn_lines:
                match = regex.match(line.text)
                if not match:
                    continue
                
                groups = match.groups()
                if len(groups) >= 2:
                    description = groups[0].strip() if groups[0] else ""
                    amount_str = groups[1].strip() if groups[1] else ""
                    balance_str = groups[2].strip() if len(groups) > 2 and groups[2] else None
                    
                    # Extract date separately since it might not be in the regex groups
                    date_match = self.RE_DATE.search(line.text)
                    date_str = date_match.group(0) if date_match else None
                    
                    # Parse amount
                    amount = self.parse_amount(amount_str)
                    if amount is None:
                        continue
                    
                    # Parse date
                    transaction_date = None
                    if date_str:
                        transaction_date = self.parse_date(date_str)
                    
                    # Filter out obvious non-transactions
                    desc_lower = description.lower()
                    if any(keyword in desc_lower for keyword in self.summary_keywords):
                        continue
                    
                    # Create transaction record
                    transaction = {
                        'date': transaction_date,
                        'description': description,
                        'amount': amount,
                        'balance': self.parse_amount(balance_str) if balance_str else None,
                        'raw_text': line.text
                    }
                    
                    transactions.append(transaction)
            
        except Exception as e:
            print(f"Error in generic parser: {e}")
            # Fallback to simple regex extraction
            return self._fallback_extraction(text)
        
        return transactions
    
    def _fallback_extraction(self, text: str) -> List[Dict[str, Any]]:
        """Fallback extraction method using simple patterns."""
        transactions = []
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Look for lines with both dates and money
            has_date = bool(self.RE_DATE.search(line))
            money_matches = self.RE_MONEY.findall(line)
            
            if has_date and money_matches:
                # Skip obvious summary lines
                line_lower = line.lower()
                if any(keyword in line_lower for keyword in self.summary_keywords):
                    continue
                
                date_match = self.RE_DATE.search(line)
                date_str = date_match.group(0) if date_match else None
                
                # Extract description (everything before the last money amount)
                last_money_match = None
                for match in self.RE_MONEY.finditer(line):
                    last_money_match = match
                
                if last_money_match:
                    description = line[:last_money_match.start()].strip()
                    amount_str = last_money_match.group(0)
                    
                    # Clean up description (remove date if it's at the beginning)
                    if date_str and description.startswith(date_str):
                        description = description[len(date_str):].strip()
                    
                    amount = self.parse_amount(amount_str)
                    if amount is not None and description:
                        transaction = {
                            'date': self.parse_date(date_str) if date_str else None,
                            'description': description,
                            'amount': amount,
                            'balance': None,
                            'raw_text': line
                        }
                        transactions.append(transaction)
        
        return transactions
    
    def get_account_info(self, text: str) -> Dict[str, str]:
        """Extract basic account information."""
        info = {
            'bank_name': 'Unknown',
            'account_number': '',
            'statement_date': '',
            'account_type': ''
        }
        
        # Try to extract account number
        account_patterns = [
            r'account\s*(?:number|#)?\s*:?\s*(\d{4,})',
            r'acct\s*(?:number|#)?\s*:?\s*(\d{4,})',
            r'account\s*ending\s*in\s*(\d{4})',
        ]
        
        for pattern in account_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                info['account_number'] = match.group(1)
                break
        
        # Try to extract statement date
        date_patterns = [
            r'statement\s*date\s*:?\s*([^\n]+)',
            r'as\s*of\s*([^\n]+)',
            r'period\s*ending\s*([^\n]+)',
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1).strip()
                parsed_date = self.parse_date(date_str)
                if parsed_date:
                    info['statement_date'] = parsed_date.strftime('%Y-%m-%d')
                break
        
        # Try to detect account type
        if re.search(r'checking|chk', text, re.IGNORECASE):
            info['account_type'] = 'Checking'
        elif re.search(r'savings|sav', text, re.IGNORECASE):
            info['account_type'] = 'Savings'
        elif re.search(r'credit|visa|mastercard|amex', text, re.IGNORECASE):
            info['account_type'] = 'Credit Card'
        
        return info
