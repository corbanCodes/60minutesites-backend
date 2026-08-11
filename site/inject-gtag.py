#!/usr/bin/env python3
"""
Inject Google Tag (gtag.js) into all HTML pages.
Run: python3 inject-gtag.py
"""

import os
import re
from pathlib import Path

GTAG_CODE = '''<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=AW-649666163"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());

  gtag('config', 'AW-649666163');
</script>
'''

# Get the root directory (parent of this script's location)
script_dir = Path(__file__).parent
root_dir = script_dir

# Directories to skip
SKIP_DIRS = {'.git', 'node_modules', '.claude', 'favicon_io (4)', '__pycache__'}

def should_skip(path):
    """Check if path should be skipped."""
    parts = path.parts
    return any(skip in parts for skip in SKIP_DIRS)

def inject_gtag(file_path):
    """Inject gtag code into an HTML file if not already present."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Skip if already has gtag
        if 'AW-649666163' in content:
            return False, 'already has gtag'

        # Skip if no </head> tag
        if '</head>' not in content:
            return False, 'no </head> tag'

        # Inject before </head>
        new_content = content.replace('</head>', f'{GTAG_CODE}</head>')

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return True, 'injected'
    except Exception as e:
        return False, str(e)

def main():
    injected = 0
    skipped = 0
    errors = 0

    print("Scanning for HTML files...\n")

    for html_file in root_dir.rglob('*.html'):
        if should_skip(html_file):
            continue

        rel_path = html_file.relative_to(root_dir)
        success, message = inject_gtag(html_file)

        if success:
            print(f"✓ {rel_path}")
            injected += 1
        elif message == 'already has gtag':
            skipped += 1
        else:
            print(f"✗ {rel_path}: {message}")
            errors += 1

    print(f"\n{'='*50}")
    print(f"Injected: {injected}")
    print(f"Skipped (already has gtag): {skipped}")
    print(f"Errors: {errors}")
    print(f"Total HTML files processed: {injected + skipped + errors}")

if __name__ == '__main__':
    main()
