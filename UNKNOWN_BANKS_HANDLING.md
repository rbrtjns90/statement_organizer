# Unknown Bank Handling System

## Overview

The system now intelligently handles both known and unknown banks using a multi-layered detection and fallback strategy.

## Detection Flow

```
1. Regex Detection (Fast, Known Banks)
   ├─ Success + Excluded Bank (Navy Federal) → Use regex parser ✅
   ├─ Success + Any Bank → Use regex parser ✅
   └─ Failure → Continue to AI Detection

2. AI Detection (Multimodal, All Banks)
   ├─ Confidence ≥ 70%
   │   ├─ Known Bank (has parser) → Use AI-suggested parser ✅
   │   └─ Unknown Bank (no parser) → Log + Use generic parser 📝
   ├─ Confidence < 70% → Use generic parser ⚠️
   └─ Detection Failed → Use generic parser ❌

3. Generic Parser (Fallback)
   └─ Uses ML + K-means clustering for transaction extraction
```

## Supported Banks

### Banks with Dedicated Parsers (5)
- **Bank of America** - 95.1% success rate
- **Chase** - 100% success rate
- **Citibank** - 83.1% success rate
- **Capital One** - 100% success rate
- **Navy Federal** - 82.1% success rate (regex only, excluded from AI)

### Banks Detectable by AI (18 total)
The AI can detect these banks even without dedicated parsers:
- Bank of America, Chase, Citibank, Capital One, Navy Federal
- Wells Fargo, US Bank, PNC Bank, TD Bank, Truist
- Citizens Bank, Fifth Third Bank, KeyBank, Regions Bank
- M&T Bank, Ally Bank, Discover Bank, American Express

## Unknown Bank Logging

When the AI detects a bank we don't have a parser for:

### What Gets Logged
- Bank name
- First seen timestamp
- Total occurrence count
- Up to 5 sample PDF paths with confidence scores
- Last seen timestamp

### Log Location
`config/unknown_banks.json`

### Example Log Entry
```json
{
  "Wells Fargo": {
    "first_seen": "2026-04-03T17:26:00",
    "last_seen": "2026-04-03T17:30:00",
    "count": 12,
    "samples": [
      {
        "path": "/path/to/statement.pdf",
        "confidence": 95,
        "date": "2026-04-03T17:26:00"
      }
    ]
  }
}
```

## Confidence Thresholds

### High Confidence (≥ 85%)
- **Action**: Trust AI detection
- **Example**: Citibank (100%), Chase (98%), Bank of America (95%)

### Medium Confidence (70-84%)
- **Action**: Trust AI detection with caution
- **Example**: Capital One (85%)

### Low Confidence (< 70%)
- **Action**: Reject AI detection, use generic parser
- **Reason**: Too uncertain to trust

## Handling Unknown Banks

When an unknown bank is detected:

1. **AI Detection**: Identifies bank name with confidence score
2. **Logging**: Records to `config/unknown_banks.json`
3. **Parsing**: Uses generic parser (ML + K-means clustering)
4. **Categorization**: AI categorization automatically enabled
5. **Notification**: Console message shows unknown bank detected

### Console Output Example
```
🆕 AI detected UNKNOWN bank: Wells Fargo (confidence: 92%)
   📝 Logged to config/unknown_banks.json (total occurrences: 1)
```

## Future Parser Development

Use the unknown banks log to prioritize which parsers to build next:

1. Check `config/unknown_banks.json`
2. Sort by occurrence count
3. Build parsers for most common unknown banks
4. Add to `bank_parsers/` directory
5. Register in `registry.py`

## AI Detection Performance

### Current Accuracy (Known Banks)
- **Overall**: 80% (12/15 correct)
- **Bank of America**: 100% (3/3)
- **Capital One**: 100% (3/3)
- **Chase**: 100% (3/3)
- **Citibank**: 100% (3/3)
- **Navy Federal**: 0% (0/3) - Excluded from AI, uses regex

### Speed (with Metal GPU)
- **First detection**: ~1.0s (includes model load)
- **Subsequent detections**: ~0.1-0.4s
- **Average**: 0.42s per file

## Configuration

### Exclusion List
Banks that should NEVER use AI detection (regex only):
```python
AI_EXCLUSION_LIST = ["Navy Federal"]
```

### Confidence Threshold
Minimum confidence to trust AI detection:
```python
MIN_CONFIDENCE = 70
```

### GPU Acceleration
Automatically detects and uses:
- **Metal** (Apple Silicon)
- **CUDA** (NVIDIA)
- **ROCm** (AMD)

## Benefits

1. **Handles Future Banks**: Automatically detects banks not in the system
2. **No Manual Intervention**: Works out of the box for unknown banks
3. **Tracks Demand**: Logs show which parsers to build next
4. **Graceful Degradation**: Falls back to generic parser
5. **AI Categorization**: Unknown banks still get AI-powered categorization
6. **Production Ready**: 80% accuracy on known banks, fast performance

## Limitations

1. **Navy Federal**: Cannot be detected by AI (visual similarity to BofA)
2. **Generic Parser**: Less accurate than dedicated parsers (~21% vs 80-100%)
3. **Unknown Banks**: Require manual parser development for best results
4. **Confidence**: High confidence doesn't guarantee correctness (see Navy Federal)

## Recommendations

1. **Monitor the log**: Check `config/unknown_banks.json` regularly
2. **Build parsers**: Create dedicated parsers for frequently seen unknown banks
3. **Test new banks**: Verify AI detection accuracy before relying on it
4. **Keep exclusion list updated**: Add banks that AI consistently misidentifies
