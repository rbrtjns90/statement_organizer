"""
Generic Bank Statement Parser using K-means clustering and regex pattern detection
----------------------------------------------------------------------------------
This parser uses machine learning to automatically detect transaction patterns
in bank statements without requiring bank-specific rules.

"""

import re
import math
import os
import json
import time
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from sklearn.cluster import KMeans, DBSCAN
import pdfplumber

try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    print("Warning: rapidfuzz not available, vendor normalization disabled")

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


class WeakSupervisionLabeler:
    """Weak supervision labeling functions for transaction classification."""
    
    def __init__(self):
        self.openai_enabled = self._check_openai_enabled()
        self.openai_client = None
        
        # Initialize OpenAI client if enabled
        if self.openai_enabled:
            self.openai_client = self._init_openai_client()
        
        # Regex patterns for labeling functions
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
        
        # Define labeling functions
        self.labeling_functions = [
            self.lf_has_date_and_amount,
            self.lf_right_aligned_amount,
            self.lf_starts_with_card_number,
            self.lf_contains_merchant_indicators,
            self.lf_reasonable_length,
            self.lf_not_summary_line
        ]
        
        # Add ChatGPT labeling function if OpenAI is enabled
        if self.openai_enabled and self.openai_client:
            self.labeling_functions.append(self.lf_chatgpt_classifier)
    
    def _check_openai_enabled(self):
        """Check if OpenAI is enabled via openai.txt file."""
        try:
            with open('openai.txt', 'r') as f:
                content = f.read().strip().lower()
                return content in ['true', '1', 'enabled', 'yes']
        except FileNotFoundError:
            return False
    
    def _init_openai_client(self):
        """Initialize OpenAI client if enabled."""
        try:
            import openai
            
            # Get API key from environment or openai_key.txt
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                try:
                    with open('openai_key.txt', 'r') as f:
                        api_key = f.read().strip()
                except FileNotFoundError:
                    print("Warning: OpenAI enabled but no API key found")
                    return None
            
            return openai.OpenAI(api_key=api_key)
        except ImportError:
            print("Warning: OpenAI library not installed")
            return None
    
    def lf_has_date_and_amount(self, line):
        """LF: Line has both date and monetary amount."""
        has_date = bool(self.RE_DATE.search(line.text))
        has_money = bool(self.RE_MONEY.search(line.text))
        return 1 if (has_date and has_money) else 0
    
    def lf_right_aligned_amount(self, line):
        """LF: Line has right-aligned monetary amount."""
        money_matches = list(self.RE_MONEY.finditer(line.text))
        if not money_matches:
            return 0
        
        # Check if amount appears near end of line
        last_match = money_matches[-1]
        return 1 if (len(line.text) - last_match.end()) < 10 else 0
    
    def lf_starts_with_card_number(self, line):
        """LF: Line starts with partial card number."""
        card_pattern = r'^\s*\*+\d{4}'
        return 1 if re.match(card_pattern, line.text) else 0
    
    def lf_contains_merchant_indicators(self, line):
        """LF: Line contains merchant-like terms."""
        merchant_terms = ['purchase', 'payment', 'pos', 'atm', 'withdrawal']
        text_lower = line.text.lower()
        return 1 if any(term in text_lower for term in merchant_terms) else 0
    
    def lf_reasonable_length(self, line):
        """LF: Line has reasonable length for transaction."""
        return 1 if 20 <= len(line.text) <= 200 else 0
    
    def lf_not_summary_line(self, line):
        """LF: Line is not a summary/total line."""
        summary_terms = ['total', 'balance', 'summary', 'subtotal', 'previous balance', 
                        'new balance', 'minimum payment', 'payment due', 'credit limit']
        text_lower = line.text.lower()
        return 0 if any(term in text_lower for term in summary_terms) else 1
    
    def lf_chatgpt_classifier(self, line):
        """LF: Use ChatGPT to classify if line is a transaction."""
        if not self.openai_enabled or not self.openai_client:
            return 0  # Fallback if OpenAI not available
        
        try:
            prompt = f"""
            Analyze this line from a bank statement and determine if it represents a financial transaction.
            
            Line: "{line.text}"
            
            A transaction typically:
            - Has a date and monetary amount
            - Describes a purchase, payment, deposit, or withdrawal
            - Is NOT a header, footer, summary, or account information line
            
            Respond with only "1" if this is a transaction, or "0" if it is not.
            """
            
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1,
                temperature=0
            )
            
            result = response.choices[0].message.content.strip()
            return 1 if result == "1" else 0
            
        except Exception as e:
            print(f"ChatGPT labeling function failed: {e}")
            return 0  # Fallback on error
    
    def generate_weak_labels(self, lines):
        """Generate weak labels using labeling functions."""
        label_matrix = []
        
        for line in lines:
            line_labels = []
            for lf in self.labeling_functions:
                line_labels.append(lf(line))
            label_matrix.append(line_labels)
        
        # Simple majority voting (could be replaced with Snorkel)
        final_labels = []
        for line_labels in label_matrix:
            vote = sum(line_labels) / len(line_labels)
            final_labels.append(1 if vote > 0.5 else 0)
        
        return final_labels


class WeightManager:
    """Manages and persists weights for the generic parser."""
    
    def __init__(self, weights_file="parser_weights.json"):
        self.weights_file = weights_file
        self.weights = self.load_weights()
        self.performance_history = []
    
    def load_weights(self):
        """Load weights from file or use defaults."""
        try:
            with open(self.weights_file, 'r') as f:
                data = json.load(f)
                # Ensure all required keys exist
                weights = self.get_default_weights()
                weights.update(data.get('weights', {}))
                self.performance_history = data.get('performance_history', [])
                return weights
        except (FileNotFoundError, json.JSONDecodeError):
            return self.get_default_weights()
    
    def get_default_weights(self):
        """Get default weight configuration."""
        return {
            'traditional_features': {
                'money_rate': 0.3,
                'date_rate': 0.2,
                'tokens': 0.1,
                'chars': 0.1,
                'summary': 0.1
            },
            'weak_supervision': {
                'ai_enabled_traditional': 0.4,
                'ai_enabled_weak': 0.6,
                'rule_based_traditional': 0.6,
                'rule_based_weak': 0.4
            },
            'line_filtering': {
                'confidence_threshold': 0.3,
                'min_lines_ratio': 0.2
            },
            'clustering': {
                'k_clusters': 5,
                'dbscan_eps': 3.0,
                'dbscan_min_samples': 2
            },
            'continuation_lines': {
                'indent_threshold': 20,
                'y_diff_threshold': 15,
                'min_text_length': 5
            }
        }
    
    def save_weights(self):
        """Save current weights and performance history to file using atomic write."""
        try:
            import os
            import tempfile
            
            # Prepare all data first
            data = {
                'weights': self.weights,
                'performance_history': self.performance_history,
                'last_updated': datetime.now().isoformat()
            }
            
            # Get directory of the weights file
            weights_dir = os.path.dirname(os.path.abspath(self.weights_file))
            if not weights_dir:
                weights_dir = '.'
            
            # Create temporary file in the same directory
            with tempfile.NamedTemporaryFile(mode='w', dir=weights_dir, delete=False, suffix='.tmp') as temp_file:
                json.dump(data, temp_file, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_filename = temp_file.name
            
            # Atomically move temp file to final location
            os.replace(temp_filename, self.weights_file)
            
        except Exception as e:
            print(f"Warning: Could not save weights: {e}")
            # Clean up temp file if it exists
            try:
                if 'temp_filename' in locals() and os.path.exists(temp_filename):
                    os.remove(temp_filename)
            except:
                pass
    
    def record_performance(self, filename, metrics):
        """Record performance metrics for weight adaptation."""
        performance_record = {
            'filename': filename,
            'timestamp': datetime.now().isoformat(),
            'metrics': metrics
        }
        self.performance_history.append(performance_record)
        
        # Keep only last 100 records to prevent file bloat
        if len(self.performance_history) > 100:
            self.performance_history = self.performance_history[-100:]
    
    def adapt_weights(self, success_rate_threshold=0.5):
        """Adapt weights based on performance history."""
        if len(self.performance_history) < 10:
            return  # Need sufficient data for adaptation
        
        recent_performance = self.performance_history[-10:]
        avg_success_rate = sum(p['metrics'].get('success_rate', 0) 
                              for p in recent_performance) / len(recent_performance)
        
        # If performance is below threshold, adjust weights
        if avg_success_rate < success_rate_threshold:
            self._adjust_weights_for_poor_performance()
        elif avg_success_rate > 0.8:
            self._fine_tune_weights_for_good_performance()
    
    def _adjust_weights_for_poor_performance(self):
        """Adjust weights when performance is poor."""
        # Increase weak supervision weight if available
        ws = self.weights['weak_supervision']
        if ws['ai_enabled_weak'] < 0.8:
            ws['ai_enabled_weak'] = min(0.8, ws['ai_enabled_weak'] + 0.1)
            ws['ai_enabled_traditional'] = 1.0 - ws['ai_enabled_weak']
        
        # Lower confidence threshold to be more inclusive
        self.weights['line_filtering']['confidence_threshold'] = max(
            0.1, self.weights['line_filtering']['confidence_threshold'] - 0.05
        )
        
        # Increase money and date importance in traditional features
        tf = self.weights['traditional_features']
        tf['money_rate'] = min(0.4, tf['money_rate'] + 0.05)
        tf['date_rate'] = min(0.3, tf['date_rate'] + 0.05)
    
    def _fine_tune_weights_for_good_performance(self):
        """Fine-tune weights when performance is good."""
        # Slightly increase confidence threshold for better precision
        self.weights['line_filtering']['confidence_threshold'] = min(
            0.5, self.weights['line_filtering']['confidence_threshold'] + 0.02
        )
    
    def get_weight(self, category, key):
        """Get a specific weight value."""
        return self.weights.get(category, {}).get(key, 0)
    
    def set_weight(self, category, key, value):
        """Set a specific weight value."""
        if category not in self.weights:
            self.weights[category] = {}
        self.weights[category][key] = value
    
    def reset_to_defaults(self):
        """Reset all weights to default values."""
        self.weights = self.get_default_weights()
        self.performance_history = []


class VendorNormalizer:
    """Vendor name normalization using fuzzy matching."""
    
    def __init__(self, cache_file="vendor_cache.json"):
        self.cache_file = cache_file
        self.cache = self.load_cache()
        self.common_vendors = [
            "Amazon", "Walmart", "Target", "Starbucks", "McDonald's",
            "Shell", "Exxon", "BP", "Chevron", "Home Depot", "Lowe's",
            "Costco", "Best Buy", "Apple", "Google", "Microsoft",
            "Netflix", "Spotify", "Uber", "Lyft", "PayPal"
        ]
    
    def load_cache(self):
        """Load cached vendor mappings."""
        try:
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def save_cache(self):
        """Save vendor mappings to cache using atomic write."""
        try:
            import tempfile
            import os
            
            # Get directory of the cache file
            cache_dir = os.path.dirname(os.path.abspath(self.cache_file))
            if not cache_dir:
                cache_dir = '.'
            
            # Create temporary file in the same directory
            with tempfile.NamedTemporaryFile(mode='w', dir=cache_dir, delete=False, suffix='.tmp') as temp_file:
                json.dump(self.cache, temp_file, indent=2)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_filename = temp_file.name
            
            # Atomically move temp file to final location
            os.replace(temp_filename, self.cache_file)
            
        except Exception as e:
            print(f"Warning: Could not save vendor cache: {e}")
            # Clean up temp file if it exists
            try:
                if 'temp_filename' in locals() and os.path.exists(temp_filename):
                    os.remove(temp_filename)
            except:
                pass
    
    def normalize_vendor(self, raw_vendor, threshold=80):
        """Normalize vendor name using fuzzy matching."""
        if not RAPIDFUZZ_AVAILABLE:
            return self.clean_vendor_name(raw_vendor)
        
        raw_clean = raw_vendor.strip().upper()
        
        # Check cache first
        if raw_clean in self.cache:
            return self.cache[raw_clean]
        
        # Find best match among common vendors
        try:
            best_match, score = process.extractOne(
                raw_clean, 
                [v.upper() for v in self.common_vendors],
                scorer=fuzz.partial_ratio
            )
            
            if score >= threshold:
                # Map back to original case
                normalized = next(v for v in self.common_vendors 
                                if v.upper() == best_match)
                self.cache[raw_clean] = normalized
                return normalized
        except Exception:
            pass
        
        # If no good match, clean up the original
        cleaned = self.clean_vendor_name(raw_vendor)
        self.cache[raw_clean] = cleaned
        return cleaned
    
    def clean_vendor_name(self, vendor):
        """Clean up vendor name (remove common suffixes, etc.)."""
        # Remove common payment processor codes
        vendor = re.sub(r'\s+\d{10,}.*$', '', vendor)  # Remove long numbers
        vendor = re.sub(r'\s+[A-Z]{2}\s*$', '', vendor)  # Remove state codes
        vendor = re.sub(r'\s+\d{5}\s*$', '', vendor)    # Remove ZIP codes
        vendor = re.sub(r'\*+', '', vendor)             # Remove asterisks
        
        # Title case
        return vendor.strip().title()


class PerformanceOptimizer:
    """Monitors and optimizes parser performance based on historical data."""
    
    def __init__(self):
        self.method_times = defaultdict(list)
        self.success_rates = defaultdict(list)
        self.text_characteristics = defaultdict(list)
        self.lock = threading.Lock()
    
    def record_performance(self, method: str, text_length: int, execution_time: float, success: bool, transaction_count: int):
        """Record performance metrics for a parsing method."""
        with self.lock:
            self.method_times[method].append(execution_time)
            self.success_rates[method].append(success)
            self.text_characteristics[method].append({
                'text_length': text_length,
                'transaction_count': transaction_count,
                'success': success,
                'time': execution_time
            })
    
    def get_optimal_strategy(self, text_length: int) -> str:
        """Choose best extraction method based on historical performance."""
        if text_length < 1000:
            return "pattern_based"
        elif text_length < 3000:
            return "light_clustering"
        elif text_length < 8000:
            return "adaptive_clustering"
        else:
            return "full_clustering"
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics for all methods."""
        stats = {}
        with self.lock:
            for method in self.method_times:
                times = self.method_times[method]
                successes = self.success_rates[method]
                if times:
                    stats[method] = {
                        'avg_time': np.mean(times),
                        'success_rate': np.mean(successes),
                        'total_runs': len(times)
                    }
        return stats


class RegexPatternCollector:
    """Collects and manages regex patterns from successful parses."""
    
    def __init__(self, patterns_file="regex_patterns.txt"):
        self.patterns_file = patterns_file
        self.patterns = self.load_patterns()
        self._compiled_patterns = {}  # Cache for compiled regex patterns
        self._pattern_features = {}   # Cache for pattern characteristics
    
    def load_patterns(self):
        """Load existing patterns from file."""
        try:
            patterns = []
            if os.path.exists(self.patterns_file):
                with open(self.patterns_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            # Parse pattern entry: filename|pattern|success_count|metadata
                            # Split only on the first 3 pipes to handle regex patterns with | characters
                            parts = line.split('|', 3)  # Limit splits to avoid breaking regex patterns
                            if len(parts) >= 2:
                                patterns.append({
                                    'filename': parts[0],
                                    'pattern': parts[1],
                                    'success_count': int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1,
                                    'metadata': parts[3] if len(parts) > 3 else ''
                                })
            return patterns
        except Exception as e:
            print(f"Warning: Could not load patterns: {e}")
            return []
    
    def save_patterns(self):
        """Save patterns to file using atomic write."""
        try:
            import tempfile
            import os
            
            # Get directory of the patterns file
            patterns_dir = os.path.dirname(os.path.abspath(self.patterns_file))
            if not patterns_dir:
                patterns_dir = '.'
            
            # Create temporary file in the same directory
            with tempfile.NamedTemporaryFile(mode='w', dir=patterns_dir, delete=False, suffix='.tmp') as temp_file:
                # Write header
                temp_file.write("# Regex Patterns Generated from Bank Statements\n")
                temp_file.write("# Format: filename|pattern|success_count|metadata\n")
                temp_file.write("# Generated by Generic Parser Pattern Collector\n\n")
                
                # Write patterns sorted by success count (most successful first)
                sorted_patterns = sorted(self.patterns, key=lambda x: x['success_count'], reverse=True)
                for pattern_info in sorted_patterns:
                    line = f"{pattern_info['filename']}|{pattern_info['pattern']}|{pattern_info['success_count']}|{pattern_info.get('metadata', '')}\n"
                    temp_file.write(line)
                
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_filename = temp_file.name
            
            # Atomically move temp file to final location
            os.replace(temp_filename, self.patterns_file)
            
        except Exception as e:
            print(f"Warning: Could not save patterns: {e}")
            # Clean up temp file if it exists
            try:
                if 'temp_filename' in locals() and os.path.exists(temp_filename):
                    os.remove(temp_filename)
            except:
                pass
    
    def add_pattern(self, filename, pattern, transaction_count=0, metadata=""):
        """Add a new pattern or update existing one."""
        # Check if pattern already exists
        for existing in self.patterns:
            if existing['pattern'] == pattern:
                existing['success_count'] += 1
                existing['metadata'] = f"{existing['metadata']};{filename}({transaction_count})" if existing['metadata'] else f"{filename}({transaction_count})"
                return
        
        # Add new pattern
        self.patterns.append({
            'filename': filename,
            'pattern': pattern,
            'success_count': 1,
            'metadata': f"transactions:{transaction_count}"
        })
    
    def get_best_patterns(self, limit=10):
        """Get the most successful patterns."""
        sorted_patterns = sorted(self.patterns, key=lambda x: x['success_count'], reverse=True)
        return sorted_patterns[:limit]
    
    def get_patterns_for_testing(self):
        """Get all patterns for testing against new statements."""
        return [p['pattern'] for p in self.patterns]
    
    def get_compiled_pattern(self, pattern: str) -> re.Pattern:
        """Get compiled regex pattern with caching."""
        if pattern not in self._compiled_patterns:
            try:
                self._compiled_patterns[pattern] = re.compile(pattern)
            except re.error:
                # Return a pattern that never matches if compilation fails
                self._compiled_patterns[pattern] = re.compile(r'(?!.*)')
        return self._compiled_patterns[pattern]
    
    def select_best_patterns_for_text(self, text: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Select most relevant patterns based on text characteristics."""
        text_lower = text.lower()
        text_features = {
            'has_visa': 'visa' in text_lower,
            'has_mastercard': 'mastercard' in text_lower,
            'has_amex': 'american express' in text_lower or 'amex' in text_lower,
            'has_discover': 'discover' in text_lower,
            'has_chase': 'chase' in text_lower,
            'has_citi': 'citi' in text_lower,
            'has_bofa': 'bank of america' in text_lower or 'bofa' in text_lower,
            'date_format_mdy': bool(re.search(r'\d{1,2}/\d{1,2}/\d{2,4}', text)),
            'date_format_ymd': bool(re.search(r'\d{4}-\d{1,2}-\d{1,2}', text)),
            'has_dollar_sign': '$' in text,
            'line_count': len(text.split('\n'))
        }
        
        # Score patterns based on relevance to text features
        scored_patterns = []
        for pattern_data in self.get_best_patterns(20):
            score = pattern_data['success_count']
            
            # Boost score for patterns from similar contexts
            filename = pattern_data.get('filename', '').lower()
            if text_features['has_visa'] and 'visa' in filename:
                score *= 1.5
            if text_features['has_chase'] and 'chase' in filename:
                score *= 1.5
            if text_features['has_citi'] and 'citi' in filename:
                score *= 1.5
            
            scored_patterns.append((score, pattern_data))
        
        # Sort by score and return top patterns
        scored_patterns.sort(key=lambda x: x[0], reverse=True)
        return [pattern_data for _, pattern_data in scored_patterns[:limit]]


class GenericRegexParser(BankStatementParser):
    """Generic parser using K-means clustering and weak supervision for transaction detection."""
    
    def __init__(self):
        super().__init__()
        self.bank_name = "Generic (Auto-detect)"
        self.supported_formats = ["PDF"]
        
        # Lazy loading - initialize heavy components only when needed
        self._weak_labeler = None
        self._vendor_normalizer = None
        self._weight_manager = None
        self._pattern_collector = None
        self._sklearn_models = None
        
        # Performance optimization components
        self.performance_optimizer = PerformanceOptimizer()
        
        # Cached regex patterns for performance
        self._cached_money_pattern = None
        self._cached_date_pattern = None
        
        # Initialize regex patterns lazily for better startup performance
        self._init_regex_patterns()
        
        # Keywords that indicate non-transaction lines
        self.summary_keywords = [
            'previous balance', 'new balance', 'minimum payment', 'payment due',
            'credit limit', 'past due', 'fees charged', 'cash advance', 
            'balance transfer', 'messages for details', 'over the credit limit',
            'customer service', 'website', 'phone', 'autopay', 'account message',
            'www.', '.com', 'http', 'total', 'subtotal'
        ]
    
    def _init_regex_patterns(self):
        """Initialize regex patterns lazily."""
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
    
    # Lazy loading properties
    @property
    def weak_labeler(self):
        if self._weak_labeler is None:
            self._weak_labeler = WeakSupervisionLabeler()
        return self._weak_labeler
    
    @property
    def vendor_normalizer(self):
        if self._vendor_normalizer is None:
            self._vendor_normalizer = VendorNormalizer()
        return self._vendor_normalizer
    
    @property
    def weight_manager(self):
        if self._weight_manager is None:
            self._weight_manager = WeightManager()
        return self._weight_manager
    
    @property
    def pattern_collector(self):
        if self._pattern_collector is None:
            self._pattern_collector = RegexPatternCollector()
        return self._pattern_collector
    
    def can_parse(self, text: str) -> bool:
        """
        This is a fallback parser - it can attempt to parse any statement
        but should be used as last resort after specific parsers fail.
        """
        return True
    
    def _has_transaction_indicators(self, text: str) -> bool:
        """Quick check for transaction-like content to enable early exit."""
        money_count = len(self.RE_MONEY.findall(text))
        date_count = len(self.RE_DATE.findall(text))
        line_count = len([line for line in text.split('\n') if line.strip()])
        
        # Must have reasonable amounts of financial data
        return money_count >= 3 and date_count >= 2 and line_count >= 5
    
    def _cached_money_search(self, text: str) -> List[str]:
        """Cached money pattern search for performance."""
        if self._cached_money_pattern is None:
            self._cached_money_pattern = {}
        
        if text not in self._cached_money_pattern:
            self._cached_money_pattern[text] = self.RE_MONEY.findall(text)
        
        return self._cached_money_pattern[text]
    
    def _cached_date_search(self, text: str) -> List[str]:
        """Cached date pattern search for performance."""
        if self._cached_date_pattern is None:
            self._cached_date_pattern = {}
        
        if text not in self._cached_date_pattern:
            self._cached_date_pattern[text] = self.RE_DATE.findall(text)
        
        return self._cached_date_pattern[text]
    
    def try_pattern_based_extraction(self, text: str) -> List[Dict[str, Any]]:
        """Fast extraction using collected patterns before expensive clustering."""
        start_time = time.time()
        transactions = []
        
        try:
            # Get the most relevant patterns for this text
            relevant_patterns = self.pattern_collector.select_best_patterns_for_text(text, limit=8)
            
            if not relevant_patterns:
                return []
            
            text_lines = [line.strip() for line in text.split('\n') if line.strip()]
            best_matches = []
            
            # Try each relevant pattern
            for pattern_data in relevant_patterns:
                pattern = pattern_data['pattern']
                compiled_pattern = self.pattern_collector.get_compiled_pattern(pattern)
                
                matches = []
                for line in text_lines:
                    match = compiled_pattern.match(line)
                    if match:
                        transaction = self._parse_regex_match(match, line)
                        if transaction:
                            matches.append(transaction)
                
                # If this pattern found a good number of transactions, use it
                if len(matches) >= 3:
                    best_matches = matches
                    break
            
            if best_matches:
                transactions = best_matches
                
        except Exception as e:
            # Silently fall back to clustering if pattern matching fails
            pass
        
        execution_time = time.time() - start_time
        success = len(transactions) > 0
        self.performance_optimizer.record_performance(
            "pattern_based", len(text), execution_time, success, len(transactions)
        )
        
        return transactions
    
    def _parse_regex_match(self, match: re.Match, line: str) -> Optional[Dict[str, Any]]:
        """Parse a regex match into a transaction record."""
        try:
            groups = match.groups()
            if len(groups) < 2:
                return None
            
            description = groups[0].strip() if groups[0] else ""
            amount_str = groups[1].strip() if groups[1] else ""
            balance_str = groups[2].strip() if len(groups) > 2 and groups[2] else None
            
            # Extract date separately
            date_match = self.RE_DATE.search(line)
            date_str = date_match.group(0) if date_match else None
            
            # Parse amount
            amount = self.parse_amount(amount_str)
            if amount is None:
                return None
            
            # Parse date
            transaction_date = None
            if date_str:
                transaction_date = self.parse_date(date_str)
            
            # Normalize vendor name
            normalized_description = self.vendor_normalizer.normalize_vendor(description)
            
            return {
                'date': transaction_date.strftime('%Y-%m-%d') if transaction_date else date_str,
                'description': normalized_description,
                'original_description': description,
                'amount': amount,
                'balance': self.parse_amount(balance_str) if balance_str else None,
                'raw_line': line.strip()
            }
            
        except Exception:
            return None
    
    def load_page_lines(self, page) -> List[Line]:
        """Reconstruct lines from page.chars using DBSCAN clustering for better line detection."""
        if not hasattr(page, 'chars') or not page.chars:
            return []
        
        chars = page.chars
        if not chars:
            return []
        
        # Use DBSCAN for automatic line grouping
        y_groups = self.group_lines_dbscan(chars)
        if not y_groups:
            # Fallback to original method if DBSCAN fails
            y_groups = self.group_lines_traditional(chars)
        
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
        
        # Group continuation lines
        lines = self.group_continuation_lines(lines)
        
        return lines
    
    def group_lines_dbscan(self, chars):
        """Use DBSCAN to automatically discover line groups."""
        if not chars or len(chars) < 2:
            return self.group_lines_traditional(chars)
        
        try:
            # Extract y-coordinates (midpoints)
            y_coords = np.array([[(char['y0'] + char['y1']) / 2] for char in chars])
            
            # DBSCAN clustering on y-coordinates using weight manager parameters
            eps = self.weight_manager.get_weight('clustering', 'dbscan_eps')
            min_samples = self.weight_manager.get_weight('clustering', 'dbscan_min_samples')
            dbscan = DBSCAN(eps=eps, min_samples=min_samples)
            line_labels = dbscan.fit_predict(y_coords)
            
            # Group characters by line labels
            line_groups = {}
            for i, label in enumerate(line_labels):
                if label != -1:  # Ignore noise points
                    if label not in line_groups:
                        line_groups[label] = []
                    line_groups[label].append(chars[i])
            
            return line_groups
        except Exception:
            # Fallback to traditional method if DBSCAN fails
            return self.group_lines_traditional(chars)
    
    def group_lines_traditional(self, chars):
        """Traditional line grouping by similar y-coordinate."""
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
        return y_groups
    
    def group_continuation_lines(self, lines):
        """Group continuation lines with their parent transactions."""
        if not lines:
            return lines
        
        grouped_lines = []
        i = 0
        
        while i < len(lines):
            current_line = lines[i]
            
            # Check if this looks like a main transaction line
            has_date = bool(self.RE_DATE.search(current_line.text))
            has_money = bool(self.RE_MONEY.search(current_line.text))
            
            if has_date or has_money:
                # This is likely a main transaction line
                main_line = current_line
                continuation_lines = []
                
                # Look ahead for continuation lines
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    
                    # Check if next line is a continuation
                    if self.is_continuation_line(main_line, next_line):
                        continuation_lines.append(next_line)
                        j += 1
                    else:
                        break
                
                # Merge continuation lines into main line
                if continuation_lines:
                    merged_text = main_line.text
                    for cont_line in continuation_lines:
                        merged_text += " " + cont_line.text.strip()
                    
                    merged_line = Line(
                        tokens=main_line.tokens + [token for line in continuation_lines 
                                                 for token in line.tokens],
                        y=main_line.y,
                        text=merged_text
                    )
                    grouped_lines.append(merged_line)
                else:
                    grouped_lines.append(main_line)
                
                i = j
            else:
                # Standalone line (might be continuation we missed)
                grouped_lines.append(current_line)
                i += 1
        
        return grouped_lines
    
    def is_continuation_line(self, main_line, candidate_line):
        """Determine if candidate_line continues main_line."""
        # Check indentation similarity
        main_indent = main_line.tokens[0].x0 if main_line.tokens else 0
        cand_indent = candidate_line.tokens[0].x0 if candidate_line.tokens else 0
        
        # Continuation lines are usually indented similarly or slightly more
        indent_diff = abs(cand_indent - main_indent)
        
        # Check for absence of date/money (typical of continuation lines)
        has_date = bool(self.RE_DATE.search(candidate_line.text))
        has_money = bool(self.RE_MONEY.search(candidate_line.text))
        
        # Check vertical proximity
        y_diff = abs(main_line.y - candidate_line.y)
        
        # Use weight manager for continuation line thresholds
        cl_weights = self.weight_manager.weights['continuation_lines']
        return (indent_diff < cl_weights['indent_threshold'] and 
                not has_date and not has_money and 
                y_diff < cl_weights['y_diff_threshold'] and 
                len(candidate_line.text.strip()) > cl_weights['min_text_length'])
    
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
        """Score each cluster and return the best one for transactions using weak supervision."""
        unique_labels = list(set(labels))
        best_score = -1
        best_cluster = 0
        
        # Generate weak supervision labels for all lines
        weak_labels = self.weak_labeler.generate_weak_labels(lines)
        
        for label in unique_labels:
            cluster_indices = [i for i, l in enumerate(labels) if l == label]
            cluster_features = [features[i] for i in cluster_indices]
            cluster_lines = [lines[i] for i in cluster_indices]
            cluster_weak_labels = [weak_labels[i] for i in cluster_indices]
            
            if not cluster_features:
                continue
            
            # Traditional scoring based on transaction-like characteristics
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
            
            # Weak supervision score - percentage of lines labeled as transactions
            weak_supervision_score = np.mean(cluster_weak_labels) if cluster_weak_labels else 0
            
            # Combined score: traditional features + weak supervision using weight manager
            tf_weights = self.weight_manager.weights['traditional_features']
            traditional_score = (money_rate * tf_weights['money_rate'] + 
                               date_rate * tf_weights['date_rate'] + 
                               min(avg_tokens / 10, 1) * tf_weights['tokens'] + 
                               min(avg_chars / 50, 1) * tf_weights['chars'] + 
                               (1 - summary_rate) * tf_weights['summary'])
            
            # Weight weak supervision based on configuration
            ws_weights = self.weight_manager.weights['weak_supervision']
            if self.weak_labeler.openai_enabled and self.weak_labeler.openai_client:
                # AI-enhanced weak supervision weights
                score = (traditional_score * ws_weights['ai_enabled_traditional'] + 
                        weak_supervision_score * ws_weights['ai_enabled_weak'])
            else:
                # Rule-based weak supervision weights
                score = (traditional_score * ws_weights['rule_based_traditional'] + 
                        weak_supervision_score * ws_weights['rule_based_weak'])
            
            if score > best_score:
                best_score = score
                best_cluster = label
        
        return best_score, best_cluster
    
    def filter_lines_with_weak_supervision(self, lines: List[Line], confidence_threshold: float = None) -> List[Line]:
        """Pre-filter lines using weak supervision to improve clustering quality."""
        if not lines:
            return lines
        
        # Use weight manager for confidence threshold if not provided
        if confidence_threshold is None:
            confidence_threshold = self.weight_manager.get_weight('line_filtering', 'confidence_threshold')
        
        # Generate weak supervision labels for all lines
        weak_labels = self.weak_labeler.generate_weak_labels(lines)
        
        # Calculate confidence scores for each line
        filtered_lines = []
        for i, (line, label) in enumerate(zip(lines, weak_labels)):
            # For now, use simple binary filtering based on weak supervision
            # In a more sophisticated implementation, we could use actual confidence scores
            if label == 1:  # Line is predicted to be a transaction
                filtered_lines.append(line)
            elif confidence_threshold <= 0.1:  # Very low threshold - include uncertain lines
                # Include lines that have basic transaction indicators even if weak supervision says no
                has_date = bool(self.RE_DATE.search(line.text))
                has_money = bool(self.RE_MONEY.search(line.text))
                if has_date and has_money:
                    filtered_lines.append(line)
        
        # Ensure we don't filter out too many lines using weight manager ratio
        min_lines_ratio = self.weight_manager.get_weight('line_filtering', 'min_lines_ratio')
        min_lines = max(1, int(len(lines) * min_lines_ratio))
        if len(filtered_lines) < min_lines:
            # If filtering is too aggressive, fall back to basic filtering
            basic_filtered = []
            for line in lines:
                has_date = bool(self.RE_DATE.search(line.text))
                has_money = bool(self.RE_MONEY.search(line.text))
                if has_date or has_money:
                    basic_filtered.append(line)
            return basic_filtered if basic_filtered else lines
        
        return filtered_lines
    
    def infer_columns(self, lines):
        """Infer column structure from numeric token positions."""
        numeric_positions = []
        
        # Collect positions of all numeric tokens
        for line in lines:
            for token in line.tokens:
                if self.RE_MONEY.search(token.text):
                    numeric_positions.append(token.x1)  # Right edge for alignment
        
        if len(numeric_positions) < 4:
            return None  # Not enough data for column inference
        
        try:
            # Cluster numeric positions
            positions_array = np.array(numeric_positions).reshape(-1, 1)
            n_clusters = min(4, len(set(numeric_positions)))
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            clusters = kmeans.fit_predict(positions_array)
            
            # Sort cluster centers to identify column order
            centers = [(i, center[0]) for i, center in enumerate(kmeans.cluster_centers_)]
            centers.sort(key=lambda x: x[1])  # Sort by x position
            
            # Map clusters to likely column types
            column_mapping = {}
            if len(centers) >= 2:
                column_mapping[centers[-1][0]] = 'balance'  # Rightmost
                column_mapping[centers[-2][0]] = 'amount'   # Second from right
                if len(centers) >= 3:
                    column_mapping[centers[-3][0]] = 'debit'  # Third from right
            
            # Store cluster centers for later use
            self.column_centers = [center[1] for center in centers]
            
            return column_mapping
        except Exception:
            return None
    
    def classify_amounts_by_column(self, line, column_mapping):
        """Classify amounts in a line based on column inference."""
        if not column_mapping or not hasattr(self, 'column_centers'):
            return {}
        
        amounts = {}
        
        for token in line.tokens:
            if self.RE_MONEY.search(token.text):
                # Find which cluster this token belongs to
                position = token.x1
                best_cluster = None
                min_distance = float('inf')
                
                for cluster_id, cluster_center in enumerate(self.column_centers):
                    distance = abs(position - cluster_center)
                    if distance < min_distance:
                        min_distance = distance
                        best_cluster = cluster_id
                
                if best_cluster in column_mapping:
                    column_type = column_mapping[best_cluster]
                    amounts[column_type] = token.text
        
        return amounts
    
    def derive_regex_template(self, lines: List[Line]) -> str:
        """Build a generic regex for the transaction cluster."""
        if not lines:
            return r"^(.+)$"
        
        # Analyze date patterns
        date_patterns = []
        for line in lines:
            dates = self.RE_DATE.findall(line.text)
            date_patterns.extend(dates)
        
        # Analyze money patterns
        money_patterns = []
        n_money_counts = []
        for line in lines:
            money_matches = self.RE_MONEY.findall(line.text)
            money_patterns.extend(money_matches)
            n_money_counts.append(len(money_matches))
        
        # Build regex components
        date_part = r"(?:(?:\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?)|(?:\d{4}[/-]\d{1,2}[/-]\d{1,2})|(?:\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})|(?:[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{2,4})|(?:[A-Za-z]{3,9}\s+\d{1,2}))"
        money = r"[+\-]?\$?\d{1,3}(?:,\d{3})*\.\d{2}"
        
        # Determine if most lines have two money amounts (debit/credit + balance)
        two_money_rate = np.mean([c >= 2 for c in n_money_counts]) if n_money_counts else 0
        
        if two_money_rate >= 0.5:
            pattern = rf"^\s*{date_part}(.+?)\s+({money})\s+({money})\s*$"
        else:
            pattern = rf"^\s*{date_part}(.+?)\s+({money})\s*$"
        
        return pattern
    
    def _rule_based_clustering(self, lines: List[Line]) -> Tuple[List[int], float]:
        """Simple rule-based clustering for small datasets."""
        labels = []
        for line in lines:
            has_money = bool(self.RE_MONEY.search(line.text))
            has_date = bool(self.RE_DATE.search(line.text))
            
            if has_money and has_date:
                labels.append(1)  # Transaction cluster
            else:
                labels.append(0)  # Non-transaction cluster
        
        return labels, 0.8  # High confidence for rule-based
    
    def _kmeans_clustering(self, lines: List[Line], max_clusters: int = 3) -> Tuple[List[int], float]:
        """Lightweight K-means clustering with fewer clusters."""
        if len(lines) < 2:
            return [0] * len(lines), 0.5
        
        # Extract minimal features for speed
        features = []
        for line in lines:
            has_money = int(bool(self.RE_MONEY.search(line.text)))
            has_date = int(bool(self.RE_DATE.search(line.text)))
            n_tokens = len(line.text.split())
            features.append([has_money, has_date, min(n_tokens, 20)])  # Cap tokens for consistency
        
        X = np.array(features)
        n_clusters = min(max_clusters, len(lines) // 2)
        
        try:
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=5)  # Fewer iterations
            labels = kmeans.fit_predict(X)
            return labels.tolist(), 0.7
        except Exception:
            return self._rule_based_clustering(lines)
    
    def _full_clustering(self, lines: List[Line]) -> Tuple[List[int], float]:
        """Full clustering with all features for large datasets."""
        page_width = 612.0
        labels, features = self.cluster_transactions(lines, page_width)
        score, chosen_cluster = self.evaluate_clusters(np.array(labels), features, lines)
        return labels, score
    
    def adaptive_clustering(self, lines: List[Line]) -> Tuple[List[int], float]:
        """Use appropriate clustering method based on dataset size."""
        n_lines = len(lines)
        
        if n_lines < 15:
            return self._rule_based_clustering(lines)
        elif n_lines < 50:
            return self._kmeans_clustering(lines, max_clusters=3)
        elif n_lines < 150:
            return self._kmeans_clustering(lines, max_clusters=5)
        else:
            return self._full_clustering(lines)
    
    def extract_transactions_parallel(self, text: str) -> List[Dict[str, Any]]:
        """Extract transactions using parallel processing of different strategies."""
        start_time = time.time()
        text_length = len(text)
        
        # Early exit if text doesn't look like it contains transactions
        if not self._has_transaction_indicators(text):
            self.performance_optimizer.record_performance(
                "early_exit", text_length, time.time() - start_time, False, 0
            )
            return []
        
        futures = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            # Run different extraction strategies in parallel
            futures.append(executor.submit(self.try_pattern_based_extraction, text))
            futures.append(executor.submit(self._clustering_extraction, text))
            futures.append(executor.submit(self._fallback_extraction, text))
            
            # Return first successful result
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result and len(result) >= 3:  # Minimum threshold for success
                        execution_time = time.time() - start_time
                        self.performance_optimizer.record_performance(
                            "parallel_extraction", text_length, execution_time, True, len(result)
                        )
                        return result
                except Exception:
                    continue
        
        # If no strategy succeeded, return empty list
        execution_time = time.time() - start_time
        self.performance_optimizer.record_performance(
            "parallel_extraction", text_length, execution_time, False, 0
        )
        return []
    
    def _clustering_extraction(self, text: str) -> List[Dict[str, Any]]:
        """Clustering-based extraction method."""
        start_time = time.time()
        transactions = []
        
        try:
            # Split text into lines and create mock Line objects
            text_lines = text.split('\n')
            lines = []
            
            for i, line_text in enumerate(text_lines):
                if line_text.strip():
                    line = Line(
                        tokens=[],
                        y=float(i),
                        text=line_text.strip()
                    )
                    lines.append(line)
            
            if not lines:
                return []
            
            # Use adaptive clustering based on dataset size
            labels, confidence = self.adaptive_clustering(lines)
            
            # Find the transaction cluster (cluster with most money/date patterns)
            cluster_scores = defaultdict(int)
            for line, label in zip(lines, labels):
                has_money = bool(self.RE_MONEY.search(line.text))
                has_date = bool(self.RE_DATE.search(line.text))
                if has_money and has_date:
                    cluster_scores[label] += 2
                elif has_money or has_date:
                    cluster_scores[label] += 1
            
            if not cluster_scores:
                return []
            
            chosen_cluster = max(cluster_scores.keys(), key=lambda k: cluster_scores[k])
            txn_lines = [line for line, label in zip(lines, labels) if label == chosen_cluster]
            
            if not txn_lines:
                return []
            
            # Generate regex pattern and extract transactions
            pattern = self.derive_regex_template(txn_lines)
            regex = re.compile(pattern)
            
            for line in txn_lines:
                match = regex.match(line.text)
                if match:
                    transaction = self._parse_regex_match(match, line.text)
                    if transaction:
                        transactions.append(transaction)
            
        except Exception:
            pass
        
        execution_time = time.time() - start_time
        success = len(transactions) > 0
        self.performance_optimizer.record_performance(
            "clustering_extraction", len(text), execution_time, success, len(transactions)
        )
        
        return transactions
    
    def extract_transactions(self, text: str) -> List[Dict[str, Any]]:
        """Extract transactions using optimized multi-strategy approach."""
        start_time = time.time()
        text_length = len(text)
        
        # Early exit if text doesn't contain transaction indicators
        if not self._has_transaction_indicators(text):
            self.performance_optimizer.record_performance(
                "early_exit", text_length, time.time() - start_time, False, 0
            )
            return []
        
        # Choose optimal strategy based on text characteristics and historical performance
        strategy = self.performance_optimizer.get_optimal_strategy(text_length)
        
        # Override strategy for BofA files to use pattern-based extraction
        if hasattr(self, 'current_filename') and self.current_filename:
            filename_lower = self.current_filename.lower()
            if 'bofa' in filename_lower or 'bank of america' in filename_lower or 'estmt' in filename_lower:
                strategy = "pattern_based"
        
        transactions = []
        
        if strategy == "pattern_based":
            # Try pattern-based extraction first (fastest)
            transactions = self.try_pattern_based_extraction(text)
            if not transactions:
                # Fallback to light clustering
                transactions = self._clustering_extraction(text)
        
        elif strategy == "light_clustering":
            # Try clustering with early pattern fallback
            transactions = self._clustering_extraction(text)
            if not transactions:
                transactions = self.try_pattern_based_extraction(text)
        
        elif strategy == "adaptive_clustering":
            # Use adaptive clustering approach
            transactions = self._clustering_extraction(text)
        
        else:  # full_clustering
            # Use the original comprehensive approach
            transactions = self._original_extract_transactions(text)
        
        # Final fallback if no strategy worked
        if not transactions:
            transactions = self._fallback_extraction(text)
        
        # Record performance and collect patterns if successful
        execution_time = time.time() - start_time
        success = len(transactions) > 0
        
        self.performance_optimizer.record_performance(
            strategy, text_length, execution_time, success, len(transactions)
        )
        
        if success and hasattr(self, 'current_filename'):
            # Collect regex pattern for future use
            pattern = self.derive_regex_template([Line([], 0, t['raw_line']) for t in transactions if 'raw_line' in t])
            self.pattern_collector.add_pattern(
                self.current_filename, pattern, len(transactions), 
                f"transactions:{len(transactions)}"
            )
            self.pattern_collector.save_patterns()
        
        return transactions
    
    def _original_extract_transactions(self, text: str) -> List[Dict[str, Any]]:
        """Original comprehensive extraction method for complex cases."""
        transactions = []
        
        try:
            # Split text into lines and create mock Line objects
            text_lines = text.split('\n')
            lines = []
            
            for i, line_text in enumerate(text_lines):
                if line_text.strip():
                    line = Line(
                        tokens=[],
                        y=float(i),
                        text=line_text.strip()
                    )
                    lines.append(line)
            
            if not lines:
                return transactions
            
            # Pre-filter lines using weak supervision
            filtered_lines = self.filter_lines_with_weak_supervision(lines)
            
            if not filtered_lines:
                filtered_lines = lines
            
            # Use full clustering for complex cases
            page_width = 612.0
            labels, features = self.cluster_transactions(filtered_lines, page_width)
            
            # Find the best cluster for transactions
            score, chosen_cluster = self.evaluate_clusters(np.array(labels), features, filtered_lines)
            
            # Get transaction lines from the chosen cluster
            txn_lines = [line for line, label in zip(filtered_lines, labels) if label == chosen_cluster]
            
            if not txn_lines:
                return transactions
            
            # Infer column structure
            self.column_mapping = self.infer_columns(txn_lines)
            
            # Generate regex pattern
            pattern = self.derive_regex_template(txn_lines)
            regex = re.compile(pattern)
            
            # Extract transactions
            for line in txn_lines:
                match = regex.match(line.text)
                if match:
                    transaction = self._parse_regex_match(match, line.text)
                    if transaction:
                        transactions.append(transaction)
        
        except Exception as e:
            # Fallback to simple pattern matching
            transactions = self._fallback_extraction(text)
        
        return transactions
        
        return transactions
        
    def _record_parsing_performance(self, original_text, transactions, total_lines):
        """Record performance metrics for weight adaptation."""
        try:
            # Calculate basic metrics
            lines_processed = len(original_text.split('\n'))
            transactions_found = len(transactions)
            success_rate = transactions_found / max(1, lines_processed) if lines_processed > 0 else 0
            
            # Calculate quality metrics
            transactions_with_dates = sum(1 for t in transactions if t.get('date'))
            transactions_with_amounts = sum(1 for t in transactions if t.get('amount'))
            
            date_coverage = transactions_with_dates / max(1, transactions_found) if transactions_found > 0 else 0
            amount_coverage = transactions_with_amounts / max(1, transactions_found) if transactions_found > 0 else 0
            
            metrics = {
                'lines_processed': lines_processed,
                'total_filtered_lines': total_lines,
                'transactions_found': transactions_found,
                'success_rate': success_rate,
                'date_coverage': date_coverage,
                'amount_coverage': amount_coverage,
                'avg_description_length': np.mean([len(t.get('description', '')) for t in transactions]) if transactions else 0
            }
            
            # Record performance (filename will be set by caller if available)
            self.weight_manager.record_performance('generic_parse', metrics)
            
            # Adapt weights based on performance
            self.weight_manager.adapt_weights()
            
        except Exception as e:
            print(f"Warning: Could not record performance metrics: {e}")
    
    def set_parsing_context(self, filename):
        """Set context for performance tracking and pattern collection."""
        self.current_filename = filename
    
    def get_performance_summary(self):
        """Get summary of recent performance."""
        if not self.weight_manager.performance_history:
            return "No performance data available"
        
        recent = self.weight_manager.performance_history[-10:]
        avg_success = sum(p['metrics'].get('success_rate', 0) for p in recent) / len(recent)
        avg_transactions = sum(p['metrics'].get('transactions_found', 0) for p in recent) / len(recent)
        
        return {
            'recent_parses': len(recent),
            'avg_success_rate': avg_success,
            'avg_transactions_found': avg_transactions,
            'total_performance_records': len(self.weight_manager.performance_history)
        }
    
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
