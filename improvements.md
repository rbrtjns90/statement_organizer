# Generic Parser Improvements

This document outlines 10 key improvements to enhance the generic bank statement parser's accuracy, robustness, and performance. Based on the current K-means clustering approach, these enhancements address the main limitations identified in testing.

## Current State Analysis

The existing `GenericRegexParser` uses K-means clustering on line features (position, money presence, dates) to identify transaction patterns. While innovative, it has a 21.1% success rate across 180 test PDFs, indicating significant room for improvement.

## Proposed Improvements

### 1. Anchored Crop Before Parsing

**Problem**: Mixed-content pages (headers, footers, account summaries) dilute transaction clustering.

**Solution**: Add a pre-processing step to locate and crop to transaction regions.

```python
def crop_to_transactions(self, page):
    """Crop page to transaction section using keyword anchors."""
    # Search for common transaction section headers
    anchors = ["Transactions", "Activity", "Transaction History", 
               "Account Activity", "Statement Activity"]
    
    for anchor in anchors:
        matches = page.search(anchor, case=False)
        if matches:
            # Crop from anchor to end of meaningful content
            crop_y = matches[0]['y1'] - 10  # Start slightly above match
            return page.crop((0, 0, page.width, crop_y))
    
    return page  # Return full page if no anchor found
```

**Expected Impact**: 15-25% accuracy improvement by reducing noise in clustering.

### 2. Swap/Augment K-means with DBSCAN for Line Discovery

**Problem**: K-means requires pre-defining cluster count, but statement layouts vary significantly.

**Solution**: Use DBSCAN for automatic line grouping, keep K-means for column inference.

```python
from sklearn.cluster import DBSCAN

def group_lines_dbscan(self, chars):
    """Use DBSCAN to automatically discover line groups."""
    if not chars:
        return []
    
    # Extract y-coordinates (midpoints)
    y_coords = np.array([[char['y0'] + char['y1']) / 2] for char in chars])
    
    # DBSCAN clustering on y-coordinates
    dbscan = DBSCAN(eps=3.0, min_samples=2)
    line_labels = dbscan.fit_predict(y_coords)
    
    # Group characters by line labels
    line_groups = {}
    for i, label in enumerate(line_labels):
        if label != -1:  # Ignore noise points
            if label not in line_groups:
                line_groups[label] = []
            line_groups[label].append(chars[i])
    
    return self.merge_chars_to_lines(line_groups)
```

**Expected Impact**: Better handling of variable line spacing, 10-15% accuracy improvement.

### 3. Probabilistic Row Filter

**Problem**: Current binary clustering misses nuanced transaction/non-transaction distinctions.

**Solution**: Add ML-based row classification with confidence scoring.

```python
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV

class TransactionRowClassifier:
    def __init__(self):
        self.classifier = CalibratedClassifierCV(
            LogisticRegression(random_state=42), 
            method='sigmoid'
        )
        self.is_trained = False
    
    def extract_row_features(self, line):
        """Extract features for transaction classification."""
        return {
            'has_date': bool(self.RE_DATE.search(line.text)),
            'has_money': bool(self.RE_MONEY.search(line.text)),
            'money_count': len(self.RE_MONEY.findall(line.text)),
            'token_count': len(line.tokens),
            'char_count': len(line.text),
            'left_aligned': line.tokens[0].x0 < 50 if line.tokens else False,
            'right_aligned': line.tokens[-1].x1 > 500 if line.tokens else False,
            'contains_keywords': any(kw in line.text.lower() 
                                   for kw in ['debit', 'credit', 'purchase', 'payment'])
        }
    
    def classify_with_confidence(self, line):
        """Return (is_transaction, confidence_score)."""
        if not self.is_trained:
            return True, 0.5  # Fallback to current behavior
        
        features = self.extract_row_features(line)
        feature_vector = np.array(list(features.values())).reshape(1, -1)
        
        prediction = self.classifier.predict(feature_vector)[0]
        confidence = self.classifier.predict_proba(feature_vector)[0].max()
        
        return bool(prediction), confidence
```

**Expected Impact**: 20-30% accuracy improvement with confidence-based filtering.

### 4. Continuation-Line Grouping

**Problem**: Multi-line transactions (descriptions spanning multiple lines) are treated as separate entries.

**Solution**: Implement deterministic continuation-line detection.

```python
def group_continuation_lines(self, lines):
    """Group continuation lines with their parent transactions."""
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
    
    return (indent_diff < 20 and not has_date and not has_money and 
            y_diff < 15 and len(candidate_line.text.strip()) > 5)
```

**Expected Impact**: 10-15% improvement in transaction completeness.

### 5. Explicit PDFPlumber Table Mode

**Problem**: Some statements use clear tabular layouts that could be parsed more directly.

**Solution**: Add table extraction fallback with tuned parameters.

```python
def extract_with_table_mode(self, page, fallback_to_generic=True):
    """Attempt table extraction before falling back to generic parsing."""
    try:
        # Try different table extraction strategies
        strategies = [
            {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
            {"vertical_strategy": "text", "horizontal_strategy": "text"},
            {"vertical_strategy": "explicit", "horizontal_strategy": "explicit"}
        ]
        
        for strategy in strategies:
            tables = page.find_tables(table_settings=strategy)
            
            if tables:
                # Extract the largest table (likely transactions)
                largest_table = max(tables, key=lambda t: len(t.extract()))
                table_data = largest_table.extract()
                
                # Convert table data to transactions
                transactions = self.parse_table_data(table_data)
                if transactions:
                    return transactions
        
        # If table extraction fails and fallback is enabled
        if fallback_to_generic:
            return self.extract_with_clustering(page)
        
    except Exception as e:
        if fallback_to_generic:
            return self.extract_with_clustering(page)
        raise e
    
    return []

def parse_table_data(self, table_data):
    """Convert extracted table data to transaction format."""
    transactions = []
    
    # Skip header rows and process data rows
    for row in table_data[1:]:  # Assume first row is header
        if len(row) >= 3:  # Minimum: date, description, amount
            date_str = row[0] if row[0] else ""
            description = row[1] if row[1] else ""
            amount_str = row[-1] if row[-1] else ""  # Amount usually in last column
            
            # Validate and parse
            if (self.RE_DATE.search(date_str) and 
                self.RE_MONEY.search(amount_str) and 
                len(description.strip()) > 2):
                
                transactions.append({
                    'date': date_str.strip(),
                    'description': description.strip(),
                    'amount': amount_str.strip()
                })
    
    return transactions
```

**Expected Impact**: 25-35% improvement for well-structured tabular statements.

### 6. OCR Fallback Path

**Problem**: Scanned PDFs with sparse character data fail completely.

**Solution**: Detect scanned content and route through OCR pipeline.

```python
def needs_ocr(self, page):
    """Determine if page needs OCR processing."""
    char_count = len(page.chars)
    page_area = page.width * page.height
    char_density = char_count / page_area if page_area > 0 else 0
    
    # If character density is very low, likely a scanned PDF
    return char_density < 0.01

def extract_with_ocr(self, page):
    """Extract text using OCR and continue with normal processing."""
    try:
        # Convert page to image
        page_image = page.to_image(resolution=300)
        
        # Use docTR or similar OCR library
        # This is a placeholder - actual implementation would use docTR
        ocr_result = self.ocr_engine.process(page_image.original)
        
        # Convert OCR result back to pdfplumber-like format
        synthetic_chars = self.convert_ocr_to_chars(ocr_result)
        
        # Continue with normal clustering process
        return self.process_chars_to_transactions(synthetic_chars)
        
    except Exception as e:
        print(f"OCR processing failed: {e}")
        return []

def convert_ocr_to_chars(self, ocr_result):
    """Convert OCR word boxes to pdfplumber char format."""
    chars = []
    for word in ocr_result.words:
        for i, char in enumerate(word.text):
            # Estimate character position within word box
            char_width = word.bbox.width / len(word.text)
            char_x0 = word.bbox.x0 + (i * char_width)
            char_x1 = char_x0 + char_width
            
            chars.append({
                'text': char,
                'x0': char_x0,
                'x1': char_x1,
                'y0': word.bbox.y0,
                'y1': word.bbox.y1
            })
    
    return chars
```

**Expected Impact**: Enables parsing of previously impossible scanned PDFs.

### 7. Column Inference Pass

**Problem**: Current parser doesn't reliably identify debit/credit/balance columns.

**Solution**: Use K-means clustering on numeric token positions to infer columns.

```python
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
    
    # Cluster numeric positions
    positions_array = np.array(numeric_positions).reshape(-1, 1)
    kmeans = KMeans(n_clusters=min(4, len(set(numeric_positions))), random_state=42)
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
    
    return column_mapping

def classify_amounts_by_column(self, line, column_mapping):
    """Classify amounts in a line based on column inference."""
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
```

**Expected Impact**: 15-20% improvement in amount classification accuracy.

### 8. Vendor Normalization Utility

**Problem**: Merchant names vary significantly (e.g., "AMAZON.COM", "Amazon", "AMZN").

**Solution**: Add fuzzy matching for vendor name standardization.

```python
from rapidfuzz import fuzz, process
import json

class VendorNormalizer:
    def __init__(self, cache_file="vendor_cache.json"):
        self.cache_file = cache_file
        self.cache = self.load_cache()
        self.common_vendors = [
            "Amazon", "Walmart", "Target", "Starbucks", "McDonald's",
            "Shell", "Exxon", "BP", "Chevron", "Home Depot", "Lowe's"
        ]
    
    def load_cache(self):
        """Load cached vendor mappings."""
        try:
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def save_cache(self):
        """Save vendor mappings to cache."""
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f, indent=2)
    
    def normalize_vendor(self, raw_vendor, threshold=80):
        """Normalize vendor name using fuzzy matching."""
        raw_clean = raw_vendor.strip().upper()
        
        # Check cache first
        if raw_clean in self.cache:
            return self.cache[raw_clean]
        
        # Find best match among common vendors
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
        
        # Title case
        return vendor.strip().title()
```

**Expected Impact**: Improved transaction categorization and duplicate detection.

### 9. Weak-Supervision Harness

**Problem**: Hand-labeling training data is expensive and time-consuming.

**Solution**: Use programmatic labeling functions for automated training data generation.

```python
class WeakSupervisionLabeler:
    def __init__(self):
        self.openai_enabled = self.check_openai_enabled()
        self.labeling_functions = [
            self.lf_has_date_and_amount,
            self.lf_right_aligned_amount,
            self.lf_starts_with_card_number,
            self.lf_contains_merchant_indicators,
            self.lf_reasonable_length,
            self.lf_not_summary_line
        ]
        
        # Add ChatGPT labeling function if OpenAI is enabled
        if self.openai_enabled:
            self.labeling_functions.append(self.lf_chatgpt_classifier)
            self.openai_client = self.init_openai_client()
    
    def check_openai_enabled(self):
        """Check if OpenAI is enabled via openai.txt file."""
        try:
            with open('openai.txt', 'r') as f:
                content = f.read().strip().lower()
                return content in ['true', '1', 'enabled', 'yes']
        except FileNotFoundError:
            return False
    
    def init_openai_client(self):
        """Initialize OpenAI client if enabled."""
        try:
            import openai
            import os
            
            # Get API key from environment or openai.txt
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
        summary_terms = ['total', 'balance', 'summary', 'subtotal']
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
```

**Expected Impact**: Automated training data generation, 20-25% accuracy improvement.

### 10. Scoring and Telemetry

**Problem**: No systematic way to measure parser performance or detect regressions.

**Solution**: Implement comprehensive parsing metrics and logging.

```python
class ParsingTelemetry:
    def __init__(self):
        self.metrics = {}
    
    def calculate_metrics(self, lines, transactions, parsing_time):
        """Calculate comprehensive parsing metrics."""
        total_lines = len(lines)
        transaction_lines = len(transactions)
        
        # Basic acceptance rate
        acceptance_rate = transaction_lines / total_lines if total_lines > 0 else 0
        
        # Continuation line analysis
        continuation_count = sum(1 for t in transactions 
                               if len(t.get('description', '').split()) > 10)
        continuation_rate = continuation_count / transaction_lines if transaction_lines > 0 else 0
        
        # Date and amount coverage
        date_coverage = sum(1 for t in transactions 
                          if self.RE_DATE.search(t.get('date', ''))) / transaction_lines if transaction_lines > 0 else 0
        
        amount_coverage = sum(1 for t in transactions 
                            if self.RE_MONEY.search(t.get('amount', ''))) / transaction_lines if transaction_lines > 0 else 0
        
        # Quality metrics
        avg_description_length = np.mean([len(t.get('description', '')) 
                                        for t in transactions]) if transactions else 0
        
        unique_descriptions = len(set(t.get('description', '') 
                                    for t in transactions)) / transaction_lines if transaction_lines > 0 else 0
        
        self.metrics = {
            'total_lines': total_lines,
            'transaction_count': transaction_lines,
            'acceptance_rate': acceptance_rate,
            'continuation_rate': continuation_rate,
            'date_coverage': date_coverage,
            'amount_coverage': amount_coverage,
            'avg_description_length': avg_description_length,
            'description_uniqueness': unique_descriptions,
            'parsing_time_seconds': parsing_time,
            'timestamp': datetime.now().isoformat()
        }
        
        return self.metrics
    
    def log_metrics(self, filename, metrics):
        """Log metrics to file for analysis."""
        log_entry = {
            'filename': filename,
            'metrics': metrics
        }
        
        with open('parsing_metrics.jsonl', 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
    
    def detect_regression(self, current_metrics, baseline_metrics, threshold=0.1):
        """Detect if current parsing represents a regression."""
        key_metrics = ['acceptance_rate', 'date_coverage', 'amount_coverage']
        
        regressions = []
        for metric in key_metrics:
            current_val = current_metrics.get(metric, 0)
            baseline_val = baseline_metrics.get(metric, 0)
            
            if baseline_val > 0:
                change = (current_val - baseline_val) / baseline_val
                if change < -threshold:
                    regressions.append(f"{metric}: {change:.2%} decrease")
        
        return regressions
```

**Expected Impact**: Systematic performance monitoring and regression detection.

## Implementation Priority

1. **High Priority** (Immediate 20-40% improvement):
   - Anchored crop before parsing (#1)
   - Probabilistic row filter (#3)
   - Explicit table mode (#5)

2. **Medium Priority** (10-20% improvement):
   - DBSCAN line discovery (#2)
   - Continuation-line grouping (#4)
   - Column inference (#7)

3. **Long-term** (Infrastructure and edge cases):
   - OCR fallback (#6)
   - Vendor normalization (#8)
   - Weak supervision (#9)
   - Telemetry system (#10)

## Expected Overall Impact

Implementing all improvements could potentially increase the generic parser success rate from 21.1% to 60-80%, making it a viable fallback for most statement formats. The combination of better preprocessing (cropping), improved clustering (DBSCAN), and ML-based filtering should address the main failure modes identified in testing.

## Integration Notes

- All improvements should maintain backward compatibility with the existing `BankStatementParser` interface
- New dependencies (scikit-learn, rapidfuzz, docTR) should be added to requirements.txt
- Each improvement should include comprehensive unit tests
- Performance benchmarks should be established before and after each implementation
