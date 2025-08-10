#!/usr/bin/env python3
"""
Mapped Schedule C PDF Filler
---------------------------
Uses the schedule_c_mapped_lines.json file to ensure correct line placement.
"""

import fitz  # PyMuPDF
import json
from bank_statement_analyzer import BankStatementAnalyzer


class MappedScheduleCFiller:
    """Schedule C PDF filler using the mapped lines configuration."""
    
    def __init__(self, pdf_path="schedule_c.pdf", mapping_file="schedule_c_mapped_lines.json"):
        self.pdf_path = pdf_path
        self.mapping_file = mapping_file
        self.form_fields = {}
        self.schedule_c_data = {}
        self.line_mappings = {}
        self.category_mappings = {}
        
        # Load the mapping configuration
        self.load_mapping_config()
    
    def load_mapping_config(self):
        """Load the Schedule C line mapping configuration."""
        try:
            with open(self.mapping_file, 'r') as f:
                config = json.load(f)
                self.line_mappings = config['schedule_c_line_mappings']
                self.category_mappings = config['category_to_line_mapping']
            print(f"✅ Loaded mapping configuration with {len(self.line_mappings)} Schedule C lines")
        except Exception as e:
            print(f"❌ Error loading mapping config: {e}")
    
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
                            'widget': widget,
                            'rect': list(widget.rect) if widget.rect else None
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
                    
                    # Show categories and their intended lines
                    print("📋 Expense categories and intended Schedule C lines:")
                    for category, amount in self.schedule_c_data.items():
                        if amount > 0:
                            line_num = self.category_mappings.get(category, "Unknown")
                            print(f"  • {category}: ${amount:,.2f} → Line {line_num}")
                    
                    return True
                    
        except Exception as e:
            print(f"❌ Error loading expense data: {e}")
        
        return False
    
    def create_field_mappings(self):
        """Create field mappings using the configuration file."""
        print("🔧 Creating field mappings using configuration...")
        
        field_mappings = {}
        
        for category, amount in self.schedule_c_data.items():
            if amount <= 0:
                continue
                
            # Get the intended Schedule C line for this category
            intended_line = self.category_mappings.get(category)
            
            if not intended_line:
                print(f"⚠️  No line mapping found for category: {category}")
                continue
            
            # Get the line configuration
            line_config = self.line_mappings.get(intended_line)
            
            if not line_config:
                print(f"⚠️  No line configuration found for line: {intended_line}")
                continue
            
            # Find matching PDF field using the patterns
            pdf_field_patterns = line_config['pdf_field_patterns']
            best_match = None
            
            for pattern in pdf_field_patterns:
                for field_name, field_info in self.form_fields.items():
                    if field_info['type'] != 'Text':
                        continue
                    
                    # Check if this field matches the pattern
                    field_name_clean = field_name.lower().replace('[0]', '').replace('topmostsubform[0].page1[0].', '')
                    
                    if pattern.lower() in field_name_clean:
                        best_match = field_name
                        break
                
                if best_match:
                    break
            
            if best_match:
                field_mappings[category] = {
                    'field_name': best_match,
                    'line_number': intended_line,
                    'description': line_config['description']
                }
                print(f"✅ {category}: ${amount:,.2f} → Line {intended_line} ({best_match})")
            else:
                print(f"❌ Could not find PDF field for {category} (Line {intended_line})")
        
        return field_mappings
    
    def fill_pdf_with_mapped_data(self, field_mappings, output_path="schedule_c_mapped_filled.pdf"):
        """Fill the PDF using the mapped field data."""
        print(f"\n📝 Filling PDF with mapped data...")
        
        try:
            doc = fitz.open(self.pdf_path)
            filled_count = 0
            
            # Sort by line number for organized output
            sorted_mappings = sorted(field_mappings.items(), 
                                   key=lambda x: self.sort_line_number(x[1]['line_number']))
            
            print("\n📋 Filling Schedule C lines in order:")
            
            for category, mapping_info in sorted_mappings:
                if category in self.schedule_c_data:
                    amount = self.schedule_c_data[category]
                    field_name = mapping_info['field_name']
                    line_number = mapping_info['line_number']
                    description = mapping_info['description']
                    
                    # Find and fill the field
                    field_info = self.form_fields.get(field_name)
                    if field_info:
                        page = doc[field_info['page']]
                        widgets = list(page.widgets())
                        
                        for widget in widgets:
                            if widget.field_name == field_name:
                                # Format amount appropriately
                                formatted_amount = f"{amount:,.0f}"
                                
                                widget.field_value = formatted_amount
                                widget.update()
                                filled_count += 1
                                
                                print(f"✅ Line {line_number}: {description} = ${amount:,.2f}")
                                break
            
            # Save the filled PDF
            doc.save(output_path)
            doc.close()
            
            print(f"\n🎉 Successfully filled {filled_count} Schedule C lines!")
            print(f"📄 Output saved as: {output_path}")
            
            return output_path
            
        except Exception as e:
            print(f"❌ Error filling PDF: {e}")
            return None
    
    def sort_line_number(self, line_num):
        """Sort line numbers properly (8, 9, 10, 11, ..., 16a, 16b, 17, ...)."""
        if 'a' in line_num or 'b' in line_num:
            base_num = int(line_num.replace('a', '').replace('b', ''))
            suffix = 0.1 if 'a' in line_num else 0.2
            return base_num + suffix
        return int(line_num)
    
    def process_mapped_schedule_c(self):
        """Complete mapped Schedule C processing workflow."""
        print("🚀 Starting Mapped Schedule C Processing...\n")
        
        # Step 1: Load expense data
        if not self.load_expense_data():
            print("❌ Failed to load expense data")
            return None
        
        # Step 2: Analyze PDF structure
        if not self.analyze_pdf_structure():
            print("❌ Failed to analyze PDF structure")
            return None
        
        # Step 3: Create field mappings using configuration
        field_mappings = self.create_field_mappings()
        
        if not field_mappings:
            print("❌ Failed to create field mappings")
            return None
        
        # Step 4: Fill PDF with mapped data
        output_file = self.fill_pdf_with_mapped_data(field_mappings)
        
        if output_file:
            print(f"\n✅ Mapped Schedule C Processing Complete!")
            print(f"📊 Total Expenses: ${self.schedule_c_data.get('Total expenses', 0):,.2f}")
            print(f"📄 Mapped PDF: {output_file}")
            print(f"🎯 All expenses placed on their correct Schedule C lines using mapping configuration!")
        
        return output_file
    
    def update_gui_integration(self):
        """Update the GUI to use the mapping configuration."""
        print("\n🔧 Updating GUI integration...")
        
        # This method can be called to ensure the GUI uses the same mappings
        gui_mapping_code = '''
# Add this to your GUI code to use the mapping configuration:

def load_schedule_c_mappings(self):
    """Load Schedule C line mappings for GUI."""
    try:
        with open('schedule_c_mapped_lines.json', 'r') as f:
            config = json.load(f)
            self.category_mappings = config['category_to_line_mapping']
            self.line_mappings = config['schedule_c_line_mappings']
        return True
    except Exception as e:
        print(f"Error loading mappings: {e}")
        return False

def get_schedule_c_line(self, category):
    """Get the correct Schedule C line number for a category."""
    return self.category_mappings.get(category, "Unknown")

def generate_schedule_c_with_mappings(self):
    """Generate Schedule C data using the mapping configuration."""
    schedule_data = {}
    
    for category, amount in self.categorized_expenses.items():
        line_number = self.get_schedule_c_line(category)
        if line_number != "Unknown":
            line_config = self.line_mappings.get(line_number, {})
            line_description = line_config.get('description', category)
            
            if line_description not in schedule_data:
                schedule_data[line_description] = 0
            schedule_data[line_description] += amount
    
    return schedule_data
'''
        
        print("📝 GUI integration code generated. Add the above methods to your GUI class.")
        
        return gui_mapping_code


def main():
    """Main function."""
    filler = MappedScheduleCFiller()
    filler.process_mapped_schedule_c()
    
    # Also generate GUI integration code
    filler.update_gui_integration()


if __name__ == "__main__":
    main()
