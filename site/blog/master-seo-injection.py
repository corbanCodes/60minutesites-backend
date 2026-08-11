#!/usr/bin/env python3
"""
Master SEO Injection Script
Processes all 15k+ blog articles with:
1. Spam phrase cleanup
2. CTA button fix
3. Green industry banner
4. Internal linking
5. Regenerate articles-data.js

Usage:
  python3 master-seo-injection.py --all          # Run everything
  python3 master-seo-injection.py --fix-cta      # Just fix CTA buttons
  python3 master-seo-injection.py --add-banner   # Just add industry banners
  python3 master-seo-injection.py --internal-links   # Add internal links
  python3 master-seo-injection.py --clean-spam   # Clean spam phrases
  python3 master-seo-injection.py --regen-data   # Regenerate articles-data.js
"""

import os
import re
import json
import random
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Industry folder to landing page mapping
INDUSTRY_LANDING_PAGES = {
    'plumber-websites': {'name': 'Plumber', 'url': '/landing-pages/plumber.html', 'icon': 'fa-wrench'},
    'electrician-websites': {'name': 'Electrician', 'url': '/landing-pages/electrician.html', 'icon': 'fa-bolt'},
    'hvac-websites': {'name': 'HVAC', 'url': '/landing-pages/hvac.html', 'icon': 'fa-snowflake'},
    'construction-websites': {'name': 'Construction', 'url': '/landing-pages/construction.html', 'icon': 'fa-hard-hat'},
    'roofing-websites': {'name': 'Roofing', 'url': '/landing-pages/roofing.html', 'icon': 'fa-home'},
    'landscaping-websites': {'name': 'Landscaping', 'url': '/landing-pages/landscaping.html', 'icon': 'fa-leaf'},
    'cleaning-websites': {'name': 'Cleaning', 'url': '/landing-pages/cleaning.html', 'icon': 'fa-broom'},
    'pest-control-websites': {'name': 'Pest Control', 'url': '/landing-pages/pest-control.html', 'icon': 'fa-bug'},
    'salon-websites': {'name': 'Salon', 'url': '/landing-pages/salon.html', 'icon': 'fa-cut'},
    'barber-websites': {'name': 'Barber', 'url': '/landing-pages/barber.html', 'icon': 'fa-cut'},
    'spa-websites': {'name': 'Spa', 'url': '/landing-pages/spa.html', 'icon': 'fa-spa'},
    'massage-websites': {'name': 'Massage', 'url': '/landing-pages/massage.html', 'icon': 'fa-hands'},
    'fitness-websites': {'name': 'Fitness', 'url': '/landing-pages/fitness.html', 'icon': 'fa-dumbbell'},
    'yoga-websites': {'name': 'Yoga', 'url': '/landing-pages/yoga.html', 'icon': 'fa-om'},
    'restaurant-websites': {'name': 'Restaurant', 'url': '/landing-pages/restaurant.html', 'icon': 'fa-utensils'},
    'cafe-websites': {'name': 'Cafe', 'url': '/landing-pages/cafe.html', 'icon': 'fa-coffee'},
    'bakery-websites': {'name': 'Bakery', 'url': '/landing-pages/bakery.html', 'icon': 'fa-bread-slice'},
    'real-estate-websites': {'name': 'Real Estate', 'url': '/landing-pages/real-estate.html', 'icon': 'fa-home'},
    'photography-websites': {'name': 'Photography', 'url': '/landing-pages/photography.html', 'icon': 'fa-camera'},
    'dental-websites': {'name': 'Dental', 'url': '/landing-pages/dental.html', 'icon': 'fa-tooth'},
    'veterinary-websites': {'name': 'Veterinary', 'url': '/landing-pages/veterinary.html', 'icon': 'fa-paw'},
    'legal-websites': {'name': 'Legal', 'url': '/landing-pages/legal.html', 'icon': 'fa-gavel'},
    'accounting-websites': {'name': 'Accounting', 'url': '/landing-pages/accounting.html', 'icon': 'fa-calculator'},
    'insurance-websites': {'name': 'Insurance', 'url': '/landing-pages/insurance.html', 'icon': 'fa-shield-alt'},
    'automotive-websites': {'name': 'Automotive', 'url': '/landing-pages/automotive.html', 'icon': 'fa-car'},
    'architect-websites': {'name': 'Architect', 'url': '/landing-pages/architect.html', 'icon': 'fa-drafting-compass'},
    'flooring-websites': {'name': 'Flooring', 'url': '/landing-pages/flooring.html', 'icon': 'fa-th-large'},
    'painting-websites': {'name': 'Painting', 'url': '/landing-pages/painting.html', 'icon': 'fa-paint-roller'},
    'moving-websites': {'name': 'Moving', 'url': '/landing-pages/moving.html', 'icon': 'fa-truck'},
    'event-websites': {'name': 'Event Planning', 'url': '/landing-pages/event.html', 'icon': 'fa-calendar-alt'},
    'music-websites': {'name': 'Music', 'url': '/landing-pages/music.html', 'icon': 'fa-music'},
    'tutoring-websites': {'name': 'Tutoring', 'url': '/landing-pages/tutoring.html', 'icon': 'fa-graduation-cap'},
    'therapy-websites': {'name': 'Therapy', 'url': '/landing-pages/therapy.html', 'icon': 'fa-brain'},
    'consulting-websites': {'name': 'Consulting', 'url': '/landing-pages/consulting.html', 'icon': 'fa-briefcase'},
    'mortgage-websites': {'name': 'Mortgage', 'url': '/landing-pages/mortgage.html', 'icon': 'fa-home'},
    'health-beauty-websites': {'name': 'Health & Beauty', 'url': '/landing-pages/health-beauty.html', 'icon': 'fa-heart'},
    'interior-design-websites': {'name': 'Interior Design', 'url': '/landing-pages/interior-design.html', 'icon': 'fa-couch'},
    # Non-industry folders get generic treatment
    'llm-optimization': {'name': 'AI & LLM Optimization', 'url': '/blog/llm-optimization/', 'icon': 'fa-robot'},
    'local-seo': {'name': 'Local SEO', 'url': '/blog/local-seo/', 'icon': 'fa-map-marker-alt'},
    'getting-started': {'name': 'Getting Started', 'url': '/blog/getting-started/', 'icon': 'fa-rocket'},
    'comparisons': {'name': 'Comparisons', 'url': '/blog/comparisons/', 'icon': 'fa-balance-scale'},
}

# Spam phrases to clean
SPAM_PHRASES = [
    (r"In today's digital age,?\s*", ""),
    (r"In today's fast-paced digital world,?\s*", ""),
    (r"In the ever-evolving (world|landscape) of,?\s*", ""),
    (r"In the ever-evolving digital landscape,?\s*", ""),
    (r"In an era where,?\s*", ""),
]

# Build article index for internal linking
article_index = defaultdict(list)

def get_all_html_files():
    """Get all blog HTML files."""
    files = []
    for root, dirs, filenames in os.walk(SCRIPT_DIR):
        # Skip non-content directories
        if any(skip in root for skip in ['css', 'js', 'components', '__pycache__']):
            continue
        for f in filenames:
            if f.endswith('.html') and f != 'index.html':
                files.append(os.path.join(root, f))
    return files

def get_folder_from_path(filepath):
    """Extract folder name from filepath."""
    parts = filepath.replace(SCRIPT_DIR, '').strip('/').split('/')
    return parts[0] if len(parts) > 1 else None

def build_article_index(files):
    """Build index of articles by folder for internal linking."""
    global article_index
    article_index = defaultdict(list)

    for filepath in files:
        folder = get_folder_from_path(filepath)
        if folder:
            filename = os.path.basename(filepath)
            slug = filename.replace('.html', '')
            # Extract title from file
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    title_match = re.search(r'<h1>([^<]+)</h1>', content)
                    title = title_match.group(1) if title_match else slug.replace('-', ' ').title()
                    article_index[folder].append({
                        'slug': slug,
                        'title': title,
                        'url': f'/blog/{folder}/{filename}',
                        'filepath': filepath
                    })
            except:
                pass

    return article_index

def clean_spam_phrases(content):
    """Remove generic AI spam phrases from content."""
    for pattern, replacement in SPAM_PHRASES:
        content = re.sub(pattern, replacement, content, flags=re.IGNORECASE)
    return content

def fix_cta_buttons(content):
    """Wrap CTA buttons in proper container for styling."""
    # Check if already fixed
    if 'class="blog-post-cta"' in content:
        return content

    # Find the CTA buttons div and wrap it
    old_cta = '''<div class="cta-buttons">
          <a href="/templates.html" class="btn btn-secondary">View Templates</a>
          <a href="/checkout.html" class="btn btn-outline-white">Get Started Now</a>
        </div>'''

    new_cta = '''<div class="blog-post-cta">
          <div class="cta-buttons">
            <a href="/templates.html" class="btn btn-primary">View Templates</a>
            <a href="/checkout.html" class="btn btn-secondary">Get Started Now</a>
          </div>
        </div>'''

    if old_cta in content:
        content = content.replace(old_cta, new_cta)
    else:
        # Try regex for variations
        pattern = r'<div class="cta-buttons">\s*<a href="/templates\.html"[^>]*>View Templates</a>\s*<a href="/checkout\.html"[^>]*>Get Started Now</a>\s*</div>'
        content = re.sub(pattern, new_cta, content)

    return content

def add_industry_banner(content, folder):
    """Add green banner linking to industry landing page."""
    # Skip if already has banner
    if 'class="industry-banner"' in content:
        return content

    # Get industry info
    industry_info = INDUSTRY_LANDING_PAGES.get(folder)
    if not industry_info:
        return content

    banner_html = f'''<div class="industry-banner" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 0.75rem 1rem; text-align: center; margin-bottom: 1rem; border-radius: 8px;">
    <a href="{industry_info['url']}" style="color: white; text-decoration: none; font-weight: 600;">
      <i class="fas {industry_info['icon']}" style="margin-right: 0.5rem;"></i>
      Get a Professional {industry_info['name']} Website in 60 Minutes →
    </a>
  </div>'''

    # Insert after blog-post-header div closes
    pattern = r'(</div>\s*</div>\s*<div class="blog-post-content">\s*<div class="container">)'
    replacement = r'\1\n        ' + banner_html

    content = re.sub(pattern, replacement, content, count=1)

    return content

def add_internal_links(content, folder, current_slug):
    """Add related articles section with internal links."""
    # Skip if already has related posts
    if 'class="related-posts"' in content or 'Related Articles' in content:
        return content

    # Get articles from same folder
    folder_articles = article_index.get(folder, [])
    if len(folder_articles) < 4:
        return content

    # Pick 3 random related articles (not current one)
    other_articles = [a for a in folder_articles if a['slug'] != current_slug]
    if len(other_articles) < 3:
        return content

    related = random.sample(other_articles, min(3, len(other_articles)))

    related_html = '''
        <div class="related-posts" style="margin-top: 2rem; padding-top: 2rem; border-top: 1px solid #e5e7eb;">
          <h3 style="font-size: 1.25rem; margin-bottom: 1rem;">Related Articles</h3>
          <div style="display: grid; gap: 1rem;">'''

    for article in related:
        related_html += f'''
            <a href="{article['url']}" style="display: block; padding: 1rem; background: #f9fafb; border-radius: 8px; text-decoration: none; color: #111;">
              <strong>{article['title']}</strong>
            </a>'''

    related_html += '''
          </div>
        </div>'''

    # Insert before CTA buttons
    pattern = r'(<div class="cta-buttons">|<div class="blog-post-cta">)'
    content = re.sub(pattern, related_html + r'\n        \1', content, count=1)

    return content

def process_file(filepath, options):
    """Process a single HTML file with all fixes."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        original = content
        folder = get_folder_from_path(filepath)
        slug = os.path.basename(filepath).replace('.html', '')

        if options.get('clean_spam') or options.get('all'):
            content = clean_spam_phrases(content)

        if options.get('fix_cta') or options.get('all'):
            content = fix_cta_buttons(content)

        if options.get('add_banner') or options.get('all'):
            content = add_industry_banner(content, folder)

        if options.get('internal_links') or options.get('all'):
            content = add_internal_links(content, folder, slug)

        if content != original:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return False

def regenerate_articles_data():
    """Regenerate articles-data.js with all articles."""
    print("\nRegenerating articles-data.js...")

    articles = []
    files = get_all_html_files()

    for filepath in files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            folder = get_folder_from_path(filepath)
            filename = os.path.basename(filepath)
            slug = filename.replace('.html', '')

            # Extract title
            title_match = re.search(r'<title>([^|<]+)', content)
            title = title_match.group(1).strip() if title_match else slug.replace('-', ' ').title()

            # Extract description
            desc_match = re.search(r'<meta name="description" content="([^"]+)"', content)
            description = desc_match.group(1)[:150] + '...' if desc_match else ''

            # Extract read time
            time_match = re.search(r'(\d+)\s*min read', content)
            read_time = time_match.group(1) if time_match else '8'

            articles.append({
                'industry': folder.replace('-websites', '') if folder else 'general',
                'slug': slug,
                'title': title,
                'description': description,
                'readTime': read_time,
                'url': f'/blog/{folder}/{filename}'
            })
        except Exception as e:
            print(f"  Error reading {filepath}: {e}")

    # Sort by industry then title
    articles.sort(key=lambda x: (x['industry'], x['title']))

    # Write JS file
    js_content = f'''/**
 * Blog Articles Data
 * Auto-generated by master-seo-injection.py
 * Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
 * Total articles: {len(articles)}
 */

const BLOG_ARTICLES = {json.dumps(articles, indent=2)};
'''

    output_path = os.path.join(SCRIPT_DIR, 'js', 'articles-data.js')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(js_content)

    print(f"  Generated articles-data.js with {len(articles)} articles")
    return len(articles)

def main():
    parser = argparse.ArgumentParser(description='Master SEO Injection Script')
    parser.add_argument('--all', action='store_true', help='Run all fixes')
    parser.add_argument('--fix-cta', action='store_true', help='Fix CTA buttons')
    parser.add_argument('--add-banner', action='store_true', help='Add industry banners')
    parser.add_argument('--internal-links', action='store_true', help='Add internal links')
    parser.add_argument('--clean-spam', action='store_true', help='Clean spam phrases')
    parser.add_argument('--regen-data', action='store_true', help='Regenerate articles-data.js')
    parser.add_argument('--dry-run', action='store_true', help='Preview without changes')

    args = parser.parse_args()

    options = {
        'all': args.all,
        'fix_cta': args.fix_cta,
        'add_banner': args.add_banner,
        'internal_links': args.internal_links,
        'clean_spam': args.clean_spam,
    }

    # If no options specified, show help
    if not any([args.all, args.fix_cta, args.add_banner, args.internal_links, args.clean_spam, args.regen_data]):
        parser.print_help()
        return

    print("=" * 60)
    print("MASTER SEO INJECTION SCRIPT")
    print("=" * 60)

    # Get all files
    print("\nScanning for HTML files...")
    files = get_all_html_files()
    print(f"Found {len(files)} HTML files")

    # Build article index for internal linking
    if args.internal_links or args.all:
        print("\nBuilding article index for internal linking...")
        build_article_index(files)
        total_indexed = sum(len(v) for v in article_index.values())
        print(f"Indexed {total_indexed} articles across {len(article_index)} folders")

    # Process files
    if any([args.all, args.fix_cta, args.add_banner, args.internal_links, args.clean_spam]):
        print("\nProcessing files...")
        modified = 0
        for i, filepath in enumerate(files):
            if args.dry_run:
                print(f"  Would process: {filepath}")
            else:
                if process_file(filepath, options):
                    modified += 1

            if (i + 1) % 1000 == 0:
                print(f"  Processed {i + 1}/{len(files)} files...")

        print(f"\nModified {modified} files")

    # Regenerate articles data
    if args.regen_data or args.all:
        regenerate_articles_data()

    print("\n" + "=" * 60)
    print("COMPLETE")
    print("=" * 60)

if __name__ == '__main__':
    main()
