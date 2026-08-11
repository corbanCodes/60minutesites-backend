#!/usr/bin/env python3
"""
Generate sitemap.xml for all blog articles
Run after article generation is complete.
"""

import os
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://60minutesites.com"

def find_all_html_files():
    """Find all HTML files in blog subdirectories."""
    articles = []
    
    for item in os.listdir(SCRIPT_DIR):
        item_path = os.path.join(SCRIPT_DIR, item)
        if os.path.isdir(item_path) and not item.startswith('.') and item not in ['css', 'js', 'images']:
            for file in os.listdir(item_path):
                if file.endswith('.html'):
                    url = f"{BASE_URL}/blog/{item}/{file}"
                    articles.append(url)
    
    # Also add index pages
    if os.path.exists(os.path.join(SCRIPT_DIR, 'index.html')):
        articles.append(f"{BASE_URL}/blog/")
    
    return articles

def generate_sitemap():
    articles = find_all_html_files()
    today = datetime.now().strftime('%Y-%m-%d')
    
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    # Main pages first (high priority)
    main_pages = [
        ('/', 1.0, 'weekly'),
        ('/pricing.html', 0.9, 'monthly'),
        ('/gallery.html', 0.9, 'weekly'),
        ('/templates.html', 0.9, 'weekly'),
        ('/checkout.html', 0.3, 'monthly'),
        ('/blog/', 0.8, 'daily'),
    ]
    
    for path, priority, freq in main_pages:
        xml += f'  <url>\n'
        xml += f'    <loc>{BASE_URL}{path}</loc>\n'
        xml += f'    <lastmod>{today}</lastmod>\n'
        xml += f'    <changefreq>{freq}</changefreq>\n'
        xml += f'    <priority>{priority}</priority>\n'
        xml += f'  </url>\n'
    
    # Blog articles (lower priority)
    for url in sorted(articles):
        xml += f'  <url>\n'
        xml += f'    <loc>{url}</loc>\n'
        xml += f'    <lastmod>{today}</lastmod>\n'
        xml += f'    <changefreq>monthly</changefreq>\n'
        xml += f'    <priority>0.5</priority>\n'
        xml += f'  </url>\n'
    
    xml += '</urlset>'
    
    # Write to root directory (one level up from blog)
    sitemap_path = os.path.join(SCRIPT_DIR, '..', 'sitemap.xml')
    with open(sitemap_path, 'w') as f:
        f.write(xml)
    
    print(f"Generated sitemap with {len(articles)} URLs")
    print(f"Saved to: {os.path.abspath(sitemap_path)}")

if __name__ == '__main__':
    generate_sitemap()
