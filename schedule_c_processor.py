#!/usr/bin/env python3
"""
Schedule C PDF Processor
------------------------
This script examines the Schedule C PDF form, extracts its structure,
and populates it with data from the bank statement analyzer.
"""

import pdfplumber
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from PyPDF2 import PdfReader, PdfWriter
import fitz  # PyMuPDF for form field manipulation
from bank_statement_analyzer import BankStatementAnalyzer


class ScheduleCProcessor:
    """Process Schedule C PDF forms with transaction data."""
    
    def __init__(self, pdf_path="config/schedule_c.pdf"):
        self.pdf_path = pdf_path
        self.form_fields = {}
        self.schedule_c_data = {}
        
    def analyze_pdf_structure(self):
        """Analyze the Schedule C PDF to understand its structure and fields."""
        print(f"Analyzing PDF structure: {self.pdf_path}")
        
        try:
            # Method 1: Try with PyMuPDF for form fields
            doc = fitz.open(self.pdf_path)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Get form fields
                widgets = page.widgets()
                if widgets:
                    print(f"\n=== Form Fields on Page {page_num + 1} ===")
                    for widget in widgets:
                        field_name = widget.field_name
                        field_type = widget.field_type_string
                        field_value = widget.field_value
                        print(f"Field: {field_name}, Type: {field_type}, Value: {field_value}")
                        self.form_fields[field_name] = {
                            'type': field_type,
                            'value': field_value,
                            'page': page_num
                        }
                
                # Extract text to understand structure
                text = page.get_text()
                if text and page_num == 0:  # Focus on first page
                    print(f"\n=== Text Structure Page {page_num + 1} ===")
                    lines = text.split('\n')
                    for i, line in enumerate(lines):
                        line = line.strip()
                        if line and any(keyword in line.lower() for keyword in 
                                      ['part ii', 'expenses', 'line', 'advertising', 'office', 'travel', 'meals']):
                            print(f"Line {i}: {line}")
            
            doc.close()
            
        except Exception as e:
            print(f"Error with PyMuPDF: {e}")
            
        # Method 2: Try with pdfplumber for text extraction
        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                print(f"\n=== PDF Structure with pdfplumber ===")
                print(f"Number of pages: {len(pdf.pages)}")
                
                for page_num, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        lines = text.split('\n')
                        expense_lines = []
                        
                        for i, line in enumerate(lines):
                            line = line.strip()
                            # Look for Schedule C expense line items
                            if any(keyword in line.lower() for keyword in [
                                'advertising', 'car and truck', 'commissions', 'contract labor',
                                'depletion', 'depreciation', 'insurance', 'interest',
                                'legal and professional', 'office expenses', 'pension',
                                'rent', 'repairs', 'supplies', 'taxes and licenses',
                                'travel', 'meals', 'utilities', 'wages', 'other expenses'
                            ]):
                                expense_lines.append((i, line))
                        
                        if expense_lines:
                            print(f"\nExpense lines found on page {page_num + 1}:")
                            for line_num, line_text in expense_lines:
                                print(f"  {line_num}: {line_text}")
                        
        except Exception as e:
            print(f"Error with pdfplumber: {e}")
    
    def load_transaction_data(self, statement_files=None):
        """Load and process transaction data from bank statements."""
        analyzer = BankStatementAnalyzer()
        
        if statement_files:
            # Process specific statement files
            analyzer.extract_from_multiple_pdfs(statement_files)
        else:
            # Look for existing transaction data
            try:
                import glob
                pdf_files = glob.glob("Statements/*.pdf")
                if pdf_files:
                    print(f"Found {len(pdf_files)} statement files")
                    analyzer.extract_from_multiple_pdfs(pdf_files[:5])  # Process first 5 files
            except Exception as e:
                print(f"Error loading statements: {e}")
        
        # Categorize transactions
        analyzer.categorize_transactions()
        
        # Generate Schedule C data
        self.schedule_c_data = analyzer.generate_schedule_c_data()
        
        if self.schedule_c_data:
            print(f"\n=== Generated Schedule C Data ===")
            for line_item, amount in self.schedule_c_data.items():
                print(f"{line_item}: ${amount:,.2f}")
        
        return self.schedule_c_data
    
    def map_data_to_fields(self):
        """Map the calculated Schedule C data to PDF form fields."""
        # Common Schedule C line mappings (these may need adjustment based on the actual PDF)
        field_mappings = {
            # Part II - Expenses
            'Advertising': ['advertising', 'line8', 'part2_line8'],
            'Car and truck expenses': ['car_truck', 'line9', 'part2_line9'],
            'Commissions and fees': ['commissions', 'line10', 'part2_line10'],
            'Contract labor': ['contract_labor', 'line11', 'part2_line11'],
            'Depletion': ['depletion', 'line12', 'part2_line12'],
            'Depreciation': ['depreciation', 'line13', 'part2_line13'],
            'Insurance': ['insurance', 'line15', 'part2_line15'],
            'Interest (mortgage)': ['interest_mortgage', 'line16a', 'part2_line16a'],
            'Interest (other)': ['interest_other', 'line16b', 'part2_line16b'],
            'Legal and professional services': ['legal_professional', 'line17', 'part2_line17'],
            'Office expenses': ['office_expenses', 'line18', 'part2_line18'],
            'Pension and profit-sharing plans': ['pension', 'line19', 'part2_line19'],
            'Rent (vehicles, machinery, equipment)': ['rent_equipment', 'line20a', 'part2_line20a'],
            'Rent (other)': ['rent_other', 'line20b', 'part2_line20b'],
            'Repairs and maintenance': ['repairs', 'line21', 'part2_line21'],
            'Supplies': ['supplies', 'line22', 'part2_line22'],
            'Taxes and licenses': ['taxes_licenses', 'line23', 'part2_line23'],
            'Travel': ['travel', 'line24a', 'part2_line24a'],
            'Meals': ['meals', 'line24b', 'part2_line24b'],
            'Utilities': ['utilities', 'line25', 'part2_line25'],
            'Wages': ['wages', 'line26', 'part2_line26'],
            'Other expenses': ['other_expenses', 'line27a', 'part2_line27a'],
            'Total expenses': ['total_expenses', 'line28', 'part2_line28']
        }
        
        mapped_data = {}
        
        for schedule_line, amount in self.schedule_c_data.items():
            if schedule_line in field_mappings:
                possible_fields = field_mappings[schedule_line]
                
                # Find matching field in the PDF
                for field_name in self.form_fields.keys():
                    field_name_lower = field_name.lower()
                    if any(possible_field in field_name_lower for possible_field in possible_fields):
                        mapped_data[field_name] = str(amount)
                        print(f"Mapped {schedule_line} (${amount:,.2f}) -> {field_name}")
                        break
        
        return mapped_data
    
    def populate_pdf(self, output_path="schedule_c_filled.pdf"):
        """Populate the Schedule C PDF with the calculated data."""
        try:
            # Open the PDF with PyMuPDF
            doc = fitz.open(self.pdf_path)
            
            # Get the mapped data
            mapped_data = self.map_data_to_fields()
            
            if not mapped_data:
                print("No field mappings found. Creating overlay instead.")
                return self.create_overlay_pdf(output_path)
            
            # Fill form fields
            for page_num in range(len(doc)):
                page = doc[page_num]
                widgets = page.widgets()
                
                for widget in widgets:
                    field_name = widget.field_name
                    if field_name in mapped_data:
                        widget.field_value = mapped_data[field_name]
                        widget.update()
                        print(f"Filled field {field_name} with {mapped_data[field_name]}")
            
            # Save the filled PDF
            doc.save(output_path)
            doc.close()
            
            print(f"Successfully created filled Schedule C: {output_path}")
            return output_path
            
        except Exception as e:
            print(f"Error filling PDF form: {e}")
            return self.create_overlay_pdf(output_path)
    
    def create_overlay_pdf(self, output_path="schedule_c_filled.pdf"):
        """Create an overlay PDF with the data if form filling doesn't work."""
        print("Creating overlay PDF with calculated data...")
        
        try:
            # Create a new PDF with the data
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            
            # Create overlay
            overlay_path = "schedule_c_overlay.pdf"
            c = canvas.Canvas(overlay_path, pagesize=letter)
            
            # Add title
            c.setFont("Helvetica-Bold", 16)
            c.drawString(50, 750, "Schedule C - Calculated Business Expenses")
            
            # Add data
            c.setFont("Helvetica", 12)
            y_position = 700
            
            for line_item, amount in self.schedule_c_data.items():
                c.drawString(50, y_position, f"{line_item}:")
                c.drawString(400, y_position, f"${amount:,.2f}")
                y_position -= 20
                
                if y_position < 100:  # Start new page if needed
                    c.showPage()
                    y_position = 750
            
            c.save()
            
            # Try to merge with original PDF
            try:
                from PyPDF2 import PdfReader, PdfWriter
                
                reader_original = PdfReader(self.pdf_path)
                reader_overlay = PdfReader(overlay_path)
                writer = PdfWriter()
                
                # Merge first page
                if len(reader_original.pages) > 0 and len(reader_overlay.pages) > 0:
                    page = reader_original.pages[0]
                    page.merge_page(reader_overlay.pages[0])
                    writer.add_page(page)
                    
                    # Add remaining pages from original
                    for i in range(1, len(reader_original.pages)):
                        writer.add_page(reader_original.pages[i])
                
                # Save merged PDF
                with open(output_path, 'wb') as output_file:
                    writer.write(output_file)
                
                print(f"Successfully created merged Schedule C: {output_path}")
                
            except Exception as merge_error:
                print(f"Could not merge PDFs: {merge_error}")
                print(f"Overlay PDF created separately: {overlay_path}")
                return overlay_path
            
            return output_path
            
        except Exception as e:
            print(f"Error creating overlay PDF: {e}")
            return None


def main():
    """Main function to process Schedule C PDF."""
    processor = ScheduleCProcessor()
    
    print("=== Schedule C PDF Processor ===\n")
    
    # Step 1: Analyze PDF structure
    processor.analyze_pdf_structure()
    
    # Step 2: Load transaction data
    schedule_data = processor.load_transaction_data()
    
    if not schedule_data:
        print("No transaction data available. Please process bank statements first.")
        return
    
    # Step 3: Populate the PDF
    output_file = processor.populate_pdf()
    
    if output_file:
        print(f"\n✅ Schedule C processing complete!")
        print(f"📄 Output file: {output_file}")
        print(f"💰 Total expenses: ${schedule_data.get('Total expenses', 0):,.2f}")
    else:
        print("❌ Failed to process Schedule C PDF")


if __name__ == "__main__":
    main()
