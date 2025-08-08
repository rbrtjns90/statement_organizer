#!/usr/bin/env python3
"""
Final Schedule C PDF Filler
--------------------------
Uses the corrected field mappings based on actual PDF positions.
"""

import fitz  # PyMuPDF
import json
import os
from bank_statement_analyzer import BankStatementAnalyzer


class FinalScheduleCFiller:
    """Final Schedule C PDF filler with corrected field mappings."""
    
    def __init__(self, pdf_path="config/schedule_c.pdf", mapping_file="config/schedule_c_field_mappings.json"):
        self.pdf_path = pdf_path
        self.mapping_file = mapping_file
        self.form_fields = {}
        self.schedule_c_data = {}
        self.field_mappings = {}
        
        # Load field mappings from JSON file
        self.load_field_mappings()
    
    def load_field_mappings(self):
        """Load field mappings from JSON configuration file."""
        # Default fallback mappings (current working mappings)
        default_mappings = {
            'Car and truck expenses': 'f1_36',
            'Contract labor': 'f1_29',
            'Insurance': 'f1_24',
            'Interest (other)': 'f1_26',
            'Legal and professional services': 'f1_18',
            'Office expenses': 'f1_28',
            'Travel': 'f1_17',
            'Meals': 'f1_35',
            'Utilities': 'f1_37',
            'Other expenses': 'f1_39',
            'Total expenses': 'f1_41'
        }
        
        try:
            if os.path.exists(self.mapping_file):
                print(f"📄 Loading field mappings from {self.mapping_file}")
                with open(self.mapping_file, 'r') as f:
                    data = json.load(f)
                
                # Extract field mappings from JSON structure
                if "schedule_c_mappings" in data:
                    for category, info in data["schedule_c_mappings"].items():
                        field_pattern = info.get("field_pattern", "")
                        if field_pattern:
                            self.field_mappings[category] = field_pattern
                    print(f"✅ Loaded {len(self.field_mappings)} mappings from JSON")
                else:
                    print("⚠️ JSON file doesn't contain 'schedule_c_mappings', using defaults")
                    self.field_mappings = default_mappings
            else:
                print(f"⚠️ Mapping file {self.mapping_file} not found, using default mappings")
                self.field_mappings = default_mappings
                
        except Exception as e:
            print(f"❌ Error loading mappings: {e}, using default mappings")
            self.field_mappings = default_mappings
        
        print(f"📋 Using {len(self.field_mappings)} field mappings")
    
    def analyze_pdf_structure(self):
        """Extract all form fields from the PDF."""
        print("🔍 Analyzing PDF form structure...")
        
        try:
            doc = fitz.open(self.pdf_path)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                widgets = list(page.widgets())
                
                if widgets:
                    print(f"📄 Page {page_num + 1}: Found {len(widgets)} form fields")
                    
                    for widget in widgets:
                        field_name = widget.field_name or f"unnamed_field_{len(self.form_fields)}"
                        field_type = widget.field_type_string
                        field_value = widget.field_value or ""
                        
                        self.form_fields[field_name] = {
                            'type': field_type,
                            'value': field_value,
                            'page': page_num,
                            'widget': widget
                        }
            
            doc.close()
            print(f"✅ Extracted {len(self.form_fields)} form fields")
            return True
            
        except Exception as e:
            print(f"❌ Error analyzing PDF: {e}")
            return False
    
    def load_expense_data(self):
        """Load and categorize expense data from bank statements."""
        print("💰 Loading expense data...")
        
        analyzer = BankStatementAnalyzer()
        
        try:
            import glob
            pdf_files = glob.glob("Statements/*.pdf")
            if pdf_files:
                print(f"📊 Processing {len(pdf_files)} bank statements...")
                analyzer.extract_from_multiple_pdfs(pdf_files[:10])
                analyzer.categorize_transactions()
                self.schedule_c_data = analyzer.generate_schedule_c_data()
                
                if self.schedule_c_data:
                    total = self.schedule_c_data.get('Total expenses', 0)
                    print(f"✅ Generated Schedule C data: ${total:,.2f} total expenses")
                    
                    # Show categories and their field mappings
                    print("📋 Expense categories and field mappings:")
                    for category, amount in self.schedule_c_data.items():
                        if amount > 0 and category in self.field_mappings:
                            field_pattern = self.field_mappings[category]
                            print(f"  • {category}: ${amount:,.2f} → {field_pattern}")
                    
                    return True
                    
        except Exception as e:
            print(f"❌ Error loading expense data: {e}")
        
        return False
    
    def find_matching_field(self, field_pattern):
        """Find the actual PDF field name that matches the pattern."""
        for field_name, field_info in self.form_fields.items():
            if field_info['type'] == 'Text' and field_pattern in field_name:
                return field_name
        return None
    
    def fill_pdf_with_mappings(self, output_path="schedule_c_final_filled.pdf"):
        """Fill the PDF using the loaded field mappings."""
        print(f"\n📝 Filling PDF with field mappings...")
        
        try:
            doc = fitz.open(self.pdf_path)
            filled_count = 0
            
            print("\n📋 Filling Schedule C with field mappings:")
            
            for category, amount in self.schedule_c_data.items():
                if amount <= 0 or category not in self.field_mappings:
                    continue
                
                field_pattern = self.field_mappings[category]
                matching_field = self.find_matching_field(field_pattern)
                
                if matching_field:
                    field_info = self.form_fields[matching_field]
                    
                    # Find and fill the field
                    page = doc[field_info['page']]
                    widgets = list(page.widgets())
                    
                    for widget in widgets:
                        if widget.field_name == matching_field:
                            # Format amount appropriately
                            formatted_amount = f"{amount:,.0f}"
                            
                            widget.field_value = formatted_amount
                            widget.update()
                            filled_count += 1
                            
                            print(f"✅ {category}: ${amount:,.2f} → {field_pattern} ({matching_field})")
                            break
                else:
                    print(f"❌ Could not find field for {category} (pattern: {field_pattern})")
            
            # Save the filled PDF
            doc.save(output_path)
            doc.close()
            
            print(f"\n🎉 Successfully filled {filled_count} form fields!")
            print(f"📄 Output saved as: {output_path}")
            
            return output_path
            
        except Exception as e:
            print(f"❌ Error filling PDF: {e}")
            return None
    
    def process_final_schedule_c(self):
        """Complete final Schedule C processing workflow."""
        print("🚀 Starting Final Schedule C Processing with Corrected Mappings...\n")
        
        # Step 1: Load expense data
        if not self.load_expense_data():
            print("❌ Failed to load expense data")
            return None
        
        # Step 2: Analyze PDF structure
        if not self.analyze_pdf_structure():
            print("❌ Failed to analyze PDF structure")
            return None
        
        # Step 3: Fill PDF with field mappings
        output_file = self.fill_pdf_with_mappings()
        
        if output_file:
            print(f"\n✅ Final Schedule C Processing Complete!")
            print(f"📊 Total Expenses: ${self.schedule_c_data.get('Total expenses', 0):,.2f}")
            print(f"📄 Final PDF: {output_file}")
            print(f"🎯 All expenses placed using field mappings from {self.mapping_file}!")
        
        return output_file


def main():
    """Main function."""
    filler = FinalScheduleCFiller()
    filler.process_final_schedule_c()


if __name__ == "__main__":
    main()
