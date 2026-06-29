"""
Transaction Validation Pipeline
--------------------------------
Validates extracted transactions with:
- Required fields checking
- Amount/date sanity checks
- Duplicate detection
- Quality scoring
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum
import re


class ValidationError(Enum):
    """Types of validation errors."""
    MISSING_DATE = "missing_date"
    INVALID_DATE = "invalid_date"
    FUTURE_DATE = "future_date"
    ANCIENT_DATE = "ancient_date"
    MISSING_DESCRIPTION = "missing_description"
    SHORT_DESCRIPTION = "short_description"
    MISSING_AMOUNT = "missing_amount"
    ZERO_AMOUNT = "zero_amount"
    HUGE_AMOUNT = "huge_amount"
    DUPLICATE = "duplicate"
    UNLIKELY_COMBINATION = "unlikely_combination"


@dataclass
class ValidationResult:
    """Result of transaction validation."""
    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    quality_score: float = 0.0  # 0-100
    
    def has_critical_errors(self) -> bool:
        """Check if there are critical errors that make transaction unusable."""
        critical = [
            ValidationError.MISSING_DATE,
            ValidationError.MISSING_DESCRIPTION,
            ValidationError.MISSING_AMOUNT,
            ValidationError.HUGE_AMOUNT,
        ]
        return any(e in self.errors for e in critical)


@dataclass
class Transaction:
    """Standardized transaction structure."""
    date: Optional[date]
    description: str
    amount: Optional[float]
    category: Optional[str] = None
    source: str = ""  # Which parser/AI extracted this
    page: int = 0
    raw_data: Dict[str, Any] = field(default_factory=dict)


class TransactionValidator:
    """Validates transactions and provides quality scoring."""
    
    # Sanity check thresholds
    MAX_REASONABLE_AMOUNT = 1_000_000  # $1M - flag anything larger
    MIN_REASONABLE_AMOUNT = 0.01  # 1 cent
    MAX_FUTURE_DAYS = 30  # Allow up to 30 days in future
    MAX_PAST_YEARS = 5  # Reject dates older than 5 years
    MIN_DESCRIPTION_LENGTH = 3  # At least 3 characters
    
    def __init__(self, statement_date: Optional[date] = None):
        """
        Initialize validator.
        
        Args:
            statement_date: Date of the statement (for context-aware validation)
        """
        self.statement_date = statement_date or date.today()
        self._seen_transactions: Set[str] = set()  # For duplicate detection
    
    def validate(self, txn: Transaction) -> ValidationResult:
        """
        Run full validation on a transaction.
        
        Args:
            txn: Transaction to validate
            
        Returns:
            ValidationResult with errors, warnings, and quality score
        """
        errors = []
        warnings = []
        
        # Validate date
        date_valid, date_errors, date_warnings = self._validate_date(txn.date)
        errors.extend(date_errors)
        warnings.extend(date_warnings)
        
        # Validate description
        desc_valid, desc_errors, desc_warnings = self._validate_description(txn.description)
        errors.extend(desc_errors)
        warnings.extend(desc_warnings)
        
        # Validate amount
        amt_valid, amt_errors, amt_warnings = self._validate_amount(txn.amount)
        errors.extend(amt_errors)
        warnings.extend(amt_warnings)
        
        # Check for duplicates
        if self._is_duplicate(txn):
            errors.append(ValidationError.DUPLICATE)
        
        # Calculate quality score
        quality_score = self._calculate_quality_score(txn, errors, warnings)
        
        # Determine overall validity
        is_valid = not any(e in [
            ValidationError.MISSING_DATE,
            ValidationError.MISSING_DESCRIPTION,
            ValidationError.MISSING_AMOUNT,
            ValidationError.HUGE_AMOUNT,
        ] for e in errors)
        
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            quality_score=quality_score
        )
    
    def _validate_date(self, txn_date: Optional[date]) -> Tuple[bool, List[ValidationError], List[str]]:
        """Validate transaction date."""
        errors = []
        warnings = []
        
        if txn_date is None:
            errors.append(ValidationError.MISSING_DATE)
            return False, errors, warnings
        
        today = date.today()
        
        # Check for future dates
        if txn_date > today + timedelta(days=self.MAX_FUTURE_DAYS):
            errors.append(ValidationError.FUTURE_DATE)
            warnings.append(f"Date {txn_date} is in the future")
        
        # Check for ancient dates
        if txn_date < today - timedelta(days=365 * self.MAX_PAST_YEARS):
            errors.append(ValidationError.ANCIENT_DATE)
            warnings.append(f"Date {txn_date} is more than {self.MAX_PAST_YEARS} years old")
        
        return len(errors) == 0, errors, warnings
    
    def _validate_description(self, description: Optional[str]) -> Tuple[bool, List[ValidationError], List[str]]:
        """Validate transaction description."""
        errors = []
        warnings = []
        
        if not description:
            errors.append(ValidationError.MISSING_DESCRIPTION)
            return False, errors, warnings
        
        desc = description.strip()
        
        # Check minimum length
        if len(desc) < self.MIN_DESCRIPTION_LENGTH:
            errors.append(ValidationError.SHORT_DESCRIPTION)
            warnings.append(f"Description '{desc}' is very short")
        
        # Check for suspicious patterns
        suspicious = ['test', 'xxxx', 'null', 'undefined', 'nan', 'none']
        if any(s in desc.lower() for s in suspicious):
            warnings.append(f"Description contains suspicious text: '{desc}'")
        
        return len(errors) == 0, errors, warnings
    
    def _validate_amount(self, amount: Optional[float]) -> Tuple[bool, List[ValidationError], List[str]]:
        """Validate transaction amount."""
        errors = []
        warnings = []
        
        if amount is None:
            errors.append(ValidationError.MISSING_AMOUNT)
            return False, errors, warnings
        
        # Check for zero
        if abs(amount) < self.MIN_REASONABLE_AMOUNT:
            errors.append(ValidationError.ZERO_AMOUNT)
            warnings.append(f"Amount ${amount} is effectively zero")
        
        # Check for huge amounts
        if abs(amount) > self.MAX_REASONABLE_AMOUNT:
            errors.append(ValidationError.HUGE_AMOUNT)
            warnings.append(f"Amount ${amount:,.2f} exceeds reasonable threshold")
        
        return len(errors) == 0, errors, warnings
    
    def _is_duplicate(self, txn: Transaction) -> bool:
        """
        Check if transaction is a duplicate of one we've seen.
        
        Uses fuzzy matching on description + amount + approximate date.
        """
        # Create fingerprint
        desc_normalized = re.sub(r'[^\w]', '', txn.description.lower())
        amount_key = f"{abs(txn.amount):.2f}" if txn.amount else "0.00"
        
        # Date tolerance: within 7 days
        if txn.date:
            date_key = txn.date.strftime("%Y-%m")
        else:
            date_key = "unknown"
        
        fingerprint = f"{desc_normalized}_{amount_key}_{date_key}"
        
        if fingerprint in self._seen_transactions:
            return True
        
        # Add to seen set
        self._seen_transactions.add(fingerprint)
        return False
    
    def _calculate_quality_score(
        self,
        txn: Transaction,
        errors: List[ValidationError],
        warnings: List[str]
    ) -> float:
        """
        Calculate overall quality score (0-100).
        
        Based on:
        - Completeness of fields (40 points)
        - Date reasonableness (20 points)
        - Description quality (20 points)
        - Amount reasonableness (20 points)
        """
        score = 0.0
        
        # Completeness (40 points)
        if txn.date is not None:
            score += 15
        if txn.description and len(txn.description.strip()) >= 5:
            score += 15
        if txn.amount is not None:
            score += 10
        
        # Date quality (20 points)
        if txn.date:
            today = date.today()
            days_diff = abs((txn.date - today).days)
            if days_diff < 365:
                score += 20  # Recent transaction
            elif days_diff < 365 * 2:
                score += 10  # Within 2 years
            else:
                score += 5   # Older but not ancient
        
        # Description quality (20 points)
        if txn.description:
            desc_len = len(txn.description.strip())
            if desc_len >= 20:
                score += 20
            elif desc_len >= 10:
                score += 15
            elif desc_len >= 5:
                score += 10
        
        # Amount quality (20 points)
        if txn.amount:
            if 0.01 <= abs(txn.amount) <= 10000:
                score += 20  # Normal range
            elif abs(txn.amount) <= 100000:
                score += 10  # Large but reasonable
            else:
                score += 5   # Very large
        
        # Penalties for errors and warnings
        score -= len(errors) * 10
        score -= len(warnings) * 5
        
        return max(0.0, min(100.0, score))


class ValidationPipeline:
    """Pipeline for batch transaction validation."""
    
    def __init__(self, min_quality_score: float = 30.0):
        """
        Initialize validation pipeline.
        
        Args:
            min_quality_score: Minimum quality score to accept transaction (0-100)
        """
        self.min_quality_score = min_quality_score
        self.validator: Optional[TransactionValidator] = None
    
    def validate_batch(
        self,
        transactions: List[Transaction],
        statement_date: Optional[date] = None
    ) -> Tuple[List[Transaction], List[Dict[str, Any]]]:
        """
        Validate a batch of transactions.
        
        Args:
            transactions: List of transactions to validate
            statement_date: Date of the statement for context
            
        Returns:
            Tuple of (valid_transactions, rejected_with_reasons)
        """
        self.validator = TransactionValidator(statement_date)
        
        valid = []
        rejected = []
        
        for txn in transactions:
            result = self.validator.validate(txn)
            
            if result.is_valid and result.quality_score >= self.min_quality_score:
                valid.append(txn)
            else:
                rejected.append({
                    "transaction": txn,
                    "validation": result,
                    "reasons": [e.value for e in result.errors] + result.warnings
                })
        
        return valid, rejected
    
    def validate_extraction_result(
        self,
        raw_transactions: List[Dict[str, Any]],
        source: str,
        statement_date: Optional[date] = None
    ) -> List[Transaction]:
        """
        Convert and validate raw extraction results.
        
        Args:
            raw_transactions: Raw dicts from parser/AI
            source: Name of extraction method
            statement_date: Statement date for context
            
        Returns:
            List of validated Transaction objects
        """
        # Convert to Transaction objects
        transactions = []
        for raw in raw_transactions:
            txn = Transaction(
                date=self._parse_date(raw.get('date')),
                description=raw.get('description', ''),
                amount=self._parse_amount(raw.get('amount')),
                category=raw.get('category'),
                source=source,
                page=raw.get('page', 0),
                raw_data=raw
            )
            transactions.append(txn)
        
        # Validate batch
        valid, rejected = self.validate_batch(transactions, statement_date)
        
        # Log rejected if any
        if rejected:
            print(f"⚠️ Rejected {len(rejected)} invalid transactions:")
            for r in rejected[:5]:  # Show first 5
                desc = r["transaction"].description[:30]
                reasons = r["reasons"]
                print(f"   - '{desc}...': {', '.join(reasons)}")
        
        return valid
    
    def _parse_date(self, date_val: Any) -> Optional[date]:
        """Parse date from various formats.

        NOTE: datetime.datetime is a subclass of datetime.date, so the
        isinstance check order matters - datetime must be tested first or it
        will pass through unchanged and break later date comparisons.
        """
        if date_val is None:
            return None

        # datetime is a subclass of date, so check it FIRST.
        if isinstance(date_val, datetime):
            return date_val.date()

        if isinstance(date_val, date):
            return date_val

        # Try string parsing
        if isinstance(date_val, str):
            formats = [
                '%Y-%m-%d',
                '%m/%d/%Y',
                '%m/%d/%y',
                '%d/%m/%Y',
                '%m-%d-%Y',
                '%Y/%m/%d',
            ]
            
            for fmt in formats:
                try:
                    return datetime.strptime(date_val.strip(), fmt).date()
                except ValueError:
                    continue
        
        return None
    
    def _parse_amount(self, amount_val: Any) -> Optional[float]:
        """Parse amount from various formats."""
        if amount_val is None:
            return None
        
        if isinstance(amount_val, (int, float)):
            return float(amount_val)
        
        if isinstance(amount_val, str):
            # Clean string
            cleaned = amount_val.replace('$', '').replace(',', '').strip()
            
            # Handle parentheses for negative
            if cleaned.startswith('(') and cleaned.endswith(')'):
                cleaned = '-' + cleaned[1:-1]
            
            try:
                return float(cleaned)
            except ValueError:
                pass
        
        return None


# Convenience functions
def validate_single_transaction(
    description: str,
    amount: Optional[float],
    txn_date: Optional[date] = None,
    statement_date: Optional[date] = None
) -> ValidationResult:
    """
    Quick validation of a single transaction.
    
    Args:
        description: Transaction description
        amount: Transaction amount
        txn_date: Transaction date
        statement_date: Statement date for context
        
    Returns:
        ValidationResult
    """
    txn = Transaction(
        date=txn_date,
        description=description,
        amount=amount
    )
    
    validator = TransactionValidator(statement_date)
    return validator.validate(txn)


def find_duplicates(transactions: List[Transaction]) -> List[Tuple[Transaction, Transaction]]:
    """
    Find duplicate transaction pairs.
    
    Args:
        transactions: List of transactions
        
    Returns:
        List of duplicate pairs
    """
    seen: Dict[str, Transaction] = {}
    duplicates = []
    
    for txn in transactions:
        # Create fingerprint
        desc_normalized = re.sub(r'[^\w]', '', txn.description.lower())
        amount_key = f"{abs(txn.amount):.2f}" if txn.amount else "0.00"
        date_key = txn.date.strftime("%Y-%m") if txn.date else "unknown"
        fingerprint = f"{desc_normalized}_{amount_key}_{date_key}"
        
        if fingerprint in seen:
            duplicates.append((seen[fingerprint], txn))
        else:
            seen[fingerprint] = txn
    
    return duplicates
