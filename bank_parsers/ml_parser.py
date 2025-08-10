"""
ML-Based Bank Statement Parser
=============================
Machine learning parser that uses trained models to extract transactions.
"""

import os
import sys
import pickle
import logging
import warnings
from typing import List, Dict, Any, Optional
from datetime import datetime
import pdfplumber
import pandas as pd
import numpy as np
from dataclasses import dataclass

# Suppress sklearn feature name warnings for ML model predictions
warnings.filterwarnings("ignore", message="X does not have valid feature names", category=UserWarning)

# Add project root to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from . import BankStatementParser

logger = logging.getLogger(__name__)

@dataclass
class RowCandidate:
    """Represents a potential transaction row candidate."""
    text: str
    page_num: int
    line_num: int
    bbox: tuple
    features: Dict[str, Any]
    prediction: Optional[str] = None
    confidence: Optional[float] = None

class MLBankParser(BankStatementParser):
    """ML-based parser using trained models for transaction extraction."""
    
    def __init__(self):
        super().__init__()
        self.bank_name = "ML Parser"
        self.supported_formats = ["pdf"]
        self.model = None
        self.model_path = "ml_models/lightgbm_model_only.pkl"
        
        # Define feature names in the exact order expected by the model
        self.feature_names = [
            'text_length', 'has_date', 'has_amount', 'has_dollar_sign',
            'has_comma', 'has_parentheses', 'num_digits', 'num_words',
            'x0_norm', 'y0_norm', 'x1_norm', 'y1_norm', 'width_norm', 'height_norm',
            'is_left_aligned', 'is_right_aligned', 'is_centered', 'is_top_third', 'is_bottom_third',
            'prev_has_date', 'prev_has_amount', 'next_has_date', 'next_has_amount',
            'relative_position', 'has_balance_keywords', 'has_merchant_indicators',
            'has_banking_keywords', 'has_transaction_keywords', 'bank_type_encoded'
        ]
        
        self._load_model()
    
    def _load_model(self):
        """Load the trained ML model."""
        try:
            # Try to load the complete ML parser first
            complete_model_path = "ml_models/ml_parser_lightgbm.pkl"
            if os.path.exists(complete_model_path):
                try:
                    # Import required classes and make them available for pickle
                    from parallel_ml_trainer import MLTransactionParser, RowCandidate, FeatureExtractor, TrainingExample
                    import __main__
                    __main__.MLTransactionParser = MLTransactionParser
                    __main__.RowCandidate = RowCandidate
                    __main__.FeatureExtractor = FeatureExtractor
                    __main__.TrainingExample = TrainingExample
                    
                    with open(complete_model_path, 'rb') as f:
                        self.ml_parser = pickle.load(f)
                    logger.info(f"✅ Complete ML parser loaded from {complete_model_path}")
                    return
                except ImportError as ie:
                    # If import fails, try loading without explicit imports (pickle may still work)
                    try:
                        with open(complete_model_path, 'rb') as f:
                            self.ml_parser = pickle.load(f)
                        logger.info(f"✅ Complete ML parser loaded from {complete_model_path} (without explicit imports)")
                        return
                    except Exception:
                        # Silently continue to fallback - this is expected in some execution contexts
                        pass
                except Exception as e:
                    # Only log if it's not a common pickle namespace issue
                    if "Can't get attribute" not in str(e):
                        logger.warning(f"⚠️ Could not load complete ML parser: {e}")
            
            # Fallback to basic model
            if os.path.exists(self.model_path):
                with open(self.model_path, 'rb') as f:
                    self.model = pickle.load(f)
                logger.info(f"✅ Basic ML model loaded from {self.model_path}")
            else:
                logger.warning(f"⚠️ ML model not found at {self.model_path}")
                self.model = None
        except Exception as e:
            logger.error(f"❌ Failed to load ML model: {e}")
            self.model = None
    
    def can_parse(self, text: str) -> bool:
        """Check if ML parser can handle the given PDF text."""
        # ML parser can attempt to parse any PDF if either model is loaded
        has_complete_parser = hasattr(self, 'ml_parser') and self.ml_parser
        has_fallback_model = hasattr(self, 'model') and self.model
        
        if not (has_complete_parser or has_fallback_model):
            return False
        
        # Basic checks for PDF content
        if not text or len(text.strip()) < 100:
            return False
        
        # Look for common financial indicators
        financial_indicators = [
            '$', 'balance', 'transaction', 'payment', 'deposit', 'withdrawal',
            'amount', 'date', 'description', 'account', 'statement'
        ]
        
        text_lower = text.lower()
        indicator_count = sum(1 for indicator in financial_indicators if indicator in text_lower)
        
        return indicator_count >= 3
    
    def extract_features_from_line(self, line_text: str, line_bbox: tuple, page_num: int, 
                                 line_num: int, page_text: str, all_candidates: list = None, 
                                 current_index: int = 0) -> Dict[str, Any]:
        """Extract features from a single line for ML prediction - matches training features exactly."""
        import re
        features = {}
        
        # Standard page dimensions (Letter size)
        page_width = 612.0
        page_height = 792.0
        
        # Extract bbox coordinates
        if line_bbox and len(line_bbox) >= 4:
            x0, y0, x1, y1 = line_bbox[:4]
            width = x1 - x0
            height = y1 - y0
        else:
            x0 = y0 = x1 = y1 = width = height = 0
        
        # TEXT FEATURES (from extract_text_features)
        features['looks_like_date'] = float(bool(re.search(r'\d{1,2}/\d{1,2}/\d{2,4}', line_text)))
        features['looks_like_amount'] = float(bool(re.search(r'\$?\d{1,3}(?:,\d{3})*\.\d{2}', line_text)))
        features['has_negative_amount'] = float(bool(re.search(r'-\$?\d+\.\d{2}', line_text)))
        features['has_balance'] = float(bool(re.search(r'balance|bal\b', line_text.lower())))
        features['has_transaction_id'] = float(bool(re.search(r'\b\d{6,}\b', line_text)))
        
        # Text characteristics
        features['text_length'] = len(line_text)
        features['word_count'] = len(line_text.split())
        features['uppercase_ratio'] = sum(1 for c in line_text if c.isupper()) / max(len(line_text), 1)
        features['digit_ratio'] = sum(1 for c in line_text if c.isdigit()) / max(len(line_text), 1)
        features['special_char_ratio'] = sum(1 for c in line_text if not c.isalnum() and not c.isspace()) / max(len(line_text), 1)
        
        # Banking keywords
        banking_keywords = ['payment', 'deposit', 'withdrawal', 'transfer', 'fee', 'interest', 'check']
        features['banking_keyword_count'] = sum(1 for word in banking_keywords if word in line_text.lower())
        
        # Merchant indicators
        merchant_indicators = ['store', 'market', 'shop', 'restaurant', 'gas', 'hotel']
        features['merchant_indicator_count'] = sum(1 for word in merchant_indicators if word in line_text.lower())
        
        # GEOMETRY FEATURES (from extract_geometry_features)
        features['bbox_x0_norm'] = x0 / page_width
        features['bbox_y0_norm'] = y0 / page_height
        features['bbox_width_norm'] = width / page_width
        features['bbox_height_norm'] = height / page_height
        features['bbox_area_norm'] = (width * height) / (page_width * page_height)
        features['bbox_aspect_ratio'] = width / max(height, 1)
        
        # Position indicators
        features['is_left_aligned'] = float(x0 < page_width * 0.2)
        features['is_right_aligned'] = float(x1 > page_width * 0.8)
        features['is_centered'] = float(abs((x0 + x1) / 2 - page_width / 2) < page_width * 0.1)
        features['is_top_third'] = float(y0 < page_height * 0.33)
        features['is_bottom_third'] = float(y1 > page_height * 0.67)
        
        # CONTEXT FEATURES (from extract_context_features)
        if all_candidates and current_index is not None:
            # Previous row features
            if current_index > 0:
                prev_text = all_candidates[current_index - 1].text
                features['prev_has_date'] = float(bool(re.search(r'\d{1,2}/\d{1,2}/\d{2,4}', prev_text)))
                features['prev_has_amount'] = float(bool(re.search(r'\$?\d+\.\d{2}', prev_text)))
            else:
                features['prev_has_date'] = 0.0
                features['prev_has_amount'] = 0.0
            
            # Next row features
            if current_index < len(all_candidates) - 1:
                next_text = all_candidates[current_index + 1].text
                features['next_has_date'] = float(bool(re.search(r'\d{1,2}/\d{1,2}/\d{2,4}', next_text)))
                features['next_has_amount'] = float(bool(re.search(r'\$?\d+\.\d{2}', next_text)))
            else:
                features['next_has_date'] = 0.0
                features['next_has_amount'] = 0.0
            
            # Position in document
            features['relative_position'] = current_index / max(len(all_candidates), 1)
        else:
            # Default values when context not available
            features['prev_has_date'] = 0.0
            features['prev_has_amount'] = 0.0
            features['next_has_date'] = 0.0
            features['next_has_amount'] = 0.0
            features['relative_position'] = 0.5
        
        # BANK-SPECIFIC FEATURES
        # Simple bank type encoding (default to generic)
        features['bank_type_encoded'] = hash("generic") % 100
        
        return features
    
    def _extract_features_from_candidate(self, candidate: RowCandidate, all_candidates: List[RowCandidate]) -> Dict[str, float]:
        """Extract features from a row candidate with context."""
        # Find the index of this candidate in the list
        current_index = None
        for i, c in enumerate(all_candidates):
            if c.text == candidate.text and c.page_num == candidate.page_num and c.line_num == candidate.line_num:
                current_index = i
                break
        
        # Extract features using the existing method
        return self.extract_features_from_line(
            candidate.text, 
            candidate.bbox, 
            candidate.page_num, 
            candidate.line_num, 
            "", # page_text not available in this context
            all_candidates,
            current_index
        )
    
    def _extract_date_patterns(self, text: str) -> Optional[str]:
        """Extract date patterns from text."""
        import re
        date_patterns = [
            r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}',
            r'\d{4}[/-]\d{1,2}[/-]\d{1,2}',
            r'[A-Za-z]{3,9}\s+\d{1,2}',
            r'\d{1,2}\s+[A-Za-z]{3,9}'
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group()
        return None
    
    def _extract_amount(self, text: str) -> Optional[float]:
        """Extract monetary amount from text."""
        import re
        # Look for currency patterns
        amount_patterns = [
            r'\$\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
            r'(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)\s*$',
            r'-\s*\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)'
        ]
        
        for pattern in amount_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    amount_str = match.group(1).replace(',', '')
                    return float(amount_str)
                except (ValueError, IndexError):
                    continue
        return None
    
    def _looks_like_header(self, text: str) -> bool:
        """Check if line looks like a header."""
        header_keywords = ['statement', 'account', 'period', 'balance', 'summary', 'total']
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in header_keywords) and len(text.split()) <= 5
    
    def _looks_like_total(self, text: str) -> bool:
        """Check if line looks like a total/subtotal."""
        total_keywords = ['total', 'subtotal', 'sum', 'balance']
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in total_keywords)
    
    def _looks_like_balance(self, text: str) -> bool:
        """Check if line looks like a balance."""
        balance_keywords = ['balance', 'ending', 'beginning', 'current']
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in balance_keywords)
    
    def extract_transactions(self, text: str) -> List[Dict[str, Any]]:
        """Extract transactions using ML model."""
        # Use the complete ML parser if available
        if hasattr(self, 'ml_parser') and self.ml_parser:
            try:
                # Use the original ML parser's prediction method
                candidates = self._extract_row_candidates_from_text(text)
                if not candidates:
                    return []
                
                # Use the original ML parser's prediction method
                # The original method expects RowCandidates with proper feature extraction
                predictions = self.ml_parser.predict_row_types(candidates)
                
                # Filter for transactions
                transaction_candidates = [
                    candidate for candidate, pred in zip(candidates, predictions)
                    if pred == "transaction"
                ]
                
                # Convert to transaction dictionaries
                transactions = []
                for candidate in transaction_candidates:
                    transaction = self._candidate_to_transaction_dict(candidate)
                    if transaction:
                        transactions.append(transaction)
                
                return transactions
                
            except Exception as e:
                print(f"Error using complete ML parser: {e}")
                # Fall back to basic model if available
        
        # Fallback to basic model
        if not self.model:
            return []
        
        print("🔍 Using fallback basic model...")
        return []
    
    def _extract_row_candidates_from_text(self, text: str) -> List[RowCandidate]:
        """Extract row candidates from plain text (fallback when PDF not available)."""
        # Import the original RowCandidate class
        from parallel_ml_trainer import RowCandidate
        
        candidates = []
        lines = text.split('\n')
        
        # First pass: create candidates without context features
        for line_num, line in enumerate(lines):
            line = line.strip()
            if not line or len(line) < 10:
                continue
            
            candidate = RowCandidate(
                text=line,
                bbox=(0, line_num * 12, 500, (line_num + 1) * 12),
                page_num=0,
                row_index=line_num,
                bank_type="generic",
                features={},  # Will be filled in second pass
                label=None
            )
            candidates.append(candidate)
        
        # Second pass: extract features with context
        for i, candidate in enumerate(candidates):
            features = self.extract_features_from_line(
                candidate.text, candidate.bbox, candidate.page_num, 
                candidate.row_index, text, candidates, i
            )
            candidate.features = features
        
        return candidates
    
    def _predict_row_types(self, candidates: List[RowCandidate]) -> List[str]:
        """Predict row types using the ML model."""
        if not candidates:
            return []
        
        # Feature names in the exact order expected by the trained model (alphabetical)
        feature_names = [
            'bank_type_encoded', 'banking_keyword_count', 'bbox_area_norm', 'bbox_aspect_ratio',
            'bbox_height_norm', 'bbox_width_norm', 'bbox_x0_norm', 'bbox_y0_norm',
            'digit_ratio', 'has_balance', 'has_negative_amount', 'has_transaction_id',
            'is_bottom_third', 'is_centered', 'is_left_aligned', 'is_right_aligned',
            'is_top_third', 'looks_like_amount', 'looks_like_date', 'merchant_indicator_count',
            'next_has_amount', 'next_has_date', 'prev_has_amount', 'prev_has_date',
            'relative_position', 'special_char_ratio', 'text_length', 'uppercase_ratio',
            'word_count'
        ]
        
        # Convert features to matrix
        feature_matrix = []
        for candidate in candidates:
            row = []
            for feature_name in feature_names:
                value = candidate.features.get(feature_name, 0.0)
                # Ensure all values are float for consistency
                if isinstance(value, bool):
                    value = float(value)
                elif isinstance(value, int):
                    value = float(value)
                row.append(value)
            feature_matrix.append(row)
        
        # Make predictions
        try:
            X = np.array(feature_matrix)
            predictions = self.model.predict(X)
            return predictions.tolist()
        except Exception as e:
            logger.error(f"❌ ML prediction failed: {e}")
            return ['junk'] * len(candidates)
    
    def _convert_predictions_to_transactions(self, candidates: List[RowCandidate], 
                                           predictions: List[str]) -> List[Dict[str, Any]]:
        """Convert ML predictions to transaction dictionaries."""
        transactions = []
        
        for candidate, prediction in zip(candidates, predictions):
            if prediction == 'transaction':
                # Extract transaction details
                date = self._extract_date_patterns(candidate.text)
                amount = self._extract_amount(candidate.text)
                
                # Parse date
                parsed_date = None
                if date:
                    try:
                        parsed_date = self._parse_date_string(date)
                    except:
                        parsed_date = None
                
                # Create transaction
                transaction = {
                    'date': parsed_date,
                    'description': self._clean_description(candidate.text),
                    'amount': amount,
                    'balance': None,
                    'raw_text': candidate.text,
                    'parser': 'ML Parser',
                    'confidence': getattr(candidate, 'confidence', 0.0)
                }
                transactions.append(transaction)
        
        return transactions
    
    def _parse_date_string(self, date_str: str) -> Optional[datetime]:
        """Parse various date string formats."""
        import re
        from datetime import datetime
        
        date_formats = [
            '%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d', '%Y/%m/%d',
            '%m/%d/%y', '%m-%d-%y', '%y-%m-%d', '%y/%m/%d',
            '%B %d', '%b %d', '%d %B', '%d %b'
        ]
        
        # Clean the date string
        date_str = re.sub(r'[^\w\s/-]', '', date_str).strip()
        
        for fmt in date_formats:
            try:
                parsed = datetime.strptime(date_str, fmt)
                # If year is not specified, assume current year
                if parsed.year == 1900:
                    parsed = parsed.replace(year=datetime.now().year)
                return parsed
            except ValueError:
                continue
        
        return None
    
    def _clean_description(self, text: str) -> str:
        """Clean transaction description."""
        # Remove extra whitespace and common artifacts
        import re
        cleaned = re.sub(r'\s+', ' ', text).strip()
        
        # Remove leading date patterns
        cleaned = re.sub(r'^\d{1,2}[/-]\d{1,2}[/-]?\d{0,4}\s*', '', cleaned)
        
        # Remove trailing amounts
        cleaned = re.sub(r'\s*\$?\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*$', '', cleaned)
        
        return cleaned.strip()
    
    def _extract_date_from_text(self, text: str) -> Optional[datetime]:
        """Extract date from text using common patterns."""
        import re
        from datetime import datetime
        
        date_patterns = [
            r'(\d{1,2})/(\d{1,2})/(\d{2,4})',
            r'(\d{1,2})-(\d{1,2})-(\d{2,4})',
            r'(\d{4})/(\d{1,2})/(\d{1,2})',
            r'(\d{4})-(\d{1,2})-(\d{1,2})'
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    groups = match.groups()
                    if len(groups) == 3:
                        if len(groups[0]) == 4:  # Year first
                            year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                        else:  # Month first
                            month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                            if year < 100:  # 2-digit year
                                year += 2000 if year < 50 else 1900
                        
                        return datetime(year, month, day)
                except (ValueError, TypeError):
                    continue
        
        return None
    
    def _extract_amount_from_text(self, text: str) -> Optional[float]:
        """Extract amount from text using common patterns."""
        import re
        
        amount_patterns = [
            r'\$?(\d{1,3}(?:,\d{3})*\.\d{2})',
            r'\$?(\d+\.\d{2})',
            r'(\d{1,3}(?:,\d{3})*\.\d{2})',
            r'(\d+\.\d{2})'
        ]
        
        for pattern in amount_patterns:
            matches = re.findall(pattern, text)
            if matches:
                try:
                    # Take the last match (often the amount)
                    amount_str = matches[-1].replace(',', '')
                    amount = float(amount_str)
                    
                    # Check if it should be negative (common indicators)
                    if any(indicator in text.lower() for indicator in ['-', 'debit', 'withdrawal', 'fee', 'charge']):
                        amount = -abs(amount)
                    
                    return amount
                except (ValueError, TypeError):
                    continue
        
        return None
    
    def _candidate_to_transaction_dict(self, candidate: RowCandidate) -> Optional[Dict[str, Any]]:
        """Convert a row candidate to a transaction dictionary."""
        try:
            # Extract date, description, and amount from the candidate text
            date = self._extract_date_from_text(candidate.text)
            amount = self._extract_amount_from_text(candidate.text)
            description = self._clean_description(candidate.text)
            
            # Only return if we found at least an amount
            if amount is not None:
                return {
                    'date': date.strftime('%Y-%m-%d') if date else 'Unknown',
                    'description': description,
                    'amount': amount,
                    'raw_text': candidate.text
                }
        except Exception as e:
            print(f"Error converting candidate to transaction: {e}")
        
        return None
    
    def get_account_info(self, text: str) -> Dict[str, str]:
        """Extract account information from PDF text."""
        # Basic account info extraction
        account_info = {
            'account_number': 'Unknown',
            'account_type': 'Unknown',
            'statement_date': 'Unknown',
            'bank_name': 'ML Detected'
        }
        
        # Try to extract account number patterns
        import re
        account_patterns = [
            r'account\s*(?:number|#)?\s*:?\s*([x\d\-\s]{8,})',
            r'acct\s*(?:number|#)?\s*:?\s*([x\d\-\s]{8,})'
        ]
        
        text_lower = text.lower()
        for pattern in account_patterns:
            match = re.search(pattern, text_lower)
            if match:
                account_info['account_number'] = match.group(1).strip()
                break
        
        return account_info
