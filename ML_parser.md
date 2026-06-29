# ML Parser Architecture

## Overview
Hybrid rules-based + machine learning pipeline for bank statement transaction extraction. Combines the reliability of rule-based parsing with the adaptability of ML to handle diverse statement formats and improve accuracy over time.

## Pipeline Architecture

### 1. Ingest & Text Extraction
```
PDF Input → Text Extraction → Page Segmentation → Table Structure → Row Classification → Column Assignment → Post-processing
```

#### Text Extraction Strategy
- **Text-based PDFs**: `pdfplumber` or `pdfminer.six` for direct text extraction
- **Scanned PDFs**: `ocrmypdf` (Tesseract) → text extraction
- **Fallback**: Hybrid approach detecting mixed content types

#### Implementation
```python
def extract_text(pdf_path):
    if is_text_based(pdf_path):
        return extract_with_pdfplumber(pdf_path)
    else:
        ocr_pdf = apply_ocr(pdf_path)
        return extract_with_pdfplumber(ocr_pdf)
```

### 2. Page Segmentation
Identify document structure components: tables, headers, footers, paragraphs.

#### ML Option (Advanced)
- **LayoutParser** + Detectron2 for layout detection
- **DocTR** for document structure analysis  
- **LayoutLMv3** for block classification: `{table, header, footer, paragraph}`

#### Heuristic Fallback (Fast)
- Detect dense horizontal/vertical line geometry
- Identify repeated baselines and text alignment patterns
- Use geometric features for block classification

```python
def segment_page(page_content):
    # Try ML approach first
    if use_ml_segmentation:
        return layoutparser_segment(page_content)
    # Fallback to heuristics
    return heuristic_segment(page_content)
```

### 3. Table Structure Detection
Extract candidate tables and determine column structure.

#### Tools
- **Camelot** (lattice/stream methods) for table detection
- **pdfplumber** for table extraction
- Custom column estimation via x-coordinate clustering

#### Column Handling
- Tolerate ragged columns and multi-line cells
- Handle varying column widths across banks
- Adaptive column detection per statement type

### 4. Row Candidate Generation
Identify potential transaction rows from table structure.

```python
def generate_row_candidates(table_data):
    candidates = []
    for line in table_data:
        if is_between_horizontal_rulings(line) or has_y_gap(line):
            candidates.append(create_row_candidate(line))
    return candidates
```

### 5. Row-Level Classification (Core ML Component)

#### Feature Engineering
**Text Features:**
- `looks_like_date`: Regex patterns for various date formats
- `looks_like_amount`: Currency and decimal patterns
- `has_balance`: Running balance indicators
- `debit_credit_sign`: Transaction direction indicators
- `id_length_patterns`: Transaction ID characteristics

**Geometry Features:**
- Column density and alignment metrics
- Font size and weight variations
- Spatial relationships between elements

**Context Features:**
- Previous/next row types for sequence modeling
- Position within document structure
- Bank-specific pattern indicators

#### Model Options

**Fast & Reliable:**
```python
# Gradient Boosted Trees (XGBoost/LightGBM)
features = extract_features(row_candidate)
prediction = xgb_model.predict(features)
row_type = {transaction, header, subtotal, junk}[prediction]
```

**Advanced:**
```python
# LayoutLMv3/DocFormer with sequence labeling
tokens_with_bbox = tokenize_with_positions(row_text)
sequence_labels = layoutlm_model.predict(tokens_with_bbox)
row_type = aggregate_sequence_labels(sequence_labels)
```

**Structured Prediction:**
- Add CRF (Conditional Random Fields) for structure enforcement
- HMM for state transitions: `headers → transactions → totals`
- Ensure logical document flow

### 6. Column Assignment
Map classified transaction rows to specific fields.

```python
def assign_columns(transaction_row, bank_profile):
    column_bands = bank_profile.get_column_bands()
    fields = {}
    
    for field_type in ['date', 'description', 'debit', 'credit', 'balance']:
        field_value = extract_from_column_band(
            transaction_row, 
            column_bands[field_type]
        )
        fields[field_type] = field_value
    
    return fields
```

#### Bank-Specific Profiles
- Learn column positions per bank over time
- Maintain probabilistic column assignments
- Handle variations in statement formats

### 7. Post-processing & Validation

#### Balance Continuity Validation
```python
def validate_balance_continuity(transactions):
    for i, txn in enumerate(transactions[1:], 1):
        expected_balance = calculate_expected_balance(
            transactions[i-1], txn
        )
        if abs(txn.balance - expected_balance) > tolerance:
            flag_for_review(txn)
```

#### Data Normalization
- Merge multi-line descriptions
- Handle carry-over rows across page breaks
- Normalize amounts, dates, and signs
- Categorize: "Payments & Credits" vs "Purchases"

## Training Data Strategy

### Synthetic Data Generation
- Use existing visual PDF training generator
- Bank-segmented training data
- Preserve authentic formatting and structure

### Ground Truth Creation
- Compare against specialized parsers for accuracy
- Use bank-specific parsers as "oracle" for training labels
- Continuous learning from parsing corrections

### Training Pipeline
```python
def train_ml_parser():
    # Load synthetic training data
    training_data = load_synthetic_data_by_bank()
    
    # Generate features
    features = extract_features_parallel(training_data)
    
    # Get ground truth from specialized parsers
    labels = generate_labels_from_specialized_parsers(training_data)
    
    # Train models
    row_classifier = train_row_classifier(features, labels)
    column_assigner = train_column_assigner(features, labels)
    
    return MLParser(row_classifier, column_assigner)
```

## Performance Monitoring

### Accuracy Metrics
- Transaction detection rate vs specialized parsers
- Field extraction accuracy (date, amount, description)
- Balance continuity validation success rate

### Continuous Improvement
- Online learning from parsing corrections
- Periodic retraining on new synthetic data
- A/B testing between rule-based and ML approaches

## Implementation Architecture

### Core Components
1. **MLParser**: Main parsing engine
2. **FeatureExtractor**: Text and geometry feature generation
3. **RowClassifier**: ML model for row type prediction
4. **ColumnAssigner**: Field extraction from classified rows
5. **PostProcessor**: Validation and normalization
6. **TrainingPipeline**: Continuous learning system

### Integration with Existing System
- Seamless fallback to existing GenericRegexParser
- Bank-specific parser comparison for validation
- Performance monitoring and automatic switching

### Scalability
- Parallel processing for large document sets
- Efficient feature caching
- Model versioning and rollback capabilities

## Benefits

1. **Adaptability**: Learns from new statement formats automatically
2. **Accuracy**: Combines rule-based reliability with ML flexibility  
3. **Scalability**: Handles diverse banks and statement types
4. **Maintainability**: Reduces manual regex pattern creation
5. **Performance**: Optimized for both speed and accuracy

## Future Enhancements

1. **Multi-modal Learning**: Combine text, layout, and visual features
2. **Transfer Learning**: Apply knowledge across similar banks
3. **Active Learning**: Prioritize uncertain cases for human review
4. **Real-time Adaptation**: Update models based on user corrections
