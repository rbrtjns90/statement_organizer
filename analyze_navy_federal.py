#!/usr/bin/env python3
"""
Analyze Navy Federal PDF statements to identify transaction formats
"""

import os
import re
import sys

def analyze_navy_federal_pdfs():
    """Analyze Navy Federal PDF statements for transaction patterns."""
    
    print("🔍 Analyzing Navy Federal PDF Statements")
    print("=" * 60)
    
    statements_dir = "Statements/Navy Federal"
    
    if not os.path.exists(statements_dir):
        print(f"❌ Directory not found: {statements_dir}")
        return
    
    pdf_files = [f for f in os.listdir(statements_dir) if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        print("❌ No PDF files found")
        return
    
    # Sort files by date (newest first)
    pdf_files.sort(reverse=True)
    
    print(f"📄 Found {len(pdf_files)} Navy Federal statements")
    
    # Analyze the most recent statement first
    latest_pdf = pdf_files[0]
    pdf_path = os.path.join(statements_dir, latest_pdf)
    
    print(f"\n📋 Analyzing latest statement: {latest_pdf}")
    print("-" * 50)
    
    try:
        import pdfplumber
        
        with pdfplumber.open(pdf_path) as pdf:
            print(f"📖 PDF has {len(pdf.pages)} pages")
            
            all_text = ""
            potential_transactions = []
            bank_identifiers = set()
            
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    all_text += page_text + "\n"
                    
                    print(f"\n📄 Page {page_num} Analysis:")
                    print("-" * 30)
                    
                    lines = page_text.split('\n')
                    for line_num, line in enumerate(lines, 1):
                        line = line.strip()
                        if not line:
                            continue
                        
                        # Look for Navy Federal identifiers
                        navy_keywords = ['navy federal', 'nfcu', 'navy federal credit union']
                        for keyword in navy_keywords:
                            if keyword.lower() in line.lower():
                                bank_identifiers.add(line)
                        
                        # Look for potential transaction lines
                        # Common patterns: date + description + amount
                        has_date = bool(re.search(r'\d{1,2}/\d{1,2}(/\d{2,4})?', line))
                        has_amount = bool(re.search(r'\$?[\d,]+\.\d{2}', line))
                        has_negative = bool(re.search(r'-\s*\$?[\d,]+\.\d{2}', line))
                        
                        if has_date and has_amount:
                            potential_transactions.append({
                                'page': page_num,
                                'line': line_num,
                                'text': line,
                                'has_negative': has_negative
                            })
                            print(f"  🎯 POTENTIAL TRANSACTION: {line}")
                        elif 'transaction' in line.lower() or 'deposit' in line.lower() or 'withdrawal' in line.lower():
                            print(f"  📋 TRANSACTION KEYWORD: {line}")
                        elif has_amount:
                            print(f"  💰 HAS AMOUNT: {line}")
                        elif has_date:
                            print(f"  📅 HAS DATE: {line}")
            
            print(f"\n🏦 Navy Federal Identifiers Found:")
            print("-" * 40)
            for identifier in sorted(bank_identifiers):
                print(f"  - {identifier}")
            
            print(f"\n💰 Transaction Analysis ({len(potential_transactions)} potential transactions):")
            print("-" * 60)
            
            # Group transactions by pattern
            transaction_patterns = {}
            
            for tx in potential_transactions:
                line = tx['text']
                
                # Try to identify the pattern
                pattern_key = "unknown"
                
                # Look for common date formats
                if re.search(r'\d{1,2}/\d{1,2}/\d{2,4}', line):
                    pattern_key = "full_date"
                elif re.search(r'\d{1,2}/\d{1,2}', line):
                    pattern_key = "month_day"
                
                # Check for negative amounts (debits vs credits)
                if tx['has_negative']:
                    pattern_key += "_negative"
                else:
                    pattern_key += "_positive"
                
                if pattern_key not in transaction_patterns:
                    transaction_patterns[pattern_key] = []
                
                transaction_patterns[pattern_key].append(line)
            
            # Show patterns
            for pattern, lines in transaction_patterns.items():
                print(f"\n📋 Pattern: {pattern} ({len(lines)} transactions)")
                for i, line in enumerate(lines[:5], 1):  # Show first 5 examples
                    print(f"  {i}. {line}")
                if len(lines) > 5:
                    print(f"  ... and {len(lines) - 5} more")
            
            # Suggest regex patterns
            print(f"\n💡 Suggested Regex Patterns:")
            print("-" * 40)
            
            suggest_navy_federal_patterns(potential_transactions)
            
    except Exception as e:
        print(f"❌ Error analyzing {latest_pdf}: {e}")
        import traceback
        traceback.print_exc()

def suggest_navy_federal_patterns(transactions):
    """Suggest regex patterns based on transaction analysis."""
    
    if not transactions:
        print("  No transactions found to analyze")
        return
    
    print("  Based on the transaction analysis, here are suggested patterns:")
    
    # Analyze a few sample transactions
    samples = [tx['text'] for tx in transactions[:10]]
    
    for i, sample in enumerate(samples, 1):
        print(f"\n  Sample {i}: {sample}")
        
        # Try to break down the components
        dates = re.findall(r'\d{1,2}/\d{1,2}(?:/\d{2,4})?', sample)
        amounts = re.findall(r'-?\s*\$?[\d,]+\.\d{2}', sample)
        
        print(f"    Dates found: {dates}")
        print(f"    Amounts found: {amounts}")
        
        # Try to identify the structure
        if dates and amounts:
            # Remove dates and amounts to see description
            temp = sample
            for date in dates:
                temp = temp.replace(date, '[DATE]')
            for amount in amounts:
                temp = temp.replace(amount, '[AMOUNT]')
            print(f"    Structure: {temp}")
    
    # Suggest common Navy Federal patterns
    suggested_patterns = [
        # Standard format: MM/DD/YYYY Description Amount
        r'(\d{1,2}/\d{1,2}/\d{2,4})\s+(.+?)\s+(-?\s*\$?[\d,]+\.\d{2})\s*$',
        
        # Short date format: MM/DD Description Amount  
        r'(\d{1,2}/\d{1,2})\s+(.+?)\s+(-?\s*\$?[\d,]+\.\d{2})\s*$',
        
        # With transaction type: MM/DD/YYYY TYPE Description Amount
        r'(\d{1,2}/\d{1,2}/\d{2,4})\s+([A-Z]+)\s+(.+?)\s+(-?\s*\$?[\d,]+\.\d{2})\s*$',
        
        # Debit/Credit format: MM/DD Description DEBIT/CREDIT Amount
        r'(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s+(.+?)\s+(DEBIT|CREDIT)\s+(-?\s*\$?[\d,]+\.\d{2})\s*$',
    ]
    
    print(f"\n  💡 Recommended regex patterns to try:")
    for i, pattern in enumerate(suggested_patterns, 1):
        print(f"    {i}. {pattern}")

if __name__ == "__main__":
    analyze_navy_federal_pdfs()
