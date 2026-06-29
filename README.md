# Bank Statement Analyzer & Schedule C Generator

A Python application that extracts transactions from bank statement PDFs, categorizes business expenses, and generates filled IRS Schedule C tax forms. Built on a **correctness-first architecture** that verifies every extraction against the statement's own totals — and falls back to AI (local model or OpenAI) only when deterministic extraction can't be verified.

The system handles **text-layer PDFs** (native digital statements) and **image-only PDFs** (scanned statements, via OCR), from **known banks** (with layout profiles) and **unknown banks** (via AI-assisted profile generation).

---

## 🚀 Features

### ✅ Correctness-first extraction
- **Reconciliation-gated**: every extraction is checked against the statement's self-declared totals (Previous/New Balance, Total Charges, deposits/withdrawals, or per-row running balances). If the sum doesn't match, the extraction is flagged — never silently wrong.
- **Four reconciliation strategies** cover every statement type:
  - `charges_total` — credit cards (Capital One, Citi, NFCU Visa)
  - `balance_equation` — `PreviousBalance + Charges − Payments + Interest + Fees = NewBalance`
  - `running_balance_chain` — checking accounts with per-row balances (Navy Federal)
  - `deposits_withdrawals` — checking accounts with totals (Bank of America)
- **Geometry extraction**: transaction amounts right-align at fixed x-coordinates per bank. The extractor clusters word positions to detect columns — far more reliable than line-based regex.
- **Honest evaluation**: the `eval/` harness measures real reconciliation rates against statement totals, not self-referential "accuracy."

### 🤖 AI on demand ("use the model if you have to")
- **Unified AI client** (`bank_parsers/ai_client.py`): one interface, local model first → OpenAI fallback. Statement content stays on-machine when a local model is installed.
- **AI as repair, not primary**: when reconciliation fails, the AI gets a *targeted* task ("find the missing $X") rather than open-ended re-extraction.
- **AI-assisted profile generation**: for unknown banks, the vision model identifies column roles + totals labels, and geometry measures exact coordinates — bootstrapping a layout profile on the fly.
- **Local-first**: runs on a local Gemma 4 GGUF model (private, $0/call). OpenAI (`gpt-4o-mini`) is the fallback.

### 🏦 Multi-bank support
- **Known banks** (layout profiles): Capital One, Bank of America, Chase, Citibank, Navy Federal (both checking and Visa layouts)
- **Unknown banks**: auto-detected column geometry + AI-generated profiles
- **Image-only PDFs**: OCR-geometry bridge (macOS Vision or cross-platform Tesseract)

### 📊 Business tools
- **Schedule C generation**: filled IRS Schedule C PDFs with field mappings
- **Categorization**: learned categories → normalized keyword match → AI, with fuzzy acceptance
- **Description normalization**: strips card prefixes, reference numbers, and glued state codes before matching
- **Excel/JSON export**: transaction reports with category summaries

### 🖥️ GUI
- PyQt6 interface with real-time status, bank detection feedback, and the active AI backend shown
- Visual PDF field mapper for Schedule C form configuration

---

## 📋 Table of Contents
- [Installation](#-installation)
- [Quick Start](#-quick-start)
- [How It Works](#-how-it-works-the-correctness-first-architecture)
- [Configuration](#-configuration)
- [Evaluation](#-evaluation)
- [Project Structure](#-project-structure)
- [Troubleshooting](#-troubleshooting)

---

## 🛠️ Installation

### Automated (recommended)
```bash
git clone <repository-url>
cd statement_organizer
python3 install.py
```
The installer detects your OS, checks Python 3.12+, installs dependencies, and creates launcher scripts.

### Manual
```bash
git clone <repository-url>
cd statement_organizer
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Optional system dependencies

**OCR (for scanned/image-only PDFs):**
- macOS: Vision framework is built-in (no install needed)
- Linux: `sudo apt install tesseract-ocr`
- Windows: install [Tesseract](https://github.com/UB-Mannheim/tesseract)

**Local AI model (optional, for on-device AI):**
```bash
python download_model.py
```
This detects your hardware (RAM, GPU/VRAM) and recommends the best Gemma 4 model variant (E2B, E4B, 12B, 26B-A4B, or 31B) and quantization that fits, then downloads it. You can also pick explicitly:
```bash
python download_model.py --list                          # show recommendations only
python download_model.py --variant 12B --quant Q4_K_M    # download a specific model
```
Or set `preferred_backend: "openai"` in `config/ai_settings.json` to use the API instead. See [AI Configuration](#ai-configuration).

---

## 🚀 Quick Start

### GUI
```bash
# Unix
./bank_statement_gui.sh
# Windows
bank_statement_gui.bat
```
1. Click **Add PDFs** to load statements (any supported bank, auto-detected)
2. Optionally enable **AI Categorization**
3. Click **Process PDFs** — watch the status bar for bank detection + reconciliation results
4. Review/edit transactions, then **Export** to Excel or generate a Schedule C PDF

### Command line
```bash
source venv/bin/activate
python final_schedule_c_filler.py   # processes Statements/*.pdf → schedule_c_final_filled.pdf
```

### Single PDF via the analyzer
```bash
python bank_statement_analyzer.py path/to/statement.pdf -o output.xlsx
```

---

## 🧠 How It Works: the correctness-first architecture

### The core insight
A bank statement is a **self-balancing document** — it states its own totals. If `sum(extracted_transactions) ≠ stated_total`, the extraction is *provably wrong*, and no AI judgment is needed to detect it. This reconciliation is the correctness gate.

### The pipeline
```
PDF
 │
 ├─ Text-layer? ──── yes ──→ geometry extraction (word x-coordinates)
 │                              │
 ├─ Image-only? ──── yes ──→ OCR (Vision/Tesseract) with bounding boxes → geometry
 │                              │
 │                              ▼
 │                    Layout profile (known bank) or AI-generated (unknown bank)
 │                              │
 │                              ▼
 │                    Transaction extraction (date | description | amount)
 │                              │
 │                              ▼
 │                    Reconciliation (sum vs stated totals)
 │                       ├─ reconciled ✓ → done (provably correct, no AI)
 │                       └─ mismatch ✗  → targeted AI repair → re-reconcile
```

### Modules

| Module | Role |
|--------|------|
| `geometry_extractor.py` | Reconstructs transaction lines from word x/y coordinates; detects amount/date/balance columns |
| `layout_profiles.py` | Declarative per-bank layout knowledge (column positions, totals labels); multi-layout support (e.g. NFCU checking vs Visa) |
| `reconciler.py` | The correctness oracle — 4 strategies (charges, balance equation, running-balance chain, deposits/withdrawals) |
| `reconciliation_pipeline.py` | Orchestrates: geometry → reconcile → targeted AI repair |
| `ocr_geometry_bridge.py` | OCR with bounding boxes (macOS Vision or Tesseract) → word dicts the geometry extractor consumes |
| `ai_client.py` | Unified local (Gemma 4) → OpenAI fallback client |
| `ai_profile_generator.py` | Hybrid profile generation for unknown banks (AI roles + geometry coordinates) |
| `categorizer.py` | Learned → keyword → AI categorization with fuzzy acceptance |
| `description_normalizer.py` | Strips bank noise from raw descriptions before matching |
| `transaction_filters.py` | Universal summary-row + dedup filtering (fixes junk-row leaks) |
| `format_memory.py` | Remembers layouts so recurring unknown banks skip AI on future runs |
| `eval/run_eval.py` | Honest ground-truth evaluation harness |
| `ai_detector.py` | AI bank detection + vision extraction (legacy/repair path) |
| `extraction_pipeline.py` | The earlier confidence-gated pipeline (still used by the legacy GUI path) |

---

## ⚙️ Configuration

### AI configuration (`config/ai_settings.json`)
```json
{
  "preferred_backend": "auto",          // "local" | "openai" | "auto"
  "local_supports_vision": true,        // true once a vision GGUF + mmproj are installed
  "openai_model": "gpt-4o-mini",
  "extraction_confidence_threshold": 50
}
```
- **`preferred_backend: "auto"`** (default): tries local model first, falls back to OpenAI
- **`preferred_backend: "local"`**: local only (private, $0); OpenAI never contacted
- **`preferred_backend: "openai"`**: OpenAI only

### AI configuration (continued)
- **Local model**: place a multimodal GGUF (e.g. `gemma-4-e2b-it-Q8_0.gguf`) + its mmproj file in `models/`. Set `local_supports_vision: true`.
- **OpenAI**: place your API key in `config/openai.txt`. The key is gitignored.
- **Neither present**: the system runs deterministically only; AI escalation is skipped gracefully.

### Categories (`config/business_categories.json`)
Maps each category to a list of keyword phrases. Edit this to tune categorization — the eval harness (`eval/category_eval.py`) flags suspect categorizations to guide tuning.

### Learned categories (`config/learned_categories.json`)
Merchant → category mappings accumulated from manual corrections in the GUI. These take priority in the categorization cascade.

---

## 📊 Evaluation

The system measures real correctness via reconciliation, not self-referential accuracy.

### Run the eval harness
```bash
python eval/run_eval.py                      # whole corpus
python eval/run_eval.py --bank "Capital One" # one bank
python eval/run_eval.py --limit 20           # quick sample
```
Reports per-bank: reconciliation rate (% that balance to the cent), mean discrepancy ($), rows extracted, and which strategy was used.

### Category evaluation
```bash
python eval/category_eval.py --pdf "path/to/statement.pdf" --report
```
Flags likely mis-categorizations (e.g. a gas-station name in a non-Travel category) and can emit a label template for human review.

### Current results (balanced 20-PDF sample)
| Bank | Reconciliation rate | Strategy |
|------|---------------------|----------|
| Bank of America | 100% | deposits_withdrawals / balance_equation |
| Chase | 100% | balance_equation |
| Citibank | 100% | charges_total |
| Navy Federal | 75% | running_balance_chain (checking) / charges_total (Visa) |
| Capital One | 50% | charges_total |

Overall ~85% of statements reconcile to the cent. The remainder are flagged with exact dollar discrepancies for review.

---

## 📁 Project Structure

```
statement_organizer/
├── bank_parsers/                       # Core extraction engine
│   ├── geometry_extractor.py           # Word-geometry transaction extraction
│   ├── layout_profiles.py              # Per-bank layout profiles (multi-layout)
│   ├── reconciler.py                   # Totals reconciliation (4 strategies)
│   ├── reconciliation_pipeline.py      # Geometry → reconcile → AI repair
│   ├── ocr_geometry_bridge.py          # OCR (Vision/Tesseract) → geometry
│   ├── ai_client.py                    # Unified local→OpenAI AI client
│   ├── ai_profile_generator.py         # AI-assisted profile generation
│   ├── categorizer.py                  # Learned→keyword→AI categorization
│   ├── description_normalizer.py       # Bank-noise stripping
│   ├── transaction_filters.py          # Summary-row + dedup filtering
│   ├── transaction_validation.py       # Well-formedness validation
│   ├── format_memory.py                # Layout learning loop
│   ├── log_utils.py                    # Capped log rotation
│   ├── ai_detector.py                  # AI bank detection + vision extraction
│   ├── ai_parser.py                    # AI parser adapter
│   ├── extraction_pipeline.py          # Confidence-gated pipeline (legacy GUI path)
│   ├── text_extraction.py              # Unified text-extraction backends
│   ├── vision_ocr.py                   # macOS Vision OCR
│   ├── image_normalization.py          # OCR image preprocessing
│   ├── bank_detection.py               # Multi-stage bank detection
│   ├── registry.py                     # Parser registry + dispatch
│   ├── __init__.py                     # Parser base class + registry
│   ├── navy_federal.py                 # Navy Federal regex parser
│   ├── capital_one.py                  # Capital One regex parser
│   ├── citibank.py                     # Citibank regex parser
│   ├── chase.py                        # Chase regex parser
│   ├── bank_of_america.py              # Bank of America regex parser
│   ├── generic_regex.py                # K-means generic fallback parser
│   └── ml_parser.py                    # LightGBM row classifier
├── eval/                               # Evaluation harness
│   ├── run_eval.py                     # Reconciliation evaluation
│   └── category_eval.py                # Categorization evaluation
├── config/                             # Configuration
│   ├── ai_settings.json                # AI backend + thresholds
│   ├── business_categories.json        # Category → keywords
│   ├── learned_categories.json         # Merchant → category (learned)
│   ├── schedule_c_field_mappings.json  # Schedule C PDF field map
│   └── schedule_c.pdf                  # IRS Schedule C template
├── models/                             # Local AI models (gitignored — downloadable)
├── Statements/                         # Input PDF statements (gitignored)
├── bank_statement_analyzer.py          # Core analyzer + CLI
├── bank_statement_gui.py               # PyQt6 GUI
├── final_schedule_c_filler.py          # Schedule C PDF generator
├── pdf_field_mapper.py                 # Visual field-mapping tool
├── install.py                          # Cross-platform installer
├── requirements.txt                    # Dependencies
└── README.md                           # This file
```

---

## 🐛 Troubleshooting

### "No transactions extracted"
- **Image-only PDF**: ensure an OCR backend is installed (macOS Vision built-in; Tesseract elsewhere). The system auto-detects and OCRs.
- **Unknown bank**: the AI profile generator should kick in. Check that an AI backend (local model or OpenAI key) is configured.
- Run `python eval/run_eval.py --pdf <path>` to see exactly what happened (extraction count, reconciliation result, discrepancy).

### "Reconciliation mismatch" (non-zero discrepancy)
This is the system **working correctly** — it detected an extraction error. The discrepancy tells you exactly how much is off:
- Small discrepancy ($1–20): likely a single mis-extracted transaction. Check the eval output for which row.
- Large discrepancy: likely a sign-convention issue or a missed/extra block of transactions. Review the profile for that bank.

### "Transactions not categorized correctly"
- Run `python eval/category_eval.py --pdf <path> --report` to see flagged miscategorizations.
- Edit `config/business_categories.json` to add keywords for miscategorized merchants.
- Enable AI categorization (GUI checkbox or `config/ai_settings.json`) for merchants keyword matching can't handle.

### Slow processing
- Local AI model inference is the slowest step. If reconciliation passes deterministically, no AI is called — that's the fast path.
- For large batches, the categorizer uses batched AI calls (configurable via `categorization_batch_size` in `ai_settings.json`).

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Run `python eval/run_eval.py` to establish a baseline reconciliation rate
4. Make your changes
5. Re-run the eval to confirm no regression
6. Submit a pull request

---

## 📄 License

GNU GPL3 — see the [LICENSE](LICENSE) file.

---

**Note**: This tool assists with tax preparation but does not replace professional tax advice. Always review generated forms and consult a tax professional for complex situations. The reconciliation system verifies extraction completeness, but categorization accuracy depends on your category configuration and AI backend.
