#!/usr/bin/env python3
"""
Scan all blog article HTML files and generate articles-data.js
This allows the blog index page to dynamically filter articles by industry.

Run: python3 scan-articles.py
"""

import os
import re
import json
import glob
from html.parser import HTMLParser

BLOG_DIR = os.path.dirname(os.path.abspath(__file__))

class ArticleParser(HTMLParser):
    """Parse article HTML to extract title, description, read time."""
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.in_h1 = False
        self.title = ""
        self.h1 = ""
        self.description = ""
        self.read_time = "7"
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == 'title':
            self.in_title = True
        elif tag == 'h1':
            self.in_h1 = True
        elif tag == 'meta' and attrs_dict.get('name') == 'description':
            self.description = attrs_dict.get('content', '')
            
    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        elif tag == 'h1':
            self.in_h1 = False
            
    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif self.in_h1:
            self.h1 += data

def extract_read_time(content):
    """Extract read time from HTML content."""
    match = re.search(r'(\d+)\s*min\s*read', content, re.IGNORECASE)
    if match:
        return match.group(1)
    return "7"

# Category folders to scan (in addition to *-websites)
CATEGORY_FOLDERS = [
    'local-seo', 'comparisons', 'web-design', 'getting-started', 'website-cost',
    'llm-optimization', 'lead-generation', 'blog-automation', 'custom-development',
    'ai-business-tools', 'website-strategy', 'local-marketing', 'industry-ai',
    'technical-seo', 'business-growth', 'qa-local-seo', 'qa-websites', 'qa-ai-business',
    '60minutesites', 'leadsprinter', 'small-business-ai', 'conversion-optimization',
    'online-reviews', 'local-directories', 'email-marketing', 'social-media-local',
    'paid-advertising', 'content-marketing', 'website-features', 'website-security',
    'mobile-optimization', 'analytics-tracking', 'competitor-analysis', 'branding-identity',
    'customer-experience', 'seasonal-marketing', 'industry-websites', 'qa-business-operations',
    'qa-marketing', 'website-mistakes', 'future-trends', 'tools-resources', 'success-stories',
    'advanced-strategies', '60minutesites-industries', 'leadsprinter-industries', 'website-comparisons'
]

def get_industry_from_path(filepath):
    """Extract industry/category from file path."""
    parts = filepath.split(os.sep)
    for part in parts:
        if part.endswith('-websites'):
            return part.replace('-websites', '')
        elif part in CATEGORY_FOLDERS:
            return part
    return 'general'

def scan_articles():
    """Scan all article HTML files and return article data."""
    articles = []
    
    # Find all HTML files in *-websites folders
    pattern = os.path.join(BLOG_DIR, '*-websites', '*.html')
    all_files = glob.glob(pattern)
    
    # Also scan category folders
    for folder in CATEGORY_FOLDERS:
        folder_path = os.path.join(BLOG_DIR, folder, '*.html')
        all_files.extend(glob.glob(folder_path))
    
    for filepath in all_files:
        filename = os.path.basename(filepath)
        
        # Skip index.html (hub pages)
        if filename == 'index.html':
            continue
            
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse HTML
            parser = ArticleParser()
            parser.feed(content)
            
            # Get data
            industry = get_industry_from_path(filepath)
            slug = filename.replace('.html', '')
            title = parser.h1.strip() or parser.title.replace(' | 60 Minute Sites', '').strip()
            description = parser.description[:150] + '...' if len(parser.description) > 150 else parser.description
            read_time = extract_read_time(content)
            
            # Build URL - handle both industry-websites and category folders
            if industry in CATEGORY_FOLDERS:
                url = f"/blog/{industry}/{slug}.html"
            else:
                url = f"/blog/{industry}-websites/{slug}.html"
            
            articles.append({
                'industry': industry,
                'slug': slug,
                'title': title,
                'description': description,
                'readTime': read_time,
                'url': url
            })
            
        except Exception as e:
            print(f"Error parsing {filepath}: {e}")
    
    return articles

def generate_js(articles):
    """Generate the articles-data.js file."""
    
    # Group by industry for stats
    industries = {}
    for article in articles:
        ind = article['industry']
        if ind not in industries:
            industries[ind] = 0
        industries[ind] += 1
    
    # Sort articles by industry then title
    articles.sort(key=lambda x: (x['industry'], x['title']))
    
    js_content = '''/**
 * Blog Articles Data
 * Auto-generated from existing HTML files by scan-articles.py
 * Last updated: ''' + __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M') + '''
 * Total articles: ''' + str(len(articles)) + '''
 */

const BLOG_ARTICLES = ''' + json.dumps(articles, indent=2) + ''';

// Industry display names
const INDUSTRY_NAMES = {
  'construction': 'Construction',
  'plumber': 'Plumber',
  'electrician': 'Electrician',
  'hvac': 'HVAC',
  'cleaning': 'Cleaning',
  'salon': 'Salon',
  'spa': 'Spa',
  'barber': 'Barber',
  'massage': 'Massage',
  'fitness': 'Fitness',
  'restaurant': 'Restaurant',
  'real-estate': 'Real Estate',
  'photography': 'Photography',
  'automotive': 'Automotive',
  'pest-control': 'Pest Control',
  'insurance': 'Insurance',
  'mortgage': 'Mortgage',
  'architect': 'Architect',
  'interior-design': 'Interior Design',
  'event': 'Event Planning',
  'music': 'Music',
  'health-beauty': 'Health & Beauty',
  'business-services': 'Business Services',
  'custom': 'Custom Websites',
  'small-business': 'Small Business',
  'auto-shop': 'Auto Shop',
  'gym': 'Fitness'
};

// Get display name for industry
function getIndustryName(industry) {
  return INDUSTRY_NAMES[industry] || industry.replace(/-/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase());
}

// Get articles by industry
function getArticlesByIndustry(industry) {
  if (!industry || industry === 'all') {
    return BLOG_ARTICLES;
  }
  return BLOG_ARTICLES.filter(a => a.industry === industry);
}

// Get unique industries
function getIndustries() {
  const industries = [...new Set(BLOG_ARTICLES.map(a => a.industry))];
  return industries.sort();
}

// Get industry counts
function getIndustryCounts() {
  const counts = {};
  BLOG_ARTICLES.forEach(a => {
    counts[a.industry] = (counts[a.industry] || 0) + 1;
  });
  return counts;
}
'''
    
    output_path = os.path.join(BLOG_DIR, 'js', 'articles-data.js')
    with open(output_path, 'w') as f:
        f.write(js_content)
    
    print(f"Generated: {output_path}")
    print(f"Total articles: {len(articles)}")
    print(f"Industries: {len(industries)}")
    for ind, count in sorted(industries.items(), key=lambda x: -x[1]):
        print(f"  {ind}: {count}")

def main():
    print("Scanning blog articles...")
    articles = scan_articles()
    generate_js(articles)
    print("Done!")

if __name__ == '__main__':
    main()
