#!/usr/bin/env python3
"""
Test Generic Parser Against All PDFs
------------------------------------
This script tests the new GenericRegexParser against all PDF files
in the Statements directories to evaluate its effectiveness.
"""

import os
import sys
import time
import pdfplumber
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bank_parsers.generic_regex import GenericRegexParser
from bank_parsers import parser_registry


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from PDF file."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            return text
    except Exception as e:
        print(f"Error extracting text from {pdf_path}: {e}")
        return ""


def test_parser_on_pdf(pdf_path: str, parser: GenericRegexParser) -> Dict[str, Any]:
    """Test the parser on a single PDF and return results."""
    print(f"\nTesting: {pdf_path}")
    
    # Extract text from PDF
    text = extract_text_from_pdf(pdf_path)
    if not text:
        return {
            'pdf_path': pdf_path,
            'status': 'failed',
            'error': 'Could not extract text from PDF',
            'transactions_found': 0,
            'account_info': {}
        }
    
    start_time = time.time()
    
    try:
        # Test if parser can handle this PDF
        can_parse = parser.can_parse(text)
        print(f"  Can parse: {can_parse}")
        
        if not can_parse:
            return {
                'pdf_path': pdf_path,
                'status': 'skipped',
                'error': 'Parser cannot handle this PDF format',
                'transactions_found': 0,
                'account_info': {}
            }
        
        # Extract transactions
        transactions = parser.extract_transactions(text)
        print(f"  Transactions found: {len(transactions)}")
        
        # Extract account info
        account_info = parser.get_account_info(text)
        print(f"  Account info: {account_info}")
        
        # Show sample transactions
        if transactions:
            print("  Sample transactions:")
            for i, txn in enumerate(transactions[:3]):
                date_str = txn['date'].strftime('%Y-%m-%d') if txn['date'] else 'No date'
                print(f"    {i+1}. {date_str} | {txn['description'][:50]}... | ${txn['amount']}")
        
        processing_time = time.time() - start_time
        
        return {
            'pdf_path': pdf_path,
            'status': 'success',
            'error': None,
            'transactions_found': len(transactions),
            'account_info': account_info,
            'processing_time': processing_time,
            'sample_transactions': transactions[:5]  # Keep first 5 for analysis
        }
        
    except Exception as e:
        processing_time = time.time() - start_time
        print(f"  Error: {e}")
        return {
            'pdf_path': pdf_path,
            'status': 'error',
            'error': str(e),
            'transactions_found': 0,
            'account_info': {},
            'processing_time': processing_time
        }


def find_all_pdfs(statements_dir: str) -> List[str]:
    """Find all PDF files in the Statements directory."""
    pdf_files = []
    statements_path = Path(statements_dir)
    
    if not statements_path.exists():
        print(f"Statements directory not found: {statements_dir}")
        return pdf_files
    
    # Walk through all subdirectories
    for root, dirs, files in os.walk(statements_path):
        for file in files:
            if file.lower().endswith('.pdf'):
                pdf_files.append(os.path.join(root, file))
    
    return sorted(pdf_files)


def test_existing_parsers_comparison(pdf_files: List[str], max_files: int = 10) -> Dict[str, Any]:
    """Test existing parsers vs generic parser on a sample of files."""
    print(f"\n{'='*60}")
    print("COMPARISON: Existing Parsers vs Generic Parser")
    print(f"{'='*60}")
    
    # Test a sample of files
    test_files = pdf_files[:max_files]
    results = {
        'existing_parser_success': 0,
        'generic_parser_success': 0,
        'both_success': 0,
        'neither_success': 0,
        'details': []
    }
    
    generic_parser = GenericRegexParser()
    
    for pdf_path in test_files:
        print(f"\nComparing parsers on: {os.path.basename(pdf_path)}")
        
        # Extract text
        text = extract_text_from_pdf(pdf_path)
        if not text:
            continue
        
        # Test existing parser
        existing_parser = parser_registry.get_parser(text)
        existing_success = False
        existing_transactions = 0
        
        if existing_parser and existing_parser.bank_name != "Generic (Auto-detect)":
            try:
                existing_txns = existing_parser.extract_transactions(text)
                existing_transactions = len(existing_txns)
                existing_success = existing_transactions > 0
                print(f"  Existing parser ({existing_parser.bank_name}): {existing_transactions} transactions")
            except Exception as e:
                print(f"  Existing parser error: {e}")
        else:
            print("  No existing parser found")
        
        # Test generic parser
        generic_success = False
        generic_transactions = 0
        
        if generic_parser.can_parse(text):
            try:
                generic_txns = generic_parser.extract_transactions(text)
                generic_transactions = len(generic_txns)
                generic_success = generic_transactions > 0
                print(f"  Generic parser: {generic_transactions} transactions")
            except Exception as e:
                print(f"  Generic parser error: {e}")
        else:
            print("  Generic parser cannot handle this PDF")
        
        # Update results
        if existing_success and generic_success:
            results['both_success'] += 1
        elif existing_success:
            results['existing_parser_success'] += 1
        elif generic_success:
            results['generic_parser_success'] += 1
        else:
            results['neither_success'] += 1
        
        results['details'].append({
            'file': os.path.basename(pdf_path),
            'existing_parser': existing_parser.bank_name if existing_parser else "None",
            'existing_transactions': existing_transactions,
            'generic_transactions': generic_transactions,
            'existing_success': existing_success,
            'generic_success': generic_success
        })
    
    return results


def main():
    """Main test function."""
    print("Generic Bank Parser Test Suite")
    print("=" * 50)
    
    # Find all PDF files
    statements_dir = "/Users/rjones/Documents/Programming files/statement_organizer/Statements"
    pdf_files = find_all_pdfs(statements_dir)
    
    print(f"Found {len(pdf_files)} PDF files to test")
    
    if not pdf_files:
        print("No PDF files found. Exiting.")
        return
    
    # Initialize the generic parser
    generic_parser = GenericRegexParser()
    
    # Test on a sample of files first (to avoid overwhelming output)
    max_test_files = 20
    test_files = pdf_files[:max_test_files]
    
    print(f"\nTesting generic parser on first {len(test_files)} files...")
    
    # Test each PDF
    results = []
    successful_tests = 0
    
    for pdf_path in test_files:
        result = test_parser_on_pdf(pdf_path, generic_parser)
        results.append(result)
        
        if result['status'] == 'success' and result['transactions_found'] > 0:
            successful_tests += 1
    
    # Summary statistics
    print(f"\n{'='*60}")
    print("GENERIC PARSER TEST RESULTS")
    print(f"{'='*60}")
    print(f"Total files tested: {len(results)}")
    print(f"Successful extractions: {successful_tests}")
    print(f"Success rate: {successful_tests/len(results)*100:.1f}%")
    
    # Status breakdown
    status_counts = {}
    for result in results:
        status = result['status']
        status_counts[status] = status_counts.get(status, 0) + 1
    
    print(f"\nStatus breakdown:")
    for status, count in status_counts.items():
        print(f"  {status}: {count}")
    
    # Transaction count statistics
    transaction_counts = [r['transactions_found'] for r in results if r['status'] == 'success']
    if transaction_counts:
        print(f"\nTransaction extraction statistics:")
        print(f"  Average transactions per file: {sum(transaction_counts)/len(transaction_counts):.1f}")
        print(f"  Max transactions found: {max(transaction_counts)}")
        print(f"  Min transactions found: {min(transaction_counts)}")
    
    # Show files with most transactions
    successful_results = [r for r in results if r['status'] == 'success' and r['transactions_found'] > 0]
    successful_results.sort(key=lambda x: x['transactions_found'], reverse=True)
    
    print(f"\nTop performing files:")
    for i, result in enumerate(successful_results[:5]):
        filename = os.path.basename(result['pdf_path'])
        print(f"  {i+1}. {filename}: {result['transactions_found']} transactions")
    
    # Compare with existing parsers
    comparison_results = test_existing_parsers_comparison(pdf_files, max_files=15)
    
    print(f"\n{'='*60}")
    print("PARSER COMPARISON RESULTS")
    print(f"{'='*60}")
    print(f"Files where both parsers succeeded: {comparison_results['both_success']}")
    print(f"Files where only existing parser succeeded: {comparison_results['existing_parser_success']}")
    print(f"Files where only generic parser succeeded: {comparison_results['generic_parser_success']}")
    print(f"Files where neither parser succeeded: {comparison_results['neither_success']}")
    
    # Save detailed results to CSV
    df = pd.DataFrame(results)
    output_file = "generic_parser_test_results.csv"
    df.to_csv(output_file, index=False)
    print(f"\nDetailed results saved to: {output_file}")
    
    # Save comparison results
    comparison_df = pd.DataFrame(comparison_results['details'])
    comparison_output = "parser_comparison_results.csv"
    comparison_df.to_csv(comparison_output, index=False)
    print(f"Comparison results saved to: {comparison_output}")
    
    print(f"\nTest completed! Generic parser shows promise as a fallback option.")
    
    # Test the K_cluster_test files specifically
    print(f"\n{'='*60}")
    print("TESTING K_CLUSTER_TEST FILES")
    print(f"{'='*60}")
    
    k_cluster_dir = "/Users/rjones/Documents/Programming files/statement_organizer/K_cluster_test"
    k_cluster_pdfs = find_all_pdfs(k_cluster_dir)
    
    print(f"Found {len(k_cluster_pdfs)} PDF files in K_cluster_test directory")
    
    for pdf_path in k_cluster_pdfs:
        result = test_parser_on_pdf(pdf_path, generic_parser)
        print(f"Result: {result['status']} - {result['transactions_found']} transactions")


if __name__ == "__main__":
    main()
