# AI Transaction Extraction for Unknown Banks

## Overview

The system now uses multimodal AI to extract transactions directly from PDF statements when dealing with unknown banks (banks without dedicated parsers).

## How It Works

### Detection Flow for Unknown Banks

```
1. Regex Detection → Fails (no parser for this bank)
2. AI Bank Detection → Identifies bank (e.g., "Wells Fargo")
3. Check Parser Registry → No parser found
4. AI Transaction Extraction → Activated ✅
```

### AI Transaction Extraction Process

For each page of the statement:

1. **Render page as image** (150 DPI, up to 1200px width)
2. **Extract text** (first 1000 characters for context)
3. **Send to AI model** with multimodal prompt:
   - Image: Visual layout of the statement
   - Text: Transaction data
   - Instruction: Extract date, description, amount for each transaction
4. **Parse JSON response** containing transaction array
5. **Validate and normalize** each transaction:
   - Parse dates using dateutil
   - Clean and parse amounts
   - Validate required fields
6. **Return structured transactions**

### Example AI Prompt

```
Extract all transactions from this bank statement page.
For each transaction, provide: date, description, amount.
Respond with JSON array: [{"date": "MM/DD/YYYY", "description": "...", "amount": 123.45}]
Page text:
[First 1000 characters of page text]
```

### Example AI Response

```json
[
  {"date": "01/15/2026", "description": "AMAZON.COM", "amount": -45.67},
  {"date": "01/16/2026", "description": "STARBUCKS #1234", "amount": -5.50},
  {"date": "01/17/2026", "description": "PAYCHECK DEPOSIT", "amount": 2500.00}
]
```

## When It's Used

### Scenario 1: Unknown Bank Detected
```
User uploads: Wells Fargo statement
→ Regex fails (no Wells Fargo parser)
→ AI detects: "Wells Fargo" (92% confidence)
→ No parser found for Wells Fargo
→ AI Transaction Extraction activated
→ Extracts transactions using multimodal AI
→ Logs to config/unknown_banks.json
```

### Scenario 2: Low Confidence Detection
```
User uploads: Regional credit union statement
→ Regex fails
→ AI detection: low confidence (<70%)
→ Falls back to generic parser (ML + K-means)
```

## Performance Characteristics

### Speed
- **Per page**: ~0.5-1.0 seconds (with Metal GPU)
- **10-page statement**: ~5-10 seconds total
- **Model reuse**: First page loads model, subsequent pages are faster

### Accuracy
- **Depends on**: Statement layout, text quality, transaction format
- **Best for**: Standard transaction formats with clear date/description/amount
- **Challenges**: Non-standard layouts, merged columns, complex formatting

### Token Usage
- **Per page**: ~500 tokens for response
- **Context window**: 512 tokens (sufficient for transaction extraction)

## Advantages Over Generic Parser

### Generic Parser (ML + K-means)
- ❌ No visual context
- ❌ Pattern-based (may miss unusual formats)
- ✅ Fast (~0.1s per page)
- ✅ No AI dependency

### AI Transaction Extraction
- ✅ Uses visual layout
- ✅ Understands context
- ✅ Handles varied formats
- ✅ Can reason about ambiguous cases
- ❌ Slower (~0.5-1s per page)
- ❌ Requires AI model

## Integration Points

### 1. AIBankParser Class
```python
from bank_parsers.ai_parser import AIBankParser

parser = AIBankParser()
parser.set_pdf_path("/path/to/statement.pdf")
transactions = parser.extract_transactions(text)
```

### 2. Direct Function Call
```python
from bank_parsers.ai_detector import extract_transactions_with_ai

transactions = extract_transactions_with_ai("/path/to/statement.pdf")
```

### 3. Automatic (via Registry)
```python
# Automatically used when:
# - Regex detection fails
# - AI detects unknown bank
# - Confidence ≥ 70%
```

## Output Format

Each transaction is a dict with:

```python
{
    'date': datetime.date(2026, 1, 15),
    'description': 'AMAZON.COM',
    'amount': -45.67,
    'category': None  # Will be categorized later
}
```

## Error Handling

### Invalid Transactions
- Missing required fields → Skipped with warning
- Invalid date format → Skipped with warning
- Invalid amount → Skipped with warning

### Page-Level Errors
- JSON parse failure → Warning logged, page skipped
- AI timeout → Page skipped
- Image rendering failure → Page skipped

### Statement-Level Errors
- No transactions found → Returns empty list
- All pages failed → Returns empty list

## Logging

### Console Output
```
🤖 AI detected bank: Wells Fargo
🆕 Using AI parser for unknown bank: Wells Fargo
🤖 Using AI to extract transactions from /path/to/statement.pdf
✅ AI extracted 45 transactions
```

### Unknown Bank Log
```json
{
  "Wells Fargo": {
    "first_seen": "2026-04-03T17:30:00",
    "count": 1,
    "samples": [
      {
        "path": "/path/to/statement.pdf",
        "confidence": 92,
        "date": "2026-04-03T17:30:00"
      }
    ]
  }
}
```

## Configuration

### GPU Acceleration
Automatically uses Metal/CUDA/ROCm if available.

### Model Settings
- Context window: 512 tokens
- Max response tokens: 500 per page
- Temperature: 0 (deterministic)
- Resolution: 150 DPI
- Max image width: 1200px

## Future Improvements

### Potential Enhancements
1. **Batch processing**: Process multiple pages in parallel
2. **Caching**: Cache AI responses for identical pages
3. **Confidence scores**: Return per-transaction confidence
4. **Field validation**: More sophisticated date/amount parsing
5. **Multi-page transactions**: Handle transactions split across pages
6. **Balance tracking**: Extract and validate running balances

### Parser Development Priority
Use `config/unknown_banks.json` to identify which banks to build parsers for:
1. Sort by occurrence count
2. Build regex parser for most common unknown banks
3. Test against sample PDFs
4. Add to registry
5. AI extraction becomes fallback only

## Comparison: AI vs Regex Parsers

| Feature | Regex Parser | AI Parser |
|---------|-------------|-----------|
| Speed | ⚡ Very fast (0.01s) | 🐢 Slower (0.5-1s) |
| Accuracy | ✅ 80-100% (known formats) | ❓ Varies (60-90%) |
| Flexibility | ❌ Format-specific | ✅ Handles variations |
| Visual context | ❌ Text only | ✅ Image + text |
| Development | ⏰ Hours per bank | ✅ Zero setup |
| Maintenance | ⚠️ Breaks on format changes | ✅ Adapts automatically |

## Recommendation

**For Production Use:**
1. **Known banks**: Use dedicated regex parsers (fast, accurate)
2. **Unknown banks**: Use AI extraction (flexible, zero setup)
3. **High-volume unknown banks**: Build regex parser (long-term efficiency)

**Best Practice:**
- Monitor `config/unknown_banks.json`
- Build regex parsers for banks with >10 occurrences
- Keep AI extraction as universal fallback
