#!/usr/bin/env python3
"""
Fix cliche phrases in existing blog articles.
Run this to clean up "In today's digital age" and similar phrases.
"""

import os
import glob
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Cliche replacements
REPLACEMENTS = [
    # "In today's..." variations - the worst offenders (with and without comma)
    ("In today's digital age, ", ""),
    ("In today's digital age,", ""),
    ("In today's digital age ", ""),
    ("In today's digital age", ""),
    ("In today's digital landscape, ", ""),
    ("In today's digital landscape,", ""),
    ("In today's digital landscape ", ""),
    ("In today's digital landscape", ""),
    ("In today's competitive market, ", "With so much competition, "),
    ("In today's competitive market,", "With so much competition,"),
    ("In today's competitive market ", "With so much competition, "),
    ("In today's competitive market", "With so much competition"),
    ("In today's fast-paced world, ", ""),
    ("In today's fast-paced world,", ""),
    ("In today's fast-paced world ", ""),
    ("In today's fast-paced world", ""),
    ("In today's business landscape, ", ""),
    ("In today's business landscape,", ""),
    ("In today's business landscape ", ""),
    ("In today's business landscape", ""),
    ("In the modern world, ", ""),
    ("In the modern world,", ""),
    ("In the modern world ", ""),
    ("In the modern world", ""),
    ("In this day and age, ", ""),
    ("In this day and age,", ""),
    ("In this day and age ", ""),
    ("In this day and age", ""),
    ("In today's economy, ", ""),
    ("In today's economy,", ""),
    ("In today's economy ", ""),
    ("In today's economy", ""),
    ("In the digital era, ", ""),
    ("In the digital era,", ""),
    ("In the digital era ", ""),
    ("In the digital era", ""),
    # "In today's digital world" - MISSED THIS ONE
    ("In today's digital world, ", ""),
    ("In today's digital world,", ""),
    ("In today's digital world ", ""),
    ("In today's digital world", ""),
    # More variations
    ("In today's world, ", ""),
    ("In today's world,", ""),
    ("In today's world ", ""),
    ("In today's world", ""),
    ("In the current digital landscape, ", ""),
    ("In the current digital landscape,", ""),
    ("In the current digital landscape ", ""),
    ("In the current digital landscape", ""),
    ("In an increasingly digital world, ", ""),
    ("In an increasingly digital world,", ""),
    ("In an increasingly digital world ", ""),
    ("In an increasingly digital world", ""),
    # Other cliches
    ("As we all know,", ""),
    ("As we all know", ""),
    ("It's no secret that", ""),
    ("It goes without saying that", ""),
    ("Needless to say,", ""),
    ("At the end of the day,", "Ultimately,"),
    ("At the end of the day", "Ultimately"),
    ("It is important to note that", ""),
    ("It's worth noting that", ""),
    ("First and foremost,", "First,"),
    ("Last but not least,", "Finally,"),
]


def fix_file(filepath):
    """Fix cliches in a single file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original = content
        
        # First do exact replacements
        for old, new in REPLACEMENTS:
            content = content.replace(old, new)
        
        # Then use regex to catch ALL "In today's..." variations
        # This catches: "In today's [anything], " or "In today's [anything] "
        content = re.sub(r"In today's [^,\"<]{1,50},\s*", "", content)
        content = re.sub(r"In today's [^,\"<]{1,50}\s+", "", content)
        
        # Catch "In the [modern/digital/current]..." variations
        content = re.sub(r"In the (?:modern|digital|current|competitive)[^,\"<]{1,50},\s*", "", content)
        content = re.sub(r"In the (?:modern|digital|current|competitive)[^,\"<]{1,50}\s+", "", content)
        
        # Catch "In an increasingly..." variations
        content = re.sub(r"In an increasingly [^,\"<]{1,50},\s*", "", content)
        content = re.sub(r"In an increasingly [^,\"<]{1,50}\s+", "", content)
        
        # Fix double spaces
        content = re.sub(r'  +', ' ', content)
        
        # Fix space after <p> tag if we removed opener
        content = re.sub(r'<p>\s+', '<p>', content)
        
        # Fix content=" with space after
        content = re.sub(r'content="\s+', 'content="', content)
        
        # Capitalize first letter after <p> if needed
        def capitalize_after_p(match):
            return match.group(1) + match.group(2).upper()
        content = re.sub(r'(<p>)([a-z])', capitalize_after_p, content)
        
        # Capitalize first letter after content=" if needed
        def capitalize_after_content(match):
            return match.group(1) + match.group(2).upper()
        content = re.sub(r'(content=")([a-z])', capitalize_after_content, content)
        
        if content != original:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return False


def main():
    print("Scanning for cliche phrases in existing articles...")
    
    # Find all HTML files in blog subdirectories
    all_files = []
    for item in os.listdir(SCRIPT_DIR):
        item_path = os.path.join(SCRIPT_DIR, item)
        if os.path.isdir(item_path) and not item.startswith('.') and item not in ['css', 'js', 'images']:
            pattern = os.path.join(item_path, '*.html')
            all_files.extend(glob.glob(pattern))
    
    print(f"Found {len(all_files)} HTML files")
    
    fixed_count = 0
    for filepath in all_files:
        if fix_file(filepath):
            fixed_count += 1
            filename = os.path.basename(filepath)
            print(f"  Fixed: {filename}")
    
    print(f"\nDone! Fixed {fixed_count} files with cliche phrases.")


if __name__ == '__main__':
    main()
