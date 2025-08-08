#!/usr/bin/env python3
"""
PDF Field Mapper GUI - PyQt6
----------------------------
Interactive GUI to display PDF with field overlays and create mapping configurations.
"""

import sys
import json
import os
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QPushButton, QLabel, QComboBox, 
                            QListWidget, QListWidgetItem, QScrollArea, 
                            QFileDialog, QMessageBox, QSplitter, QTextEdit,
                            QTreeWidget, QTreeWidgetItem, QGroupBox)
from PyQt6.QtCore import Qt, QRect, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QFont
import fitz  # PyMuPDF
from PIL import Image
import tempfile


class ClickableLabel(QLabel):
    """Custom QLabel that emits click signals with coordinates."""
    
    clicked = pyqtSignal(int, int, str)  # x, y, field_name
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.field_overlays = []
        self.selected_field = None
        
    def set_field_overlays(self, overlays):
        """Set the field overlay data."""
        self.field_overlays = overlays
        
    def mousePressEvent(self, event):
        """Handle mouse clicks to detect field selection."""
        if event.button() == Qt.MouseButton.LeftButton:
            x, y = event.position().x(), event.position().y()
            
            # Check which field was clicked
            for field_name, rect in self.field_overlays:
                if rect.contains(int(x), int(y)):
                    self.clicked.emit(int(x), int(y), field_name)
                    return
        
        super().mousePressEvent(event)


class PDFFieldMapperGUI(QMainWindow):
    """Main GUI class for PDF field mapping."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Field Mapper - Schedule C")
        self.setGeometry(100, 100, 1400, 900)
        
        # Data storage
        self.pdf_doc = None
        self.current_page = 0
        self.form_fields = {}
        self.field_mappings = {}
        self.selected_field = None
        self.pdf_pixmap = None
        
        # Load expense categories from business_categories.json
        self.expense_categories = self.load_business_categories()
        
        self.setup_ui()
    
    def load_business_categories(self):
        """Load business categories from business_categories.json file."""
        categories_file = "config/business_categories.json"
        
        # Default fallback categories (Schedule C specific)
        default_categories = [
            'Car and truck expenses',
            'Contract labor',
            'Insurance', 
            'Interest (other)',
            'Legal and professional services',
            'Office expenses',
            'Travel',
            'Meals',
            'Utilities',
            'Other expenses',
            'Total expenses'
        ]
        
        try:
            if os.path.exists(categories_file):
                with open(categories_file, 'r') as f:
                    data = json.load(f)
                
                # Extract category names (keys from the JSON)
                categories = list(data.keys())
                
                # Add Schedule C specific categories that might not be in business categories
                schedule_c_specific = [
                    'Car and truck expenses',
                    'Contract labor',
                    'Interest (other)',
                    'Legal and professional services',
                    'Office expenses',
                    'Travel',
                    'Other expenses',
                    'Total expenses'
                ]
                
                # Combine business categories with Schedule C specific ones
                all_categories = categories + [cat for cat in schedule_c_specific if cat not in categories]
                
                print(f"✅ Loaded {len(categories)} business categories from {categories_file}")
                print(f"📋 Total categories available: {len(all_categories)}")
                
                return sorted(all_categories)
                
            else:
                print(f"⚠️ {categories_file} not found, using default Schedule C categories")
                return default_categories
                
        except Exception as e:
            print(f"❌ Error loading categories: {e}, using defaults")
            return default_categories
        
    def setup_ui(self):
        """Setup the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        
        # Top controls
        controls_layout = QHBoxLayout()
        
        self.open_btn = QPushButton("Open PDF")
        self.open_btn.clicked.connect(self.open_pdf)
        controls_layout.addWidget(self.open_btn)
        
        self.prev_btn = QPushButton("Previous Page")
        self.prev_btn.clicked.connect(self.prev_page)
        self.prev_btn.setEnabled(False)
        controls_layout.addWidget(self.prev_btn)
        
        self.next_btn = QPushButton("Next Page") 
        self.next_btn.clicked.connect(self.next_page)
        self.next_btn.setEnabled(False)
        controls_layout.addWidget(self.next_btn)
        
        self.page_label = QLabel("No PDF loaded")
        controls_layout.addWidget(self.page_label)
        
        controls_layout.addStretch()
        
        self.load_mapping_btn = QPushButton("Load Mapping")
        self.load_mapping_btn.clicked.connect(self.load_mapping)
        controls_layout.addWidget(self.load_mapping_btn)
        
        self.save_mapping_btn = QPushButton("Save Mapping")
        self.save_mapping_btn.clicked.connect(self.save_mapping)
        controls_layout.addWidget(self.save_mapping_btn)
        
        main_layout.addLayout(controls_layout)
        
        # Content area with splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)
        
        # PDF display area
        pdf_group = QGroupBox("PDF Preview")
        pdf_layout = QVBoxLayout(pdf_group)
        
        # Scrollable PDF display
        self.scroll_area = QScrollArea()
        self.pdf_label = ClickableLabel()
        self.pdf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_label.setStyleSheet("border: 1px solid gray;")
        self.pdf_label.clicked.connect(self.field_clicked)
        
        self.scroll_area.setWidget(self.pdf_label)
        self.scroll_area.setWidgetResizable(True)
        pdf_layout.addWidget(self.scroll_area)
        
        splitter.addWidget(pdf_group)
        
        # Mapping panel
        mapping_group = QGroupBox("Field Mappings")
        mapping_layout = QVBoxLayout(mapping_group)
        
        # Instructions
        instructions = QLabel("Click on PDF fields (red overlays) to map them to categories:")
        instructions.setWordWrap(True)
        mapping_layout.addWidget(instructions)
        
        # Category selection
        category_layout = QHBoxLayout()
        category_layout.addWidget(QLabel("Category:"))
        
        self.category_combo = QComboBox()
        self.category_combo.addItems(self.expense_categories)
        category_layout.addWidget(self.category_combo)
        
        mapping_layout.addLayout(category_layout)
        
        # Selected field info
        self.field_info_label = QLabel("Click a field to select it")
        self.field_info_label.setWordWrap(True)
        self.field_info_label.setStyleSheet("background-color: #f0f0f0; padding: 5px; border: 1px solid gray;")
        mapping_layout.addWidget(self.field_info_label)
        
        # Map button
        self.map_btn = QPushButton("Map Selected Field")
        self.map_btn.clicked.connect(self.map_field)
        self.map_btn.setEnabled(False)
        mapping_layout.addWidget(self.map_btn)
        
        # Current mappings tree
        mappings_label = QLabel("Current Mappings:")
        mapping_layout.addWidget(mappings_label)
        
        self.mappings_tree = QTreeWidget()
        self.mappings_tree.setHeaderLabels(["Category", "PDF Field"])
        self.mappings_tree.setColumnWidth(0, 200)
        mapping_layout.addWidget(self.mappings_tree)
        
        # Clear mapping button
        self.clear_btn = QPushButton("Clear Selected Mapping")
        self.clear_btn.clicked.connect(self.clear_mapping)
        mapping_layout.addWidget(self.clear_btn)
        
        splitter.addWidget(mapping_group)
        
        # Set splitter proportions
        splitter.setSizes([800, 400])
        
        # Status bar
        self.statusBar().showMessage("Ready - Open a PDF to start mapping")
        
    def open_pdf(self):
        """Open and analyze a PDF file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select PDF File", "", "PDF files (*.pdf);;All files (*.*)"
        )
        
        if not file_path:
            return
            
        try:
            self.pdf_doc = fitz.open(file_path)
            self.current_page = 0
            self.analyze_pdf_fields()
            self.display_page()
            
            # Enable navigation buttons
            self.prev_btn.setEnabled(len(self.pdf_doc) > 1)
            self.next_btn.setEnabled(len(self.pdf_doc) > 1)
            
            self.statusBar().showMessage(f"Loaded: {os.path.basename(file_path)} - {len(self.pdf_doc)} pages")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open PDF: {e}")
            
    def analyze_pdf_fields(self):
        """Extract all form fields from the PDF."""
        self.form_fields = {}
        
        for page_num in range(len(self.pdf_doc)):
            page = self.pdf_doc[page_num]
            widgets = list(page.widgets())
            
            for widget in widgets:
                if widget.field_type == 7:  # Text field (type 7, not 0)
                    field_name = widget.field_name or f"unnamed_field_{len(self.form_fields)}"
                    
                    # Extract simple field name (like f1_36)
                    simple_name = field_name.split('.')[-1].replace('[0]', '')
                    
                    self.form_fields[simple_name] = {
                        'full_name': field_name,
                        'page': page_num,
                        'rect': widget.rect,
                        'simple_name': simple_name
                    }
                    
    def display_page(self):
        """Display the current PDF page with field overlays."""
        if not self.pdf_doc:
            return
            
        try:
            # Render PDF page
            page = self.pdf_doc[self.current_page]
            mat = fitz.Matrix(1.5, 1.5)  # 1.5x zoom for better visibility
            pix = page.get_pixmap(matrix=mat)
            
            # Convert to QPixmap
            img_data = pix.tobytes("ppm")
            with tempfile.NamedTemporaryFile(suffix=".ppm", delete=False) as tmp_file:
                tmp_file.write(img_data)
                tmp_file.flush()
                
                self.pdf_pixmap = QPixmap(tmp_file.name)
                os.unlink(tmp_file.name)
            
            # Add field overlays
            self.add_field_overlays()
            
            # Display in label
            self.pdf_label.setPixmap(self.pdf_pixmap)
            
            # Update page label
            self.page_label.setText(f"Page {self.current_page + 1} of {len(self.pdf_doc)}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to display page: {e}")
            
    def add_field_overlays(self):
        """Add visual overlays for form fields on current page."""
        if not self.pdf_pixmap:
            return
            
        # Create a copy of the pixmap to draw on
        overlay_pixmap = self.pdf_pixmap.copy()
        painter = QPainter()
        
        if not painter.begin(overlay_pixmap):
            print("Failed to begin painting")
            return
            
        try:
            # Setup drawing
            pen = QPen(QColor(255, 0, 0), 2)  # Red pen
            painter.setPen(pen)
            painter.setFont(QFont("Arial", 8))
            
            # Field overlays for click detection
            field_overlays = []
            
            # Get fields for current page
            current_page_fields = [f for f in self.form_fields.values() if f['page'] == self.current_page]
            
            for field_info in current_page_fields:
                rect = field_info['rect']
                simple_name = field_info['simple_name']
                
                # Scale coordinates (1.5x zoom)
                x1, y1, x2, y2 = rect.x0 * 1.5, rect.y0 * 1.5, rect.x1 * 1.5, rect.y1 * 1.5
                
                # Draw rectangle overlay
                painter.drawRect(int(x1), int(y1), int(x2-x1), int(y2-y1))
                
                # Draw field name
                painter.setPen(QPen(QColor(255, 0, 0), 1))
                painter.drawText(int(x1 + 2), int(y1 + 12), simple_name)
                painter.setPen(pen)
                
                # Store for click detection
                click_rect = QRect(int(x1), int(y1), int(x2-x1), int(y2-y1))
                field_overlays.append((simple_name, click_rect))
                
        finally:
            painter.end()
        
        # Set the overlay data and pixmap
        self.pdf_label.set_field_overlays(field_overlays)
        self.pdf_label.setPixmap(overlay_pixmap)
        
    def field_clicked(self, x, y, field_name):
        """Handle field click events."""
        self.selected_field = field_name
        field_info = self.form_fields.get(field_name, {})
        
        info_text = f"Selected: {field_name}\nFull name: {field_info.get('full_name', 'Unknown')}"
        self.field_info_label.setText(info_text)
        
        self.map_btn.setEnabled(True)
        self.statusBar().showMessage(f"Selected field: {field_name}")
        
        # Redraw with highlighted field
        self.highlight_selected_field(field_name)
        
    def highlight_selected_field(self, selected_field):
        """Highlight the selected field."""
        if not self.pdf_pixmap:
            return
            
        # Create a copy of the original pixmap
        overlay_pixmap = self.pdf_pixmap.copy()
        painter = QPainter()
        
        if not painter.begin(overlay_pixmap):
            print("Failed to begin painting for highlight")
            return
            
        try:
            # Get fields for current page
            current_page_fields = [f for f in self.form_fields.values() if f['page'] == self.current_page]
            
            for field_info in current_page_fields:
                rect = field_info['rect']
                simple_name = field_info['simple_name']
                
                # Scale coordinates (1.5x zoom)
                x1, y1, x2, y2 = rect.x0 * 1.5, rect.y0 * 1.5, rect.x1 * 1.5, rect.y1 * 1.5
                
                # Choose color based on selection
                if simple_name == selected_field:
                    pen = QPen(QColor(0, 0, 255), 3)  # Blue for selected
                    painter.setBrush(QColor(0, 0, 255, 50))  # Light blue fill
                else:
                    pen = QPen(QColor(255, 0, 0), 2)  # Red for unselected
                    painter.setBrush(QColor(255, 255, 0, 50))  # Light yellow fill
                    
                painter.setPen(pen)
                
                # Draw rectangle
                painter.drawRect(int(x1), int(y1), int(x2-x1), int(y2-y1))
                
                # Draw field name
                painter.setPen(QPen(QColor(255, 0, 0), 1))
                painter.drawText(int(x1 + 2), int(y1 + 12), simple_name)
                
        finally:
            painter.end()
            
        self.pdf_label.setPixmap(overlay_pixmap)
        
    def map_field(self):
        """Map the selected field to the selected category."""
        if not self.selected_field:
            QMessageBox.warning(self, "Warning", "Please select a field first")
            return
            
        category = self.category_combo.currentText()
        if not category:
            QMessageBox.warning(self, "Warning", "Please select a category")
            return
            
        # Remove existing mapping for this category
        for i in range(self.mappings_tree.topLevelItemCount()):
            item = self.mappings_tree.topLevelItem(i)
            if item.text(0) == category:
                self.mappings_tree.takeTopLevelItem(i)
                break
                
        # Add new mapping
        self.field_mappings[category] = self.selected_field
        
        # Add to tree widget
        item = QTreeWidgetItem([category, self.selected_field])
        self.mappings_tree.addTopLevelItem(item)
        
        self.statusBar().showMessage(f"Mapped {category} → {self.selected_field}")
        
    def clear_mapping(self):
        """Clear the selected mapping."""
        current_item = self.mappings_tree.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Warning", "Please select a mapping to clear")
            return
            
        category = current_item.text(0)
        if category in self.field_mappings:
            del self.field_mappings[category]
            
        self.mappings_tree.takeTopLevelItem(self.mappings_tree.indexOfTopLevelItem(current_item))
        self.statusBar().showMessage("Mapping cleared")
        
    def save_mapping(self):
        """Save the current mappings to a JSON file."""
        if not self.field_mappings:
            QMessageBox.warning(self, "Warning", "No mappings to save")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Mapping File", "config/schedule_c_field_mappings.json", 
            "JSON files (*.json);;All files (*.*)"
        )
        
        if not file_path:
            return
            
        try:
            # Create mapping structure
            mapping_data = {
                "schedule_c_mappings": {}
            }
            
            # Line number mapping (for reference)
            line_mapping = {
                'Car and truck expenses': '9',
                'Contract labor': '11',
                'Insurance': '15',
                'Interest (other)': '16b',
                'Legal and professional services': '17',
                'Office expenses': '18',
                'Travel': '24a',
                'Meals': '24b',
                'Utilities': '25',
                'Other expenses': '27a',
                'Total expenses': '28'
            }
            
            for category, field in self.field_mappings.items():
                line_num = line_mapping.get(category, 'unknown')
                mapping_data["schedule_c_mappings"][category] = {
                    "line": line_num,
                    "field_pattern": field,
                    "description": f"Schedule C Line {line_num}"
                }
                
            with open(file_path, 'w') as f:
                json.dump(mapping_data, f, indent=2)
                
            QMessageBox.information(self, "Success", f"Mapping saved to {file_path}")
            self.statusBar().showMessage(f"Saved mapping with {len(self.field_mappings)} entries")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save mapping: {e}")
            
    def load_mapping(self):
        """Load mappings from a JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Mapping File", "", "JSON files (*.json);;All files (*.*)"
        )
        
        if not file_path:
            return
            
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                
            # Clear existing mappings
            self.mappings_tree.clear()
            self.field_mappings = {}
            
            # Load mappings
            mappings = data.get("schedule_c_mappings", {})
            for category, info in mappings.items():
                field_pattern = info.get("field_pattern", "")
                self.field_mappings[category] = field_pattern
                
                # Add to tree widget
                item = QTreeWidgetItem([category, field_pattern])
                self.mappings_tree.addTopLevelItem(item)
                
            QMessageBox.information(self, "Success", f"Loaded {len(mappings)} mappings")
            self.statusBar().showMessage(f"Loaded mapping with {len(mappings)} entries")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load mapping: {e}")
            
    def prev_page(self):
        """Go to previous page."""
        if self.pdf_doc and self.current_page > 0:
            self.current_page -= 1
            self.display_page()
            
    def next_page(self):
        """Go to next page."""
        if self.pdf_doc and self.current_page < len(self.pdf_doc) - 1:
            self.current_page += 1
            self.display_page()


def main():
    """Main function."""
    app = QApplication(sys.argv)
    
    # Set application properties
    app.setApplicationName("PDF Field Mapper")
    app.setApplicationVersion("1.0")
    
    # Create and show main window
    window = PDFFieldMapperGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
