#!/usr/bin/env python3
"""
Fix existing blog articles:
1. Remove date display from post-meta
2. Update old header/footer to new dynamic ones
3. Fix any other issues

Run: python3 fix-blog-articles.py
"""

import os
import re
import glob

BLOG_DIR = os.path.dirname(os.path.abspath(__file__))

def fix_article(filepath):
    """Fix a single blog article."""
    with open(filepath, 'r') as f:
        content = f.read()
    
    original = content
    changes = []
    
    # 1. Remove date from post-meta (keep only read time)
    # Pattern: <span><i class="fas fa-calendar"></i> January 2026</span>
    date_pattern = r'\s*<span><i class="fas fa-calendar"></i>[^<]+</span>'
    if re.search(date_pattern, content):
        content = re.sub(date_pattern, '', content)
        changes.append("Removed date display")
    
    # 2. Replace old static header with dynamic header
    old_header_patterns = [
        r'<header class="site-header">.*?</header>',
        r'<nav class="main-nav">.*?</nav>',
    ]
    
    # Check if using old header (has actual header HTML instead of div#blog-header)
    if '<header class="site-header">' in content and '<div id="blog-header"></div>' not in content:
        # Replace old header with dynamic one
        content = re.sub(
            r'<header class="site-header">.*?</header>\s*',
            '<div id="blog-header"></div>\n\n',
            content,
            flags=re.DOTALL
        )
        changes.append("Replaced old header with dynamic header")
    
    # 3. Replace old static footer with dynamic footer
    if '<footer class="site-footer">' in content and '<div id="blog-footer"></div>' not in content:
        content = re.sub(
            r'<footer class="site-footer">.*?</footer>\s*',
            '<div id="blog-footer"></div>\n\n',
            content,
            flags=re.DOTALL
        )
        changes.append("Replaced old footer with dynamic footer")
    
    # 4. Ensure components.js is included
    if '/blog/js/components.js' not in content:
        content = content.replace(
            '<script src="/js/main.js"></script>',
            '<script src="/js/main.js"></script>\n  <script src="/blog/js/components.js"></script>'
        )
        changes.append("Added components.js")
    
    # 5. Fix any double components.js includes
    content = re.sub(
        r'(<script src="/blog/js/components.js"></script>\s*){2,}',
        '<script src="/blog/js/components.js"></script>\n',
        content
    )
    
    # Save if changed
    if content != original:
        with open(filepath, 'w') as f:
            f.write(content)
        return changes
    
    return None

def main():
    print("Blog Article Fixer")
    print("=" * 50)
    
    # Find all HTML files in blog subdirectories
    patterns = [
        os.path.join(BLOG_DIR, '*-websites', '*.html'),
        os.path.join(BLOG_DIR, '*-websites', 'index.html'),
    ]
    
    all_files = set()
    for pattern in patterns:
        all_files.update(glob.glob(pattern))
    
    # Also check main blog index
    main_index = os.path.join(BLOG_DIR, 'index.html')
    if os.path.exists(main_index):
        all_files.add(main_index)
    
    fixed_count = 0
    for filepath in sorted(all_files):
        changes = fix_article(filepath)
        if changes:
            rel_path = os.path.relpath(filepath, BLOG_DIR)
            print(f"Fixed: {rel_path}")
            for change in changes:
                print(f"  - {change}")
            fixed_count += 1
    
    print()
    print(f"Fixed {fixed_count} files")

if __name__ == '__main__':
    main()
