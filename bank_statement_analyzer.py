#!/usr/bin/env python3
"""
Bank Statement Analyzer
----------------------
Core engine that orchestrates transaction extraction (via the reconciliation
pipeline or the legacy extraction pipeline), categorization, and Schedule C
generation. Exposes BankStatementAnalyzer, the class used by the GUI, CLI,
and Schedule C filler.

This module is the user-facing API. The heavy lifting lives in bank_parsers/.
"""

import argparse
import json
import os
import re
from datetime import date, datetime

import pandas as pd
import pdfplumber
from dateutil import parser as date_parser


class BankStatementAnalyzer:
    """Main class for analyzing bank statements and categorizing transactions."""

    # Default categories for business expenses
    DEFAULT_CATEGORIES = {
        "Office Supplies": ["staples", "office depot", "amazon", "office supplies"],
        "Travel & Transportation": [
            "airline", "hotel", "airbnb", "uber *trip", "lyft", "taxi",
            "rental car", "love's", "mobile purchase",
        ],
        "Meals & Entertainment": [
            "restaurant", "cafe", "coffee", "doordash", "grubhub",
            "ubereats", "uber *eats",
        ],
        "Software & Subscriptions": [
            "github", "aws", "google cloud", "microsoft", "zoom", "slack", "adobe",
        ],
        "Marketing": ["facebook ads", "google ads", "marketing", "advertising"],
        "Professional Services": ["lawyer", "accountant", "consulting", "legal"],
        "Insurance": ["freedom life ins", "ins. prem", "ngic", "delta dental", "insurance"],
        "Banking & Credit": ["citi autopay", "payment", "transfer", "banking"],
        "Utilities": ["phone", "internet", "electricity", "water", "gas"],
        "Rent": ["rent", "lease", "coworking"],
        "Other Business Expenses": [],
    }

    def __init__(self, categories=None):
        """Initialize with optional custom categories.

        If no categories are passed, load from config/business_categories.json
        (the consolidated source of truth). Falls back to DEFAULT_CATEGORIES
        only if that file is missing.
        """
        if categories is None:
            categories = self._load_categories_from_config()
        self.categories = categories
        self.transactions = []
        self.learned_categories = {}
        self.learned_categories_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "config",
            "learned_categories.json",
        )
        self.use_ai = False
        self.ai_backend = ""
        self.n_ctx = 2048
        self.local_model_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "models",
            "gemma-4-e2b-it-Q8_0.gguf",
        )
        self.status_callback = None
        self._last_categorization_stats = None
        self._load_learned_categories()

    @staticmethod
    def _load_categories_from_config():
        """Load category keywords from config/business_categories.json.

        Falls back to DEFAULT_CATEGORIES if the file is missing or unreadable.
        """
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "config",
            "business_categories.json",
        )
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and data:
                return data
        except Exception as exc:
            print(f"Warning: could not load {path}, using default categories: {exc}")
        return BankStatementAnalyzer.DEFAULT_CATEGORIES

    def set_status_callback(self, callback):
        """Set a callback function for status updates during processing."""
        self.status_callback = callback

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    def extract_from_pdf(self, pdf_path):
        """Extract transactions from a PDF bank statement.

        Uses the reconciliation-driven pipeline (geometry extraction + totals
        reconciliation + targeted AI repair) when available; falls back to the
        confidence-gated extraction pipeline.
        """
        print(f"Processing {pdf_path}...")
        try:
            from bank_parsers.reconciliation_pipeline import ReconciliationPipeline

            pipe = ReconciliationPipeline(status_callback=self.status_callback)
            result = pipe.extract(pdf_path)
            self.transactions = result.transactions
            bank = result.bank or "Unknown"
            recon = result.reconciliation
            if recon:
                verdict = "reconciled" if recon.reconciled else f"discrepancy ${recon.discrepancy:.2f}"
                print(
                    f"Extracted {result.count} transactions from {bank} "
                    f"({result.method}, {verdict})"
                )
            else:
                print(f"Extracted {result.count} transactions from {bank} ({result.method})")
            return self.transactions
        except Exception as exc:
            print(f"Reconciliation pipeline failed, falling back to legacy: {exc}")
            return self._extract_legacy(pdf_path)

    def _extract_legacy(self, pdf_path):
        """Legacy fallback: text extraction + inline regex parsing.

        Uses a SINGLE detection call (detect_bank) then looks up the parser by
        bank name — no redundant per-parser can_parse scan.
        """
        from bank_parsers.registry import detect_bank, initialize_parsers, get_parser_for_bank
        from bank_parsers.transaction_filters import clean_transactions

        initialize_parsers()
        text = self._extract_text_from_pdf(pdf_path)
        if not text.strip():
            return []
        bank = detect_bank(text, pdf_path)
        parser = get_parser_for_bank(bank)
        if parser:
            raw = parser.extract_transactions(text)
            self.transactions = clean_transactions(raw)
        return self.transactions

    def extract_from_multiple_pdfs(self, pdf_paths, use_multiprocessing=True):
        """Extract transactions from multiple PDF bank statements."""
        original_transactions = self.transactions.copy()
        self.transactions = []
        for pdf_path in pdf_paths:
            self.extract_from_pdf(pdf_path)
        # Sort all transactions by date where possible. Dates from the pipeline
        # are now normalized to datetime.date, but guard against None and any
        # legacy string that slipped through — None sorts to the end.
        def _sort_key(txn):
            d = txn.get("date")
            if isinstance(d, (datetime, date)):
                return (0, d)
            return (1, str(d) if d is not None else "")
        try:
            self.transactions.sort(key=_sort_key)
        except (TypeError, ValueError):
            pass
        return self.transactions

    @staticmethod
    def _extract_text_from_pdf(pdf_path):
        """Extract all text from a PDF using pdfplumber."""
        parts = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    parts.append(page.extract_text() or "")
        except Exception as exc:
            print(f"Text extraction error: {exc}")
        return "\n".join(parts)

    def extract_transactions_from_pdf(self, pdf_path):
        """Alias for extract_from_pdf (backward compat)."""
        return self.extract_from_pdf(pdf_path)

    # ------------------------------------------------------------------
    # Categorization
    # ------------------------------------------------------------------
    def categorize_transactions(self, use_multiprocessing=True):
        """Categorize all transactions.

        Delegates to the unified Categorizer (bank_parsers/categorizer.py),
        which normalizes descriptions before matching, accepts fuzzy AI results,
        and routes AI calls through the local -> OpenAI AIClient fallback.
        """
        uncategorized = [
            t for t in self.transactions
            if "category" not in t or t["category"] is None
        ]
        if not uncategorized:
            from bank_parsers.categorizer import CategorizationStats
            self._last_categorization_stats = CategorizationStats()
            return

        from bank_parsers.categorizer import Categorizer, load_categories

        categories = self.categories if isinstance(self.categories, dict) else load_categories()
        categorizer = Categorizer(
            categories=categories,
            learned=self.learned_categories,
            use_ai=self.use_ai if self.use_ai else None,
            status_callback=self.status_callback,
        )
        stats = categorizer.categorize(self.transactions, parallel=use_multiprocessing)
        if stats.ai_backend:
            self.ai_backend = stats.ai_backend
        self._last_categorization_stats = stats

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    def save_to_excel(self, output_path):
        """Save transactions to an Excel file with category summaries."""
        if not self.transactions:
            print("No transactions to save.")
            return
        rows = []
        for t in self.transactions:
            rows.append({
                "Date": t.get("date"),
                "Description": t.get("description", ""),
                "Amount": t.get("amount", 0),
                "Category": t.get("category", "Other Business Expenses"),
            })
        df = pd.DataFrame(rows)
        try:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        except Exception:
            pass

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="All Transactions", index=False)
            # Category summary
            summary = df.groupby("Category")["Amount"].agg(["count", "sum"]).reset_index()
            summary.columns = ["Category", "Count", "Total"]
            summary.to_excel(writer, sheet_name="Category Summary", index=False)
            # One sheet per category
            for cat in sorted(df["Category"].dropna().unique()):
                cat_df = df[df["Category"] == cat]
                safe = re.sub(r"[^\w]", "_", str(cat))[:31]
                cat_df.to_excel(writer, sheet_name=safe, index=False)
        print(f"Saved {len(df)} transactions to {output_path}")

    def save_to_json(self, output_path):
        """Save transactions to a JSON file."""
        serializable = []
        for t in self.transactions:
            row = dict(t)
            d = row.get("date")
            if hasattr(d, "isoformat"):
                row["date"] = d.isoformat()
            elif d is not None:
                row["date"] = str(d)
            serializable.append(row)
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(serializable, fh, indent=2, ensure_ascii=False, default=str)
        print(f"Saved {len(serializable)} transactions to {output_path}")

    # ------------------------------------------------------------------
    # Category management
    # ------------------------------------------------------------------
    def load_custom_categories(self, categories_file):
        """Load custom categories from a JSON file."""
        try:
            with open(categories_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self.categories = data
                print(f"Loaded {len(data)} categories from {categories_file}")
                return True
        except Exception as exc:
            print(f"Error loading categories: {exc}")
        return False

    def _load_learned_categories(self):
        """Load learned merchant-to-category mappings."""
        try:
            if os.path.exists(self.learned_categories_file):
                with open(self.learned_categories_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    self.learned_categories = data
                    print(f"Loaded {len(data)} learned categories from {self.learned_categories_file}")
        except Exception as exc:
            print(f"Warning: could not load learned categories: {exc}")

    def save_learned_categories(self):
        """Save learned merchant-to-category mappings."""
        try:
            os.makedirs(os.path.dirname(self.learned_categories_file), exist_ok=True)
            with open(self.learned_categories_file, "w", encoding="utf-8") as fh:
                json.dump(self.learned_categories, fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            print(f"Warning: could not save learned categories: {exc}")

    def learn_category(self, description, category):
        """Learn a category for a specific merchant description.

        Stores the NORMALIZED merchant name so the mapping matches future
        transactions regardless of card prefixes, reference numbers, or
        trailing state codes.
        """
        from bank_parsers.categorizer import clean_for_categorization

        merchant = clean_for_categorization(description)
        if not merchant:
            words = (description or "").lower().split()
            merchant = " ".join(words[:2]) if len(words) >= 2 else ""
        if merchant:
            self.learned_categories[merchant] = category
            print(f"Learned category '{category}' for '{merchant}'")
            self.save_learned_categories()
            self.apply_learned_category(merchant, category)
            return merchant
        return None

    def apply_learned_category(self, merchant, category):
        """Apply a learned merchant-to-category mapping to all matching transactions."""
        merchant_lower = merchant.lower()
        for t in self.transactions:
            desc = (t.get("description") or "").lower()
            if merchant_lower in desc and t.get("category") != category:
                t["category"] = category

    # ------------------------------------------------------------------
    # AI categorization
    # ------------------------------------------------------------------
    def enable_ai_categorization(self, estimated_transactions=None):
        """Enable AI-based categorization.

        Checks whether a local model or OpenAI backend is available via the
        unified AIClient. Returns True if AI is available, False otherwise.
        """
        try:
            from bank_parsers.ai_client import get_ai_client

            client = get_ai_client()
            if client.available:
                self.use_ai = True
                desc = client.describe()
                print(f"AI categorization enabled: {desc}")
                return True
            else:
                print(
                    "AI categorization not available. To enable:\n"
                    "  - Local model: run 'python download_model.py'\n"
                    "  - OpenAI: set preferred_backend='openai' in config/ai_settings.json"
                )
                return False
        except Exception as exc:
            print(f"AI categorization setup failed: {exc}")
            return False

    def download_local_ai_model(self):
        """Download the configured GGUF AI model into the project models directory."""
        from bank_parsers.model_catalog import detect_hardware, best_recommendation, model_url, mmproj_url
        import urllib.request

        hw = detect_hardware()
        rec = best_recommendation(hw)
        if rec is None:
            print("No model fits your hardware. Consider using OpenAI backend instead.")
            return None
        os.makedirs(os.path.dirname(self.local_model_path), exist_ok=True)
        model_dest = os.path.join(os.path.dirname(self.local_model_path), rec.quant.filename)
        print(f"Downloading {rec.variant.label} {rec.quant.name} ({rec.quant.size_gb:.1f} GB)...")
        urllib.request.urlretrieve(model_url(rec.variant, rec.quant), model_dest)
        # Also download the mmproj for vision
        mmproj_dest = os.path.join(os.path.dirname(self.local_model_path), rec.variant.mmproj_filename)
        urllib.request.urlretrieve(mmproj_url(rec.variant), mmproj_dest)
        self.local_model_path = model_dest
        print(f"Model downloaded to {model_dest}")
        return model_dest

    # ------------------------------------------------------------------
    # Schedule C generation
    # ------------------------------------------------------------------
    def generate_schedule_c_data(self):
        """Generate Schedule C line-item data from categorized transactions.

        Returns a dict mapping Schedule C line descriptions to dollar totals.
        """
        if not self.transactions:
            return {}

        # Map category names to Schedule C line items
        schedule_c_mapping = {
            "Advertising": "advertising",
            "Marketing": "advertising",
            "Meals & Entertainment": "meals_and_entertainment",
            "Other Business Expenses": "other_business_expenses",
            "Office Supplies": "office_expense",
            "Insurance": "insurance",
            "Software & Subscriptions": "other_business_expenses",
            "Professional Services": "legal_and_professional_services",
            "Banking & Credit": "other_business_expenses",
            "Utilities": "utilities",
            "Rent": "rent_or_lease_other_business_property",
            "Travel & Transportation": "travel",
            "Repairs or Maintenance": "repairs_and_maintenance",
            "Supplies (not incl Part III)": "supplies_not_included_in_part_iii",
            "Taxes or licenses": "taxes_and_licenses",
            "Interest Mortgage": "mortgage_interest_paid",
            "Employee Benefit Programs": "employee_benefit_programs",
            "Pension and profit-sharing plans": "pension_and_profit_sharing_plans",
            "Rent or Lease Vehicles, Mach": "rent_or_lease_vehicles_machinery_and_equipment",
            "Rent or Lease Other Business": "rent_or_lease_other_business_property",
            "Depreciation": "depreciation",
            "Depletion": "depletion",
            "Energy efficient commercial bldgs": "energy_efficient_commercial_buildings",
        }

        totals = {}
        for t in self.transactions:
            category = t.get("category", "Other Business Expenses")
            amount = t.get("amount", 0)
            try:
                amount = abs(float(amount))
            except (TypeError, ValueError):
                amount = 0
            line = schedule_c_mapping.get(category, "other_business_expenses")
            totals[line] = totals.get(line, 0) + amount

        totals["total_expenses"] = sum(totals.values())
        return totals


def main():
    """Command-line entry point for the Bank Statement Analyzer."""
    parser = argparse.ArgumentParser(
        description="Extract and categorize transactions from bank statement PDFs."
    )
    parser.add_argument("pdf_file", nargs="?", help="Path to a PDF bank statement")
    parser.add_argument("-o", "--output", default="categorized_transactions.xlsx",
                        help="Output file path (default: categorized_transactions.xlsx)")
    parser.add_argument("-j", "--json", action="store_true", help="Output JSON instead of Excel")
    parser.add_argument("-c", "--categories", help="Custom categories JSON file")
    parser.add_argument("-m", "--multiple", action="store_true",
                        help="Process all PDFs in the current directory")
    parser.add_argument("-s", "--schedule_c", action="store_true",
                        help="Print Schedule C data to stdout")
    args = parser.parse_args()

    analyzer = BankStatementAnalyzer()

    if args.categories:
        analyzer.load_custom_categories(args.categories)

    if args.multiple:
        import glob
        pdfs = sorted(glob.glob("*.pdf"))
    elif args.pdf_file:
        pdfs = [args.pdf_file]
    else:
        parser.print_help()
        return

    for pdf in pdfs:
        analyzer.extract_from_pdf(pdf)

    analyzer.categorize_transactions()

    if args.schedule_c:
        data = analyzer.generate_schedule_c_data()
        print(json.dumps(data, indent=2))

    if args.json:
        analyzer.save_to_json(args.output)
    else:
        analyzer.save_to_excel(args.output)


if __name__ == "__main__":
    main()
