#!/usr/bin/env python3
"""
Bank Statement Analyzer GUI
--------------------------
A graphical user interface for the bank statement analyzer using PyQt6.
"""

import os
import sys
import json
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QFileDialog, QComboBox, QTableWidget, 
    QTableWidgetItem, QTabWidget, QMessageBox, QProgressBar,
    QGroupBox, QGridLayout, QLineEdit, QTextEdit, QSplitter,
    QHeaderView, QDialog, QDialogButtonBox, QStyledItemDelegate
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QIcon, QColor

from bank_statement_analyzer import BankStatementAnalyzer
import pandas as pd


class WorkerThread(QThread):
    """Worker thread for processing PDFs in the background."""
    update_progress = pyqtSignal(int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, pdf_paths, categories_path=None):
        super().__init__()
        self.pdf_paths = pdf_paths if isinstance(pdf_paths, list) else [pdf_paths]
        self.categories_path = categories_path
        self.analyzer = None
        
    def run(self):
        try:
            self.analyzer = BankStatementAnalyzer()
            
            # Load custom categories if provided
            if self.categories_path:
                self.analyzer.load_custom_categories(self.categories_path)
            
            # Extract transactions from PDFs
            self.update_progress.emit(30)
            if len(self.pdf_paths) == 1:
                self.analyzer.extract_from_pdf(self.pdf_paths[0])
            else:
                self.analyzer.extract_from_multiple_pdfs(self.pdf_paths)
            
            # Categorize transactions
            self.update_progress.emit(70)
            self.analyzer.categorize_transactions()
            
            # Return the transactions
            self.update_progress.emit(100)
            self.finished.emit(self.analyzer.transactions)
            
        except Exception as e:
            self.error.emit(str(e))


class CategoryComboDelegate(QStyledItemDelegate):
    """Custom delegate for category combo boxes in the transaction table."""
    
    def __init__(self, categories, parent=None):
        super().__init__(parent)
        self.categories = sorted(categories)
    
    def createEditor(self, parent, option, index):
        """Create the combo box editor."""
        editor = QComboBox(parent)
        editor.addItems(self.categories)
        return editor
    
    def setEditorData(self, editor, index):
        """Set the current value in the editor."""
        value = index.model().data(index, Qt.ItemDataRole.DisplayRole)
        if value:
            idx = editor.findText(value)
            if idx >= 0:
                editor.setCurrentIndex(idx)
    
    def setModelData(self, editor, model, index):
        """Get the value from the editor and set it in the model."""
        value = editor.currentText()
        model.setData(index, value, Qt.ItemDataRole.EditRole)


class CategoryEditorDialog(QDialog):
    """Dialog for editing business expense categories."""
    
    def __init__(self, categories, parent=None):
        super().__init__(parent)
        self.categories = categories.copy()
        self.setWindowTitle("Edit Business Categories")
        self.setMinimumSize(600, 500)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Instructions
        instructions = QLabel(
            "Edit your business expense categories and keywords below. "
            "Each line in the keywords box should contain one keyword."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Category selector
        category_layout = QHBoxLayout()
        category_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems(self.categories.keys())
        self.category_combo.currentTextChanged.connect(self.load_category)
        category_layout.addWidget(self.category_combo)
        
        # Add/Remove category buttons
        self.add_category_btn = QPushButton("Add Category")
        self.add_category_btn.clicked.connect(self.add_category)
        category_layout.addWidget(self.add_category_btn)
        
        self.remove_category_btn = QPushButton("Remove Category")
        self.remove_category_btn.clicked.connect(self.remove_category)
        category_layout.addWidget(self.remove_category_btn)
        
        layout.addLayout(category_layout)
        
        # Category name editor
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Category Name:"))
        self.category_name = QLineEdit()
        self.category_name.textChanged.connect(self.update_category_name)
        name_layout.addWidget(self.category_name)
        layout.addLayout(name_layout)
        
        # Keywords editor
        layout.addWidget(QLabel("Keywords (one per line):"))
        self.keywords_edit = QTextEdit()
        self.keywords_edit.textChanged.connect(self.update_keywords)
        layout.addWidget(self.keywords_edit)
        
        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        self.setLayout(layout)
        
        # Load the first category
        if self.category_combo.count() > 0:
            self.load_category(self.category_combo.currentText())
    
    def load_category(self, category_name):
        """Load the selected category into the editor."""
        if not category_name:
            return
            
        self.category_name.setText(category_name)
        keywords = self.categories.get(category_name, [])
        self.keywords_edit.setText("\n".join(keywords))
    
    def update_category_name(self, new_name):
        """Update the category name."""
        if not new_name or new_name == self.category_combo.currentText():
            return
            
        old_name = self.category_combo.currentText()
        if old_name in self.categories:
            # Store the keywords under the new name
            keywords = self.categories.pop(old_name)
            self.categories[new_name] = keywords
            
            # Update the combo box
            self.category_combo.blockSignals(True)
            current_index = self.category_combo.currentIndex()
            self.category_combo.removeItem(current_index)
            self.category_combo.insertItem(current_index, new_name)
            self.category_combo.setCurrentIndex(current_index)
            self.category_combo.blockSignals(False)
    
    def update_keywords(self):
        """Update the keywords for the current category."""
        category = self.category_combo.currentText()
        if category:
            # Split the text by newlines and filter out empty lines
            keywords = [line.strip() for line in self.keywords_edit.toPlainText().split('\n') if line.strip()]
            self.categories[category] = keywords
    
    def add_category(self):
        """Add a new category."""
        new_name = "New Category"
        counter = 1
        while new_name in self.categories:
            new_name = f"New Category {counter}"
            counter += 1
            
        self.categories[new_name] = []
        self.category_combo.addItem(new_name)
        self.category_combo.setCurrentText(new_name)
    
    def remove_category(self):
        """Remove the current category."""
        category = self.category_combo.currentText()
        if category and len(self.categories) > 1:
            # Remove from the dictionary
            self.categories.pop(category, None)
            
            # Remove from the combo box
            self.category_combo.removeItem(self.category_combo.currentIndex())
        else:
            QMessageBox.warning(
                self, 
                "Cannot Remove Category", 
                "You must have at least one category."
            )


class ScheduleCDialog(QDialog):
    """Dialog for displaying Schedule C data."""
    
    def __init__(self, schedule_c_data, parent=None):
        super().__init__(parent)
        self.schedule_c_data = schedule_c_data
        self.setWindowTitle("Schedule C Data")
        self.setMinimumSize(600, 500)
        self.setup_ui()
        
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Instructions
        instructions = QLabel(
            "This is a preview of your Schedule C data based on the categorized transactions. "
            "You can use this information to help fill out your Schedule C tax form."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        
        # Schedule C table
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Line Item", "Amount"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        
        # Populate table
        self.table.setRowCount(len(self.schedule_c_data))
        for i, (line_item, amount) in enumerate(self.schedule_c_data.items()):
            # Line item
            line_item_widget = QTableWidgetItem(line_item)
            self.table.setItem(i, 0, line_item_widget)
            
            # Amount
            amount_widget = QTableWidgetItem(f"${amount:.2f}")
            amount_widget.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 1, amount_widget)
        
        layout.addWidget(self.table)
        
        # Export button
        export_btn = QPushButton("Export to Excel")
        export_btn.clicked.connect(self.export_to_excel)
        layout.addWidget(export_btn)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        
        self.setLayout(layout)
    
    def export_to_excel(self):
        """Export Schedule C data to Excel."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Schedule C Data", "schedule_c_data.xlsx", "Excel Files (*.xlsx)"
        )
        if file_path:
            if not file_path.endswith('.xlsx'):
                file_path += '.xlsx'
            
            try:
                # Create DataFrame and export to Excel
                data = {'Line Item': [], 'Amount': []}
                for line_item, amount in self.schedule_c_data.items():
                    data['Line Item'].append(line_item)
                    data['Amount'].append(amount)
                
                df = pd.DataFrame(data)
                df.to_excel(file_path, index=False)
                
                QMessageBox.information(
                    self, 
                    "Export Complete", 
                    f"Schedule C data exported to {file_path}"
                )
            except Exception as e:
                QMessageBox.critical(
                    self, 
                    "Export Error", 
                    f"Failed to export Schedule C data: {e}"
                )


class BankStatementGUI(QMainWindow):
    """Main window for the bank statement analyzer GUI."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bank Statement Analyzer")
        self.setMinimumSize(1000, 700)
        
        self.transactions = []
        self.categories_path = None
        self.pdf_paths = []
        self.output_path = None
        self.analyzer = None
        self.transaction_indices = {}  # Map to track transaction indices in the table
        
        self.setup_ui()
    
    def setup_ui(self):
        """Set up the user interface."""
        # Main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # File selection section
        file_group = QGroupBox("Input Files")
        file_layout = QGridLayout()
        
        # PDF file selection
        file_layout.addWidget(QLabel("Bank Statement PDF:"), 0, 0)
        self.pdf_path_label = QLabel("No files selected")
        file_layout.addWidget(self.pdf_path_label, 0, 1)
        
        pdf_buttons_layout = QHBoxLayout()
        self.browse_pdf_btn = QPushButton("Browse Single...")
        self.browse_pdf_btn.clicked.connect(self.browse_pdf)
        pdf_buttons_layout.addWidget(self.browse_pdf_btn)
        
        self.browse_multiple_pdf_btn = QPushButton("Browse Multiple...")
        self.browse_multiple_pdf_btn.clicked.connect(self.browse_multiple_pdfs)
        pdf_buttons_layout.addWidget(self.browse_multiple_pdf_btn)
        
        self.batch_folder_btn = QPushButton("Select Folder...")
        self.batch_folder_btn.clicked.connect(self.select_batch_folder)
        pdf_buttons_layout.addWidget(self.batch_folder_btn)
        
        file_layout.addLayout(pdf_buttons_layout, 0, 2)
        
        # Categories file selection
        file_layout.addWidget(QLabel("Categories File:"), 1, 0)
        self.categories_path_label = QLabel("Using default categories")
        file_layout.addWidget(self.categories_path_label, 1, 1)
        self.browse_categories_btn = QPushButton("Browse...")
        self.browse_categories_btn.clicked.connect(self.browse_categories)
        file_layout.addWidget(self.browse_categories_btn, 1, 2)
        
        # Edit categories button
        self.edit_categories_btn = QPushButton("Edit Categories...")
        self.edit_categories_btn.clicked.connect(self.edit_categories)
        file_layout.addWidget(self.edit_categories_btn, 1, 3)
        
        # Output file selection
        file_layout.addWidget(QLabel("Output Excel File:"), 2, 0)
        self.output_path_label = QLabel("categorized_transactions.xlsx")
        file_layout.addWidget(self.output_path_label, 2, 1)
        self.browse_output_btn = QPushButton("Browse...")
        self.browse_output_btn.clicked.connect(self.browse_output)
        file_layout.addWidget(self.browse_output_btn, 2, 2)
        
        file_group.setLayout(file_layout)
        main_layout.addWidget(file_group)
        
        # Process button and progress bar
        process_layout = QHBoxLayout()
        self.process_btn = QPushButton("Process Bank Statement(s)")
        self.process_btn.setMinimumHeight(40)
        self.process_btn.clicked.connect(self.process_pdf)
        process_layout.addWidget(self.process_btn)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        process_layout.addWidget(self.progress_bar)
        
        self.save_btn = QPushButton("Save to Excel")
        self.save_btn.clicked.connect(self.save_to_excel)
        self.save_btn.setEnabled(False)
        process_layout.addWidget(self.save_btn)
        
        self.schedule_c_btn = QPushButton("Generate Schedule C")
        self.schedule_c_btn.clicked.connect(self.show_schedule_c)
        self.schedule_c_btn.setEnabled(False)
        process_layout.addWidget(self.schedule_c_btn)
        
        main_layout.addLayout(process_layout)
        
        # Results tabs
        self.tabs = QTabWidget()
        
        # All transactions tab
        self.all_transactions_tab = QWidget()
        all_transactions_layout = QVBoxLayout()
        
        # Search bar for transactions
        search_layout = QHBoxLayout()
        search_label = QLabel("Search Transactions:")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Enter text to search in transaction descriptions...")
        self.search_input.textChanged.connect(self.search_transactions)
        self.search_clear_btn = QPushButton("Clear")
        self.search_clear_btn.clicked.connect(self.clear_search)
        
        search_layout.addWidget(search_label)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_clear_btn)
        all_transactions_layout.addLayout(search_layout)
        
        # All transactions table
        self.all_transactions_table = QTableWidget()
        self.all_transactions_table.setColumnCount(4)
        self.all_transactions_table.setHorizontalHeaderLabels(["Date", "Description", "Amount", "Category"])
        self.all_transactions_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        all_transactions_layout.addWidget(self.all_transactions_table)
        
        self.all_transactions_tab.setLayout(all_transactions_layout)
        self.tabs.addTab(self.all_transactions_tab, "All Transactions")
        
        # Category summary tab
        self.category_summary_table = QTableWidget()
        self.category_summary_table.setColumnCount(2)
        self.category_summary_table.setHorizontalHeaderLabels(["Category", "Total Amount"])
        self.category_summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.category_summary_table, "Category Summary")
        
        main_layout.addWidget(self.tabs)
        
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
    
    def browse_pdf(self):
        """Open a file dialog to select a single PDF file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Bank Statement PDF", "", "PDF Files (*.pdf)"
        )
        if file_path:
            self.pdf_paths = [file_path]
            self.pdf_path_label.setText(os.path.basename(file_path))
            
            # Auto-generate output path based on PDF name
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            self.output_path = f"{base_name}_categorized.xlsx"
            self.output_path_label.setText(self.output_path)
    
    def browse_multiple_pdfs(self):
        """Open a file dialog to select multiple PDF files."""
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Bank Statement PDFs", "", "PDF Files (*.pdf)"
        )
        if file_paths:
            self.pdf_paths = file_paths
            
            # Display the number of selected files
            if len(file_paths) == 1:
                self.pdf_path_label.setText(os.path.basename(file_paths[0]))
            else:
                self.pdf_path_label.setText(f"{len(file_paths)} PDFs selected")
            
            # Auto-generate output path
            self.output_path = "yearly_transactions.xlsx"
            self.output_path_label.setText(self.output_path)
    
    def select_batch_folder(self):
        """Open a folder dialog to select a folder containing PDF files."""
        folder_path = QFileDialog.getExistingDirectory(
            self, "Select Folder Containing Bank Statement PDFs"
        )
        if folder_path:
            # Find all PDF files in the folder
            pdf_files = [os.path.join(folder_path, f) for f in os.listdir(folder_path) 
                        if f.lower().endswith('.pdf')]
            
            if pdf_files:
                self.pdf_paths = pdf_files
                self.pdf_path_label.setText(f"{len(pdf_files)} PDFs in {os.path.basename(folder_path)}")
                
                # Auto-generate output path
                self.output_path = f"{os.path.basename(folder_path)}_transactions.xlsx"
                self.output_path_label.setText(self.output_path)
            else:
                QMessageBox.warning(
                    self, 
                    "No PDFs Found", 
                    f"No PDF files were found in the selected folder."
                )
    
    def browse_categories(self):
        """Open a file dialog to select a categories JSON file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Categories File", "", "JSON Files (*.json)"
        )
        if file_path:
            self.categories_path = file_path
            self.categories_path_label.setText(os.path.basename(file_path))
    
    def browse_output(self):
        """Open a file dialog to select an output Excel file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Excel File", "", "Excel Files (*.xlsx)"
        )
        if file_path:
            if not file_path.endswith('.xlsx'):
                file_path += '.xlsx'
            self.output_path = file_path
            self.output_path_label.setText(os.path.basename(file_path))
    
    def edit_categories(self):
        """Open the category editor dialog."""
        # Load categories from file or use defaults
        if self.categories_path and os.path.exists(self.categories_path):
            try:
                with open(self.categories_path, 'r') as f:
                    categories = json.load(f)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to load categories file: {e}")
                categories = BankStatementAnalyzer.DEFAULT_CATEGORIES
        else:
            categories = BankStatementAnalyzer.DEFAULT_CATEGORIES
        
        # Open the editor dialog
        dialog = CategoryEditorDialog(categories, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Save the updated categories
            if not self.categories_path:
                # If no categories file is selected, create one
                self.categories_path = "config/business_categories.json"
                self.categories_path_label.setText(os.path.basename(self.categories_path))
            
            try:
                with open(self.categories_path, 'w') as f:
                    json.dump(dialog.categories, f, indent=2)
                QMessageBox.information(
                    self, 
                    "Categories Saved", 
                    f"Categories saved to {self.categories_path}"
                )
            except Exception as e:
                QMessageBox.warning(
                    self, 
                    "Error", 
                    f"Failed to save categories: {e}"
                )
    
    def process_pdf(self):
        """Process the selected PDF files."""
        if not self.pdf_paths:
            QMessageBox.warning(self, "Error", "Please select at least one PDF file first.")
            return
        
        # Disable UI elements during processing
        self.process_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        
        # Create and start the worker thread
        self.worker = WorkerThread(self.pdf_paths, self.categories_path)
        self.worker.update_progress.connect(self.update_progress)
        self.worker.finished.connect(self.display_results)
        self.worker.error.connect(self.show_error)
        self.worker.start()
    
    def update_progress(self, value):
        """Update the progress bar."""
        self.progress_bar.setValue(value)
    
    def show_error(self, error_msg):
        """Display an error message."""
        QMessageBox.critical(self, "Error", f"An error occurred: {error_msg}")
        self.process_btn.setEnabled(True)
        self.progress_bar.setValue(0)
    
    def display_results(self, transactions):
        """Display the processed transactions in the UI."""
        self.transactions = transactions
        self.analyzer = self.worker.analyzer
        
        # Enable the save and Schedule C buttons
        self.save_btn.setEnabled(True)
        self.schedule_c_btn.setEnabled(True)
        
        # Get all available categories
        all_categories = sorted(list(self.analyzer.categories.keys()))
        
        # Set up the category delegate for the table
        category_delegate = CategoryComboDelegate(all_categories, self.all_transactions_table)
        self.all_transactions_table.setItemDelegateForColumn(3, category_delegate)
        
        # Populate the all transactions table
        self.all_transactions_table.setRowCount(len(transactions))
        self.transaction_indices = {}  # Reset the transaction indices map
        
        for i, transaction in enumerate(transactions):
            # Store the transaction index for later reference
            self.transaction_indices[i] = transaction
            
            # Date
            date_item = QTableWidgetItem(transaction['date'].strftime('%Y-%m-%d'))
            self.all_transactions_table.setItem(i, 0, date_item)
            
            # Description
            desc_item = QTableWidgetItem(transaction['description'])
            self.all_transactions_table.setItem(i, 1, desc_item)
            
            # Amount
            amount_item = QTableWidgetItem(f"${transaction['amount']:.2f}")
            amount_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            # Color negative amounts red
            if transaction['amount'] < 0:
                amount_item.setForeground(QColor('red'))
            self.all_transactions_table.setItem(i, 2, amount_item)
            
            # Category
            category_item = QTableWidgetItem(transaction['category'])
            category_item.setFlags(category_item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.all_transactions_table.setItem(i, 3, category_item)
        
        # Connect to the cell changed signal
        self.all_transactions_table.cellChanged.connect(self.on_category_changed)
        
        # Calculate and display category summary
        self.update_category_summary()
        
        # Re-enable the process button
        self.process_btn.setEnabled(True)
        
        # Show a success message
        QMessageBox.information(
            self, 
            "Processing Complete", 
            f"Successfully processed {len(transactions)} transactions from {len(self.pdf_paths)} PDF file(s)."
        )
    
    def on_category_changed(self, row, column):
        """Handle changes to transaction categories."""
        # Only process changes to the category column
        if column != 3 or not self.analyzer:
            return
            
        # Get the new category and transaction
        new_category = self.all_transactions_table.item(row, 3).text()
        transaction = self.transaction_indices.get(row)
        
        if not transaction:
            return
            
        # Update the transaction's category
        old_category = transaction['category']
        transaction['category'] = new_category
        
        # Ask if user wants to apply this change to similar transactions
        if old_category != new_category:
            reply = QMessageBox.question(
                self,
                "Apply to Similar Transactions",
                f"Would you like to apply the category '{new_category}' to all similar transactions?\n\n"
                f"This will help the system learn your categorization preferences.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # Learn this category for similar transactions
                description = transaction['description']
                merchant = self.analyzer.learn_category(description, new_category)
                
                if merchant:
                    # Refresh the table to show updated categories
                    self.refresh_transaction_table()
                    
                    # Show confirmation
                    QMessageBox.information(
                        self,
                        "Category Applied",
                        f"The category '{new_category}' has been applied to all transactions containing '{merchant}'.\n\n"
                        f"This pattern will be remembered for future transactions."
                    )
        
        # Update the category summary
        self.update_category_summary()
    
    def refresh_transaction_table(self):
        """Refresh the transaction table to reflect category changes."""
        # Temporarily disconnect the cellChanged signal to avoid recursive calls
        self.all_transactions_table.cellChanged.disconnect(self.on_category_changed)
        
        # Update the categories in the table
        for row, transaction in self.transaction_indices.items():
            category_item = self.all_transactions_table.item(row, 3)
            if category_item and category_item.text() != transaction['category']:
                category_item.setText(transaction['category'])
        
        # Reconnect the signal
        self.all_transactions_table.cellChanged.connect(self.on_category_changed)
    
    def update_category_summary(self):
        """Update the category summary table based on current transactions."""
        if not self.transactions:
            return
            
        # Calculate category totals
        category_totals = {}
        for transaction in self.transactions:
            category = transaction['category']
            if category not in category_totals:
                category_totals[category] = 0
            category_totals[category] += transaction['amount']
        
        # Populate the category summary table
        self.category_summary_table.setRowCount(len(category_totals))
        for i, (category, amount) in enumerate(category_totals.items()):
            # Category
            category_item = QTableWidgetItem(category)
            self.category_summary_table.setItem(i, 0, category_item)
            
            # Amount
            amount_item = QTableWidgetItem(f"${amount:.2f}")
            amount_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            # Color negative amounts red
            if amount < 0:
                amount_item.setForeground(QColor('red'))
            self.category_summary_table.setItem(i, 1, amount_item)
    
    def show_schedule_c(self):
        """Generate and display Schedule C data."""
        if not self.transactions or not self.analyzer:
            QMessageBox.warning(self, "Error", "No transactions to generate Schedule C data.")
            return
        
        # Generate Schedule C data
        schedule_c_data = self.analyzer.generate_schedule_c_data()
        
        if not schedule_c_data:
            QMessageBox.warning(self, "Error", "Failed to generate Schedule C data.")
            return
        
        # Show Schedule C dialog
        dialog = ScheduleCDialog(schedule_c_data, self)
        dialog.exec()
    
    def save_to_excel(self):
        """Save the processed transactions to an Excel file."""
        if not self.transactions:
            QMessageBox.warning(self, "Error", "No transactions to save.")
            return
        
        if not self.output_path:
            self.output_path = "categorized_transactions.xlsx"
        
        try:
            # Create an analyzer instance and populate it with our transactions
            analyzer = BankStatementAnalyzer()
            analyzer.transactions = self.transactions
            
            # Load categories to ensure we have the correct category names for sheets
            if self.categories_path:
                analyzer.load_custom_categories(self.categories_path)
            
            # Save to Excel
            analyzer.save_to_excel(self.output_path)
            
            QMessageBox.information(
                self, 
                "Save Complete", 
                f"Transactions saved to {self.output_path}"
            )
        except Exception as e:
            QMessageBox.critical(
                self, 
                "Error", 
                f"Failed to save Excel file: {e}"
            )
    
    def search_transactions(self):
        """Search transactions based on the search input."""
        search_text = self.search_input.text().lower()
        
        # Show all rows if search is empty
        if not search_text:
            for row in range(self.all_transactions_table.rowCount()):
                self.all_transactions_table.setRowHidden(row, False)
            return
        
        # Hide rows that don't match the search
        for row in range(self.all_transactions_table.rowCount()):
            description_item = self.all_transactions_table.item(row, 1)
            if description_item:
                description = description_item.text().lower()
                if search_text in description:
                    self.all_transactions_table.setRowHidden(row, False)
                else:
                    self.all_transactions_table.setRowHidden(row, True)
    
    def clear_search(self):
        """Clear the search input and show all transactions."""
        self.search_input.clear()
        for row in range(self.all_transactions_table.rowCount()):
            self.all_transactions_table.setRowHidden(row, False)


def main():
    """Main function to run the GUI application."""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Use Fusion style for a consistent look across platforms
    
    window = BankStatementGUI()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
