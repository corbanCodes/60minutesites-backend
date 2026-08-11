#!/usr/bin/env python3
"""
Remove existing articles from master CSV to avoid duplicates.
Creates blog-articles-remaining.csv with only articles that don't exist yet.
"""

import os
import csv
import glob

BLOG_DIR = os.path.dirname(os.path.abspath(__file__))

def get_existing_slugs():
    """Get all slugs of existing articles."""
    existing = set()
    
    # Find all HTML files in industry folders
    for filepath in glob.glob(os.path.join(BLOG_DIR, '*-websites', '*.html')):
        filename = os.path.basename(filepath)
        if filename != 'index.html':
            slug = filename.replace('.html', '')
            existing.add(slug)
    
    return existing

def clean_csv():
    existing = get_existing_slugs()
    print(f"Found {len(existing)} existing articles")
    
    input_file = os.path.join(BLOG_DIR, 'blog-articles-master.csv')
    output_file = os.path.join(BLOG_DIR, 'blog-articles-remaining.csv')
    
    kept = 0
    removed = 0
    
    with open(input_file, 'r') as infile, open(output_file, 'w', newline='') as outfile:
        reader = csv.DictReader(infile)
        writer = csv.DictWriter(outfile, fieldnames=reader.fieldnames)
        writer.writeheader()
        
        for row in reader:
            if row['slug'] in existing:
                removed += 1
            else:
                writer.writerow(row)
                kept += 1
    
    print(f"Removed {removed} existing articles")
    print(f"Kept {kept} remaining articles")
    print(f"Created: {output_file}")

if __name__ == '__main__':
    clean_csv()
