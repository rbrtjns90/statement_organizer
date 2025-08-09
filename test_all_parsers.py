#!/usr/bin/env python3
"""
Comprehensive Parser Efficacy Test
----------------------------------
Tests all PDFs in the Statements directory against all available parsers
to evaluate parsing success rates and generate detailed statistics.
"""

import os
import sys
import time
import pdfplumber
from pathlib import Path
from typing import List, Dict, Any, Tuple
from datetime import datetime
import traceback

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bank_parsers import parser_registry
from bank_parsers.registry import initialize_parsers  # This ensures parsers are registered
from bank_parsers.generic_regex import GenericRegexParser

# Ensure parsers are initialized
initialize_parsers()


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


def test_pdf_with_all_parsers(pdf_path: str) -> Dict[str, Any]:
    """Test a single PDF with all available parsers."""
    print(f"\nTesting: {os.path.basename(pdf_path)}")
    
    # Extract text from PDF
    text = extract_text_from_pdf(pdf_path)
    if not text:
        return {
            'pdf_path': pdf_path,
            'file_name': os.path.basename(pdf_path),
            'status': 'failed',
            'error': 'Could not extract text from PDF',
            'detected_parser': None,
            'transactions_found': 0,
            'parsing_time': 0,
            'all_parser_results': {}
        }
    
    start_time = time.time()
    
    # Test with automatic parser detection (existing system)
    detected_parser = parser_registry.get_parser(text)
    detected_parser_name = detected_parser.bank_name if detected_parser else "None"
    
    print(f"  Detected parser: {detected_parser_name}")
    
    # Test detected parser
    detected_success = False
    detected_transactions = 0
    detected_error = None
    
    if detected_parser:
        try:
            transactions = detected_parser.extract_transactions(text)
            detected_transactions = len(transactions)
            detected_success = detected_transactions > 0
            print(f"  Detected parser result: {detected_transactions} transactions")
        except Exception as e:
            detected_error = str(e)
            print(f"  Detected parser error: {detected_error}")
    
    # Test all parsers individually for comprehensive analysis
    all_parser_results = {}
    
    # Get all registered parsers
    all_parsers = [
        ('Navy Federal', 'bank_parsers.navy_federal', 'NavyFederalParser'),
        ('Capital One', 'bank_parsers.capital_one', 'CapitalOneParser'),
        ('Citibank', 'bank_parsers.citibank', 'CitibankParser'),
        ('Chase', 'bank_parsers.chase', 'ChaseParser'),
        ('Bank of America', 'bank_parsers.bank_of_america', 'BankOfAmericaParser'),
        ('Generic', 'bank_parsers.generic_regex', 'GenericRegexParser')
    ]
    
    for parser_name, module_name, class_name in all_parsers:
        try:
            # Import and instantiate parser
            module = __import__(module_name, fromlist=[class_name])
            parser_class = getattr(module, class_name)
            parser = parser_class()
            
            # Test if parser can handle this PDF
            can_parse = parser.can_parse(text)
            
            if can_parse:
                try:
                    transactions = parser.extract_transactions(text)
                    transaction_count = len(transactions)
                    success = transaction_count > 0
                    error = None
                except Exception as e:
                    transaction_count = 0
                    success = False
                    error = str(e)
            else:
                transaction_count = 0
                success = False
                error = "Parser cannot handle this PDF format"
            
            all_parser_results[parser_name] = {
                'can_parse': can_parse,
                'success': success,
                'transactions': transaction_count,
                'error': error
            }
            
            print(f"  {parser_name}: {'✓' if success else '✗'} ({transaction_count} transactions)")
            
        except Exception as e:
            all_parser_results[parser_name] = {
                'can_parse': False,
                'success': False,
                'transactions': 0,
                'error': f"Parser instantiation error: {str(e)}"
            }
            print(f"  {parser_name}: ERROR - {str(e)}")
    
    parsing_time = time.time() - start_time
    
    return {
        'pdf_path': pdf_path,
        'file_name': os.path.basename(pdf_path),
        'status': 'success' if detected_success else 'failed',
        'error': detected_error,
        'detected_parser': detected_parser_name,
        'transactions_found': detected_transactions,
        'parsing_time': parsing_time,
        'all_parser_results': all_parser_results
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


def generate_statistics_report(results: List[Dict[str, Any]]) -> str:
    """Generate comprehensive statistics report."""
    total_files = len(results)
    successful_files = len([r for r in results if r['status'] == 'success'])
    failed_files = total_files - successful_files
    
    # Parser detection statistics
    parser_detection_stats = {}
    for result in results:
        parser = result['detected_parser']
        if parser not in parser_detection_stats:
            parser_detection_stats[parser] = {'count': 0, 'successful': 0, 'total_transactions': 0}
        parser_detection_stats[parser]['count'] += 1
        if result['status'] == 'success':
            parser_detection_stats[parser]['successful'] += 1
            parser_detection_stats[parser]['total_transactions'] += result['transactions_found']
    
    # Individual parser performance
    parser_performance = {}
    parser_names = ['Navy Federal', 'Capital One', 'Citibank', 'Chase', 'Bank of America', 'Generic']
    
    for parser_name in parser_names:
        parser_performance[parser_name] = {
            'can_parse_count': 0,
            'successful_count': 0,
            'total_transactions': 0,
            'error_count': 0
        }
    
    for result in results:
        for parser_name in parser_names:
            if parser_name in result['all_parser_results']:
                parser_result = result['all_parser_results'][parser_name]
                if parser_result['can_parse']:
                    parser_performance[parser_name]['can_parse_count'] += 1
                if parser_result['success']:
                    parser_performance[parser_name]['successful_count'] += 1
                    parser_performance[parser_name]['total_transactions'] += parser_result['transactions']
                if parser_result['error'] and parser_result['error'] != "Parser cannot handle this PDF format":
                    parser_performance[parser_name]['error_count'] += 1
    
    # Generate report
    report = []
    report.append("=" * 80)
    report.append("COMPREHENSIVE PARSER EFFICACY REPORT")
    report.append("=" * 80)
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    
    # Overall Statistics
    report.append("OVERALL STATISTICS")
    report.append("-" * 40)
    report.append(f"Total PDF files tested: {total_files}")
    report.append(f"Successfully parsed: {successful_files} ({successful_files/total_files*100:.1f}%)")
    report.append(f"Failed to parse: {failed_files} ({failed_files/total_files*100:.1f}%)")
    report.append("")
    
    # Parser Detection Results
    report.append("PARSER DETECTION RESULTS")
    report.append("-" * 40)
    for parser, stats in sorted(parser_detection_stats.items()):
        success_rate = stats['successful'] / stats['count'] * 100 if stats['count'] > 0 else 0
        avg_transactions = stats['total_transactions'] / stats['successful'] if stats['successful'] > 0 else 0
        report.append(f"{parser}:")
        report.append(f"  Files detected: {stats['count']}")
        report.append(f"  Successfully parsed: {stats['successful']} ({success_rate:.1f}%)")
        report.append(f"  Average transactions per file: {avg_transactions:.1f}")
        report.append("")
    
    # Individual Parser Performance
    report.append("INDIVIDUAL PARSER PERFORMANCE")
    report.append("-" * 40)
    for parser_name in parser_names:
        stats = parser_performance[parser_name]
        can_parse_rate = stats['can_parse_count'] / total_files * 100
        success_rate = stats['successful_count'] / stats['can_parse_count'] * 100 if stats['can_parse_count'] > 0 else 0
        avg_transactions = stats['total_transactions'] / stats['successful_count'] if stats['successful_count'] > 0 else 0
        
        report.append(f"{parser_name}:")
        report.append(f"  Can parse: {stats['can_parse_count']}/{total_files} ({can_parse_rate:.1f}%)")
        report.append(f"  Successful extractions: {stats['successful_count']}/{stats['can_parse_count']} ({success_rate:.1f}%)")
        report.append(f"  Total transactions extracted: {stats['total_transactions']}")
        report.append(f"  Average transactions per successful file: {avg_transactions:.1f}")
        report.append(f"  Errors encountered: {stats['error_count']}")
        report.append("")
    
    # Failed Files Analysis
    failed_results = [r for r in results if r['status'] == 'failed']
    if failed_results:
        report.append("FAILED FILES ANALYSIS")
        report.append("-" * 40)
        report.append(f"Total failed files: {len(failed_results)}")
        report.append("")
        
        # Group by error type
        error_types = {}
        for result in failed_results:
            error = result['error'] or 'No specific error'
            if error not in error_types:
                error_types[error] = []
            error_types[error].append(result['file_name'])
        
        for error, files in error_types.items():
            report.append(f"Error: {error}")
            report.append(f"  Files affected ({len(files)}):")
            for file in files[:10]:  # Show first 10 files
                report.append(f"    - {file}")
            if len(files) > 10:
                report.append(f"    ... and {len(files) - 10} more")
            report.append("")
    
    # Top Performing Files
    successful_results = [r for r in results if r['status'] == 'success']
    if successful_results:
        successful_results.sort(key=lambda x: x['transactions_found'], reverse=True)
        report.append("TOP PERFORMING FILES")
        report.append("-" * 40)
        for i, result in enumerate(successful_results[:10]):
            report.append(f"{i+1:2d}. {result['file_name']}")
            report.append(f"    Parser: {result['detected_parser']}")
            report.append(f"    Transactions: {result['transactions_found']}")
            report.append(f"    Processing time: {result['parsing_time']:.2f}s")
            report.append("")
    
    # Performance Statistics
    processing_times = [r['parsing_time'] for r in results]
    if processing_times:
        report.append("PERFORMANCE STATISTICS")
        report.append("-" * 40)
        report.append(f"Average processing time: {sum(processing_times)/len(processing_times):.2f}s")
        report.append(f"Fastest processing time: {min(processing_times):.2f}s")
        report.append(f"Slowest processing time: {max(processing_times):.2f}s")
        report.append("")
    
    # Recommendations
    report.append("RECOMMENDATIONS")
    report.append("-" * 40)
    
    # Check Generic Parser performance
    generic_stats = parser_performance.get('Generic', {})
    if generic_stats.get('successful_count', 0) > 0:
        report.append("✓ Generic Parser is working and providing fallback support")
    else:
        report.append("⚠ Generic Parser may need tuning - no successful extractions")
    
    # Check for high failure rates
    if failed_files / total_files > 0.3:
        report.append("⚠ High failure rate detected - consider:")
        report.append("  - Adding more bank-specific parsers")
        report.append("  - Improving Generic Parser training")
        report.append("  - Checking PDF quality and format compatibility")
    
    # Check parser coverage
    undetected_count = parser_detection_stats.get('None', {}).get('count', 0)
    if undetected_count > 0:
        report.append(f"⚠ {undetected_count} files had no parser detection")
        report.append("  - Consider adding parsers for these statement types")
        report.append("  - Use regex_builder.py to analyze unsupported formats")
    
    report.append("")
    report.append("=" * 80)
    
    return "\n".join(report)


def main():
    """Main test function."""
    print("Comprehensive Parser Efficacy Test")
    print("=" * 50)
    
    # Find all PDF files
    statements_dir = "/Users/rjones/Documents/Programming files/statement_organizer/Statements"
    pdf_files = find_all_pdfs(statements_dir)
    
    print(f"Found {len(pdf_files)} PDF files to test")
    
    if not pdf_files:
        print("No PDF files found. Exiting.")
        return
    
    # Test each PDF
    results = []
    start_time = time.time()
    
    print(f"\nTesting all {len(pdf_files)} PDF files...")
    print("This may take several minutes...")
    
    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"\nProgress: {i}/{len(pdf_files)} ({i/len(pdf_files)*100:.1f}%)")
        try:
            result = test_pdf_with_all_parsers(pdf_path)
            results.append(result)
        except Exception as e:
            print(f"Critical error testing {pdf_path}: {e}")
            traceback.print_exc()
            results.append({
                'pdf_path': pdf_path,
                'file_name': os.path.basename(pdf_path),
                'status': 'critical_error',
                'error': str(e),
                'detected_parser': None,
                'transactions_found': 0,
                'parsing_time': 0,
                'all_parser_results': {}
            })
    
    total_time = time.time() - start_time
    
    # Generate statistics report
    print(f"\n\nGenerating statistics report...")
    report = generate_statistics_report(results)
    
    # Save report to file
    with open("statistics.txt", "w") as f:
        f.write(report)
        f.write(f"\nTotal testing time: {total_time:.2f} seconds\n")
    
    # Print summary to console
    print("\n" + "=" * 60)
    print("TEST COMPLETED")
    print("=" * 60)
    print(f"Total files tested: {len(results)}")
    print(f"Total testing time: {total_time:.2f} seconds")
    print(f"Detailed statistics saved to: statistics.txt")
    
    # Print quick summary
    successful = len([r for r in results if r['status'] == 'success'])
    print(f"\nQuick Summary:")
    print(f"  Successfully parsed: {successful}/{len(results)} ({successful/len(results)*100:.1f}%)")
    print(f"  Average processing time: {total_time/len(results):.2f}s per file")
    
    print(f"\nFor detailed analysis, see statistics.txt")


if __name__ == "__main__":
    main()
