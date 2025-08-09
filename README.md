# Bank Statement Analyzer & Schedule C Generator

A comprehensive Python application that extracts transactions from bank statement PDFs, categorizes business expenses, and generates filled IRS Schedule C tax forms automatically. Features a modular parser system supporting multiple major banks with intelligent transaction detection and AI-powered categorization.

## 🚀 Features

### 🏦 Multi-Bank Support
- **Navy Federal Credit Union**: Both checking/savings (MM-DD format) and credit card (MM/DD/YY format) statements
- **Capital One**: Credit card statements with transaction/post date format
- **Citibank**: Complex multi-line transaction formats with orphaned amount matching
- **Chase**: Standard and no-date transaction patterns with PayPal support
- **Bank of America**: Traditional bank statement formats
- **Generic Parser**: AI-powered fallback parser using K-means clustering for unknown statement formats
- **Automatic Detection**: Intelligent bank identification from PDF content with fallback support

### 💡 Smart Processing
- **PDF Transaction Extraction**: Automatically extract transactions from bank statement PDFs
- **Modular Parser System**: Plugin-based architecture for easy bank format extension
- **Machine Learning Parser**: K-means clustering algorithm automatically detects transaction patterns in unknown statement formats
- **AI-Powered Categorization**: Optional OpenAI integration for intelligent expense categorization
- **Transaction Management**: Delete, edit, and manage transactions with real-time updates
- **Multiprocessing Support**: Parallel processing for faster PDF analysis

### 📊 Business Tools
- **Schedule C Generation**: Generate filled IRS Schedule C PDFs with correct field mappings
- **Category Management**: Configurable business expense categories with learning capabilities
- **Excel Export**: Detailed transaction reports with category summaries
- **Search & Filter**: Advanced transaction search and filtering capabilities

### 🖥️ User Interface
- **Interactive GUI**: PyQt6-based graphical interface for easy use
- **Visual Field Mapper**: Interactive PyQt6 tool to create and modify PDF field mappings
- **Real-time Status**: Live processing updates and bank detection feedback
- **Context Menus**: Right-click transaction management and bulk operations


## 📋 Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Core Components](#core-components)
- [Usage Guide](#usage-guide)
- [Configuration](#configuration)
- [Advanced Features](#advanced-features)
- [Troubleshooting](#troubleshooting)

## 🛠️ Installation

### Automated Installation (Recommended)

The easiest way to install Statement Organizer is using the automated installer:

1. **Download the project**:
   ```bash
   git clone <repository-url>
   cd statement_organizer
   ```

2. **Run the installer**:
   ```bash
   python3 install.py
   ```

The installer will:
- ✅ Detect your operating system (Windows, macOS, Linux, BSD)
- ✅ Check for Python 3.12+ (download if needed)
- ✅ Install all required dependencies automatically
- ✅ Create executable scripts for easy application launching
- ✅ Set up the config directory structure

### Manual Installation

If you prefer manual installation:

1. **Prerequisites**:
   - Python 3.12+
   - Virtual environment (recommended)

2. **Setup**:
   ```bash
   git clone <repository-url>
   cd statement_organizer
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

### Running Applications

After installation, use the generated scripts:

**Windows:**
```cmd
bank_statement_gui.bat          # Main GUI application
pdf_field_mapper.bat            # PDF field mapping tool
final_schedule_c_filler.bat     # Schedule C PDF processor
```

**Unix (Linux/macOS/BSD):**
```bash
./bank_statement_gui.sh         # Main GUI application
./pdf_field_mapper.sh           # PDF field mapping tool
./final_schedule_c_filler.sh    # Schedule C PDF processor
```



## 🚀 Quick Start

### Method 1: GUI Interface (Recommended)

**Windows:**
```cmd
bank_statement_gui.bat
```

**Unix (Linux/macOS/BSD):**
```bash
./bank_statement_gui.sh
```

1. **Load Bank Statements**: Click "Add PDFs" to select your bank statement files
   - Supports: Navy Federal, Capital One, Citibank, Chase, Bank of America
   - Automatically detects bank format from PDF content
   - Can process multiple banks simultaneously

2. **Configure Categories**: Choose your business categories file (or use default)
   - Optional: Enable AI categorization for intelligent expense classification

3. **Process Transactions**: Click "Process PDFs" to analyze transactions
   - Real-time status updates show bank detection and extraction progress
   - Multiprocessing for faster analysis of multiple files

4. **Manage Transactions**: Review and manage extracted transactions
   - Edit categories with dropdown menus
   - Delete unwanted transactions with right-click or delete button
   - Search and filter transactions by description

5. **Export Results**: Generate reports and tax forms
   - Export to Excel with category summaries
   - Generate filled Schedule C PDF forms

### Method 2: Command Line

```bash
source venv/bin/activate
python final_schedule_c_filler.py
```

This will:
- Process all PDFs in the `Statements/` folder
- Categorize transactions automatically
- Generate `schedule_c_final_filled.pdf`

## 🧩 Core Components

### 1. Modular Bank Parser System (`bank_parsers/`)
Plugin-based architecture for parsing different bank statement formats.

**Key Features:**
- **Auto-Detection**: Automatically identifies bank format from PDF content
- **Extensible Design**: Easy to add new bank parsers by implementing the interface
- **Standardized Output**: All parsers return consistent transaction format
- **Fallback System**: Uses generic parser if bank not recognized

**Supported Banks:**
- `navy_federal.py`: Navy Federal Credit Union (checking & credit card formats)
- `capital_one.py`: Capital One credit card statements
- `citibank.py`: Citibank statements with complex multi-line transactions
- `chase.py`: Chase statements including PayPal and no-date transactions
- `bank_of_america.py`: Bank of America traditional formats

### 2. Bank Statement Analyzer (`bank_statement_analyzer.py`)
The core engine that orchestrates transaction extraction and categorization.

**Key Features:**
- PDF text extraction using pdfplumber
- Modular parser integration with automatic bank detection
- Multiprocessing support for parallel PDF processing
- Pattern-based and AI-powered categorization
- Schedule C data generation with field mapping

### 3. GUI Interface (`bank_statement_gui.py`)
PyQt6-based graphical interface for comprehensive transaction management.

**Features:**
- Multi-bank PDF loading with automatic detection
- Real-time processing progress with bank identification
- Interactive transaction review and editing
- Transaction deletion with confirmation dialogs
- Category management with learning capabilities
- Search and filter functionality
- Export capabilities (Excel and Schedule C PDF)
- **AI-Powered Categorization** (optional)

#### AI Categorization Checkbox

The GUI includes an intelligent **"Use AI Categorization"** checkbox that enhances transaction categorization accuracy:

**🤖 How It Works:**
- **Auto-Detection**: Checkbox automatically enables if `openai.txt` file exists and OpenAI package is installed
- **Smart Processing**: Uses GPT-3.5-turbo to categorize ambiguous transactions
- **Fallback System**: If AI fails, automatically falls back to pattern matching
- **Real-Time Feedback**: Shows AI categorization progress in the status display area

**📋 Categorization Priority:**
1. **Learned Categories** (from previous manual corrections)
2. **AI Categorization** (if enabled and available)
3. **Pattern Matching** (keyword-based)
4. **Default**: "Other Business Expenses"

**⚙️ Setup Requirements:**
- Install OpenAI package: `pip install openai`
- Create `openai.txt` file with your API key
- Checkbox will auto-enable when requirements are met

**💡 Benefits:**
- **Higher Accuracy**: AI understands context better than simple keyword matching
- **Learns Context**: Considers transaction amounts, descriptions, and business categories
- **Cost Effective**: Uses GPT-3.5-turbo for affordable processing
- **Transparent**: Status area shows which transactions are AI-categorized
- **Optional**: Can be disabled to use only pattern matching

### 3. Schedule C Processor (`schedule_c_processor.py`)

**Purpose**: Alternative PDF processing tool

**Key Features:**
- PDF form field analysis
- Direct form filling capabilities
- Schedule C specific processing
- Configurable field mappings export/import

### 4. Final Schedule C Filler (`final_schedule_c_filler.py`)
Generates filled IRS Schedule C PDFs with accurate field mappings.

**Capabilities:**
- JSON-based field mapping configuration
- Automatic PDF form filling
- Multiple mapping strategies
- Error handling and validation

### 5. PDF Field Mapper (`pdf_field_mapper.py`)
Interactive PyQt6 tool for creating and modifying PDF field mappings.

**Features:**
- Visual PDF display with clickable field overlays
- Interactive field selection and mapping
- Business category dropdown selection
- Tree view of current mappings
- Save/load JSON mapping configurations
- Page navigation for multi-page PDFs
- Real-time field highlighting

## 📖 Usage Guide

### Processing Bank Statements

#### Using the GUI

1. **Launch the application**:
   ```bash
   python bank_statement_gui.py
   ```

2. **Load Bank Statement PDFs**:
   - Click "Add PDFs" or drag-and-drop files
   - Select multiple bank statement PDFs from any supported bank
   - **Supported Banks**: Navy Federal, Capital One, Citibank, Chase, Bank of America
   - Application automatically detects bank format from PDF content

3. **Configure Categories & AI**:
   - Use default `business_categories.json` or load custom configuration
   - **Optional**: Enable "Use AI Categorization" checkbox for intelligent expense classification
   - Categories determine how expenses are classified for tax purposes

4. **Process Transactions**:
   - Click "Process PDFs" to start extraction
   - **Real-time Status**: Monitor bank detection and extraction progress
   - **Multiprocessing**: Multiple PDFs processed in parallel for speed
   - Review extracted transactions in the interactive table

5. **Manage Transactions**:
   - **Edit Categories**: Use dropdown menus to change transaction categories
   - **Delete Transactions**: Right-click or use delete button to remove unwanted entries
   - **Search & Filter**: Find specific transactions by description
   - **Bulk Operations**: Apply categories to multiple similar transactions

6. **Export Results**:
   - **Excel Export**: Generate detailed transaction reports with category summaries
   - **Schedule C PDF**: Create filled IRS tax forms with expense totals
   - **Category Learning**: System remembers manual corrections for future processing

#### Using Command Line

1. **Place PDFs in Statements folder**:
   ```bash
   mkdir -p Statements
   cp your_bank_statements.pdf Statements/
   ```

2. **Run the processor**:
   ```bash
   python final_schedule_c_filler.py
   ```

3. **Check output**:
   - Generated PDF: `schedule_c_final_filled.pdf`
   - Processing logs show categorization details

### Creating Custom Field Mappings

Use the interactive field mapper to create custom PDF mappings:

1. **Launch the field mapper**:
   ```bash
   python pdf_field_mapper.py
   ```

2. **Open your PDF form**:
   - Click "Open PDF"
   - Select the PDF form you want to map
   - Navigate through pages if needed

3. **Map fields visually**:
   - Red overlays show available form fields
   - Click on a field to select it
   - Choose expense category from dropdown
   - Click "Map Selected Field"

4. **Save configuration**:
   - Click "Save Mapping"
   - Export as JSON file
   - Use with Schedule C processor

## 🎯 Visual Field Mapping

Use the interactive GUI to create accurate PDF field mappings:

1. **Launch the field mapper**:
   ```bash
   python pdf_field_mapper.py
   ```

2. **Open your PDF form**:
   - Click "Open PDF"
   - Select the PDF form you want to map
   - Navigate through pages if needed

3. **Map fields visually**:
   - Red overlays show available form fields
   - Click on a field to select it
   - Choose expense category from dropdown
   - Click "Map Selected Field"

4. **Save configuration**:
   - Click "Save Mapping"
   - Export as JSON file
   - Use with Schedule C processor

## 🏗️ Bank Parser Architecture

The modular parser system enables support for multiple bank statement formats through a plugin-based architecture:

### Parser Interface

All bank parsers implement the `BankStatementParser` interface:

```python
class BankStatementParser:
    def can_parse(self, text: str) -> bool:
        """Detect if this parser can handle the PDF content"""
        
    def extract_transactions(self, text: str) -> List[Dict]:
        """Extract transactions with bank-specific logic"""
        
    def get_account_info(self, text: str) -> Dict:
        """Extract account metadata (number, dates, etc.)"""
```

### Automatic Bank Detection

The system automatically identifies bank formats using unique identifiers:

- **Navy Federal**: "Navy Federal", "NFCU", "Navy Federal Credit Union"
- **Capital One**: "Capital One", "capitalone.com", "CAPITAL ONE"
- **Citibank**: "Citibank", "CITI", "citicards.com"
- **Chase**: "Chase", "JPMorgan Chase", "CHASE CARD SERVICES"
- **Bank of America**: "Bank of America", "BofA", "bankofamerica.com"

### Parser Registry

The `BankParserRegistry` manages parser detection and priority:

```python
# Priority order (highest to lowest)
1. Navy Federal Credit Union
2. Capital One  
3. Citibank
4. Chase
5. Bank of America
6. Generic fallback parser
```

### Adding New Banks

To add support for a new bank:

1. **Create parser file**: `bank_parsers/new_bank.py`
2. **Implement interface**: Extend `BankStatementParser`
3. **Add detection logic**: Unique bank identifiers
4. **Register parser**: Add to `bank_parsers/registry.py`
5. **Test thoroughly**: Create test cases for various statement formats

### Transaction Format Standards

All parsers return transactions in this standardized format:

```python
{
    'date': datetime.date,
    'description': str,
    'amount': float,
    'category': str,
    'transaction_type': str  # 'debit' or 'credit'
}
```

## 🎯 Configuration Management

The system uses JSON configuration files stored in the `config/` folder:

1. **Business Categories** (`config/business_categories.json`):
   - Define expense categorization rules
   - Add keywords for automatic matching
   - Customize categories for your business

2. **Field Mappings** (`config/schedule_c_field_mappings.json`):
   - Maps business categories to PDF form fields
   - Uses precise field patterns (f1_35, f1_27, etc.)
   - Ensures accurate form filling

3. **Schedule C Form** (`config/schedule_c.pdf`):
   - Official IRS Schedule C form
   - Used as template for filling
   - Must be a fillable PDF form

## ⚙️ Configuration

### Business Categories (`config/business_categories.json`)

Define how transactions are categorized:

```json
{
  "Meals & Entertainment": [
    "restaurant",
    "cafe",
    "doordash"
  ],
  "Software & Subscriptions": [
    "github",
    "aws",
    "google cloud"
  ],
  "Marketing": [
    "facebook ads",
    "google ads"
  ]
}
```

**Structure:**
- **Keys**: Business expense categories
- **Values**: Arrays of keywords/patterns to match

### PDF Field Mappings (`config/schedule_c_field_mappings.json`)

Maps expense categories to PDF form fields:

```json
{
  "schedule_c_mappings": {
    "Car and truck expenses": {
      "line": "9",
      "field_pattern": "f1_36",
      "description": "Schedule C Line 9"
    }
  }
}
```

**Fields:**
- **line**: IRS Schedule C line number
- **field_pattern**: PDF form field identifier
- **description**: Human-readable description



## 🔧 Advanced Features

### Generic Parser with Machine Learning

The system includes an advanced **Generic Parser** that uses machine learning to automatically detect transaction patterns in unknown statement formats:

#### How It Works
1. **K-means Clustering**: Groups PDF lines by layout features (position, money presence, dates, text characteristics)
2. **Pattern Detection**: Automatically generates regex patterns for transaction extraction
3. **Smart Filtering**: Removes summary/header content using keyword detection
4. **Fallback Support**: Activates when bank-specific parsers fail

#### Technical Features
- **Layout Analysis**: Analyzes PDF character positioning and line structure
- **Feature Extraction**: Uses 13+ features including money patterns, date presence, and spatial positioning
- **Automatic Regex Generation**: Creates custom regex patterns based on detected transaction clusters
- **Multi-format Support**: Handles various date formats, currency symbols, and layout styles

#### Usage
The Generic Parser automatically activates as a fallback when:
- No specific bank parser can handle the PDF
- Statement format is unknown or unsupported
- Bank-specific parser fails to extract transactions

```python
# The Generic Parser is automatically registered and used
from bank_parsers.generic_regex import GenericRegexParser

# Test if a PDF can be parsed
parser = GenericRegexParser()
if parser.can_parse(pdf_text):
    transactions = parser.extract_transactions(pdf_text)
```

#### Dependencies
Requires additional machine learning packages:
```bash
pip install scikit-learn numpy pandas
```

### Custom Transaction Patterns

Extend transaction recognition by modifying `extract_transactions()` in `bank_statement_analyzer.py`:

```python
# Add custom patterns for your bank's format
transaction_patterns = [
    r'(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?\$?[\d,]+\.?\d*)',
    # Add your bank's specific pattern here
]
```

### Multiple PDF Formats

The system supports various bank statement formats:
- Standard date-description-amount layouts
- Multi-column formats
- Different date formats (MM/DD/YYYY, DD/MM/YYYY)

### Batch Processing

Process multiple months/years of statements:

```python
from bank_statement_analyzer import BankStatementAnalyzer

analyzer = BankStatementAnalyzer()
pdf_files = glob.glob("Statements/*.pdf")
analyzer.extract_from_multiple_pdfs(pdf_files)
analyzer.categorize_transactions()
data = analyzer.generate_schedule_c_data()
```

### Export Options

Export data in multiple formats:

```python
# Export to Excel
analyzer.export_to_excel("transactions.xlsx")

# Export to CSV
df = analyzer.get_transactions_dataframe()
df.to_csv("transactions.csv", index=False)

# Export Schedule C data
schedule_data = analyzer.generate_schedule_c_data()
with open("schedule_c_data.json", "w") as f:
    json.dump(schedule_data, f, indent=2)
```

### Testing the Generic Parser

The system includes a comprehensive test suite for evaluating the Generic Parser's performance:

#### Running the Test Suite

```bash
# Activate virtual environment
source venv_new/bin/activate

# Run comprehensive tests on all PDFs
python test_generic_parser.py
```

#### Test Results
The test script evaluates:
- **Success Rate**: Percentage of PDFs successfully parsed
- **Transaction Count**: Number of transactions extracted per file
- **Parser Comparison**: Generic parser vs bank-specific parsers
- **Performance Metrics**: Processing time and accuracy

#### Sample Output
```
GENERIC PARSER TEST RESULTS
============================================================
Total files tested: 20
Successful extractions: 5
Success rate: 25.0%

Top performing files:
  1. 2024-09-09_VISASTMT.pdf: 16 transactions
  2. Statement_012025_9746.pdf: 24 transactions
  3. Statement_022025_9746.pdf: 20 transactions
```

#### Interpreting Results
- **High transaction counts**: Indicates good pattern detection
- **Low success rates**: May indicate need for additional training data
- **Zero transactions**: Could indicate PDF format incompatibility

#### Improving Performance
To enhance Generic Parser accuracy:
1. **Add training data**: Include more diverse PDF formats in K_cluster_test/
2. **Adjust clustering parameters**: Modify n_clusters in `cluster_transactions()`
3. **Update filtering keywords**: Enhance `summary_keywords` list
4. **Refine regex patterns**: Improve date and money detection patterns

## 🐛 Troubleshooting

### Common Issues

#### PDF Processing Errors

**Problem**: "No transactions found in PDF"
**Solution**: 
- Verify PDF is text-based (not scanned image)
- Check if PDF format matches expected patterns
- Try different PDF extraction methods

#### Field Mapping Issues

**Problem**: "Numbers appear in wrong PDF fields"
**Solution**:
- Use the visual field mapper tool
- Create custom field mapping configuration
- Verify PDF form field names

#### Categorization Problems

**Problem**: "Transactions not categorized correctly"
**Solutions**:
- Update `business_categories.json` with better keywords
- Add specific merchant names to categories
- Update business categories with more specific keywords

### Performance Optimization

For large numbers of PDFs:

1. **Process in batches**:
   ```python
   # Process 10 PDFs at a time
   for batch in chunks(pdf_files, 10):
       analyzer.extract_from_multiple_pdfs(batch)
   ```

2. **Use multiprocessing**:
   ```python
   from multiprocessing import Pool
   
   with Pool() as pool:
       results = pool.map(process_pdf, pdf_files)
   ```

### Debug Mode

Enable detailed logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

analyzer = BankStatementAnalyzer()
# Detailed logs will show extraction and categorization steps
```

## 📁 Project Structure

```
statement_organizer/
├── config/                        # Configuration files
│   ├── business_categories.json   # Expense categorization rules
│   ├── schedule_c_field_mappings.json # PDF field mappings
│   ├── learned_categories.json    # Learned categorization patterns
│   └── schedule_c.pdf             # IRS Schedule C form template
├── bank_parsers/                  # Modular bank parser system
│   ├── __init__.py               # Parser base classes and registry
│   ├── registry.py               # Parser registration and detection
│   ├── navy_federal.py           # Navy Federal Credit Union parser
│   ├── capital_one.py            # Capital One parser
│   ├── citibank.py               # Citibank parser
│   ├── chase.py                  # Chase parser
│   ├── bank_of_america.py        # Bank of America parser
│   └── generic_regex.py          # ML-powered generic parser
├── K_cluster_test/               # Machine learning parser development
│   ├── regex_builder.py          # Original K-means clustering implementation
│   ├── requirements.txt          # ML-specific dependencies
│   └── *.pdf                     # Test PDF files
├── bank_statement_analyzer.py     # Core transaction extraction
├── bank_statement_gui.py          # Main GUI interface
├── final_schedule_c_filler.py     # Main PDF form filler
├── schedule_c_processor.py        # Alternative Schedule C processor
├── pdf_field_mapper.py            # Field mapping utilities
├── create_categories.py           # Category creation tool
├── test_generic_parser.py         # Generic parser test suite
├── requirements.txt               # Python dependencies
├── .gitignore                     # Git ignore rules
├── venv/                          # Virtual environment
└── README.md                      # This file
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the GNU GPL3 License - see the LICENSE file for details.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section
2. Review the configuration files
3. Enable debug logging for detailed information
4. Create an issue with detailed error information

---

**Note**: This tool is designed to assist with tax preparation but should not replace professional tax advice. Always review generated forms and consult with a tax professional for complex situations.
