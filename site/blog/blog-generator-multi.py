#!/usr/bin/env python3
"""
Multi-CSV Blog Generator
Run multiple category generators in parallel on different ports.

Usage:
  python3 blog-generator-multi.py

This will start separate Flask apps for each category CSV on different ports.
"""

import subprocess
import sys
import os
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Category CSVs and their ports
CATEGORIES = [
    ('blog-articles-web-design.csv', 'web-design', 5051),
    ('blog-articles-local-seo.csv', 'local-seo', 5052),
    ('blog-articles-comparisons.csv', 'comparisons', 5053),
    ('blog-articles-getting-started.csv', 'getting-started', 5054),
    ('blog-articles-website-cost.csv', 'website-cost', 5055),
]

def main():
    print("=" * 60)
    print("Multi-CSV Blog Generator")
    print("=" * 60)
    print()
    print("This will start generators for each category on different ports.")
    print("You can run them all simultaneously with the same API key.")
    print()
    
    for csv_file, folder, port in CATEGORIES:
        csv_path = os.path.join(SCRIPT_DIR, csv_file)
        if os.path.exists(csv_path):
            # Count articles
            with open(csv_path, 'r') as f:
                count = sum(1 for _ in f) - 1  # Subtract header
            print(f"  {folder}: {count} articles → http://localhost:{port}")
        else:
            print(f"  {folder}: CSV not found ({csv_file})")
    
    print()
    print("To start a specific category generator, run:")
    print()
    for csv_file, folder, port in CATEGORIES:
        print(f"  CSV_FILE={csv_file} FOLDER={folder} PORT={port} python3 blog-generator-category.py")
    print()
    print("Or use the individual commands below to open in separate terminals:")
    print()
    
    for csv_file, folder, port in CATEGORIES:
        print(f"# {folder.upper()}")
        print(f"cd {SCRIPT_DIR} && python3 blog-generator-category.py {csv_file} {folder} {port}")
        print()

if __name__ == '__main__':
    main()
