# Bank Statement Analyzer & Schedule C Generator

A comprehensive Python application that extracts transactions from bank statement PDFs, categorizes business expenses, and generates filled IRS Schedule C tax forms automatically.

## 🚀 Features

- **PDF Transaction Extraction**: Automatically extract transactions from bank statement PDFs
- **Smart Categorization**: Intelligent expense categorization using configurable business categories
- **Schedule C Generation**: Generate filled IRS Schedule C PDFs with correct field mappings
- **Interactive GUI**: PyQt6-based graphical interface for easy use
- **Visual Field Mapper**: Interactive PyQt6 tool to create and modify PDF field mappings
- **JSON Configuration**: Flexible configuration system for PDF field mappings
- **Configurable Categories**: JSON-based business expense categories


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

1. Click "Add PDFs" to select your bank statement files
2. Choose your business categories file (or use default)
3. Click "Process PDFs" to analyze transactions
4. Review and edit categorizations
5. Generate Schedule C PDF

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

### 1. Bank Statement Analyzer (`bank_statement_analyzer.py`)
The core engine that extracts and categorizes transactions.

**Key Features:**
- PDF text extraction using pdfplumber
- Transaction pattern recognition
- Pattern-based categorization
- Schedule C data generation

### 2. GUI Interface (`bank_statement_gui.py`)
PyQt6-based graphical interface for easy interaction.

**Features:**
- Drag-and-drop PDF loading
- Real-time processing progress
- Interactive transaction review
- Category editing and management
- Export capabilities

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

2. **Load PDFs**:
   - Click "Add PDFs" or drag-and-drop files
   - Select multiple bank statement PDFs
   - Files should be in standard bank statement format

3. **Configure Categories**:
   - Use default `business_categories.json`
   - Or load custom category configuration
   - Categories determine how expenses are classified

4. **Process Transactions**:
   - Click "Process PDFs"
   - Monitor progress in the status bar
   - Review extracted transactions in the table

5. **Review and Edit**:
   - Check transaction categorizations
   - Edit categories using dropdown menus
   - Add or modify business rules

6. **Generate Schedule C**:
   - Click "Generate Schedule C"
   - Review expense totals by category
   - Export filled PDF form

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
├── bank_statement_analyzer.py     # Core transaction extraction
├── bank_statement_gui.py          # Main GUI interface
├── final_schedule_c_filler.py     # Main PDF form filler
├── schedule_c_processor.py        # Alternative Schedule C processor
├── pdf_field_mapper.py            # Field mapping utilities
├── create_categories.py           # Category creation tool
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
