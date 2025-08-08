#!/usr/bin/env python3
"""
Create Categories Utility
------------------------
Helper script to create and customize business expense categories for the bank statement analyzer.
"""

import json
import os
import argparse


def create_default_categories_file(output_path):
    """Create a default categories JSON file that users can customize."""
    default_categories = {
        "Office Supplies": ["staples", "office depot", "amazon", "office supplies"],
        "Travel": ["airline", "hotel", "airbnb", "uber", "lyft", "taxi", "rental car"],
        "Meals & Entertainment": ["restaurant", "cafe", "coffee", "doordash", "grubhub", "ubereats"],
        "Software & Subscriptions": ["github", "aws", "google cloud", "microsoft", "zoom", "slack", "adobe"],
        "Marketing": ["facebook ads", "google ads", "marketing", "advertising"],
        "Professional Services": ["lawyer", "accountant", "consulting", "legal"],
        "Utilities": ["phone", "internet", "electricity", "water", "gas"],
        "Rent": ["rent", "lease", "coworking"],
        "Other Business Expenses": []  # Catch-all category
    }
    
    with open(output_path, 'w') as f:
        json.dump(default_categories, f, indent=2)
    
    print(f"Created default categories file at {output_path}")
    print("You can now edit this file to customize categories and keywords for your business.")


def main():
    parser = argparse.ArgumentParser(description='Create and manage business expense categories.')
    parser.add_argument('-o', '--output', default='business_categories.json',
                        help='Output file path for categories (default: business_categories.json)')
    
    args = parser.parse_args()
    create_default_categories_file(args.output)


if __name__ == "__main__":
    main()
