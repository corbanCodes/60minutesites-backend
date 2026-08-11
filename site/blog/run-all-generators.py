#!/usr/bin/env python3
"""
Unified Blog Generator - Runs all category generators
Includes test mode to generate 1 of each category first.

Usage:
  python3 run-all-generators.py <openai-api-key> [--test]

Options:
  --test    Generate only 1 article from each category to verify everything works
"""

import os
import sys
import csv
import json
import threading
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import openai
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openai"])
    import openai

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# All categories to generate
CATEGORIES = [
    {
        'name': 'Industry',
        'csv': 'blog-articles-remaining.csv',
        'folder_field': 'industry',  # folder comes from industry field + "-websites"
        'folder_suffix': '-websites',
    },
    {
        'name': 'Local SEO (General)',
        'csv': 'blog-articles-local-seo.csv',
        'folder': 'local-seo',
    },
    {
        'name': 'Local SEO (Industry+City)',
        'csv': 'blog-articles-local-seo-industry-city.csv',
        'folder': 'local-seo',
    },
    {
        'name': 'Comparisons',
        'csv': 'blog-articles-comparisons.csv',
        'folder': 'comparisons',
    },
    {
        'name': 'Web Design',
        'csv': 'blog-articles-web-design.csv',
        'folder': 'web-design',
    },
    {
        'name': 'Getting Started',
        'csv': 'blog-articles-getting-started.csv',
        'folder': 'getting-started',
    },
    {
        'name': 'Website Cost',
        'csv': 'blog-articles-website-cost.csv',
        'folder': 'website-cost',
    },
]

CATEGORY_DISPLAY = {
    'local-seo': 'Local SEO',
    'comparisons': 'Comparisons',
    'web-design': 'Web Design',
    'getting-started': 'Getting Started',
    'website-cost': 'Website Cost',
}

ARTICLE_HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} | 60 Minute Sites</title>
  <meta name="description" content="{meta_description}">
  <link rel="canonical" href="https://60minutesites.com/blog/{folder}/{slug}.html">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{meta_description}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="https://60minutesites.com/blog/{folder}/{slug}.html">
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Article",
    "headline": "{title}",
    "description": "{meta_description}",
    "url": "https://60minutesites.com/blog/{folder}/{slug}.html",
    "datePublished": "{date}",
    "dateModified": "{date}",
    "publisher": {{
      "@type": "Organization",
      "name": "60 Minute Sites",
      "url": "https://60minutesites.com"
    }}
  }}
  </script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/css/main.css">
  <link rel="stylesheet" href="/blog/css/blog.css">
</head>
<body>
  <div id="blog-header"></div>
  <article class="blog-post">
    <div class="blog-post-header">
      <div class="container">
        <div class="breadcrumbs">
          <a href="/">Home</a> <span>/</span>
          <a href="/blog/">Blog</a> <span>/</span>
          <a href="/blog/{folder}/">{category_display}</a>
        </div>
        <span class="category-badge">{category_display}</span>
        <h1>{title}</h1>
        <p class="post-meta">
          <span><i class="fas fa-clock"></i> {read_time} min read</span>
        </p>
      </div>
    </div>
    <div class="container">
      <div class="blog-post-content">
        <p>{intro}</p>
{sections_html}
        <p>{conclusion}</p>
      </div>
      <div class="blog-post-cta">
        <h3>Ready for Your Professional Website?</h3>
        <p>Get a professional website live in 60 minutes. From $41.67/month.</p>
        <div class="cta-buttons">
          <a href="/templates.html" class="btn btn-secondary">View Templates</a>
          <a href="/checkout.html" class="btn btn-outline-white">Get Started Now</a>
        </div>
      </div>
    </div>
  </article>
  <div id="blog-footer"></div>
  <script src="/js/main.js"></script>
  <script src="/blog/js/components.js"></script>
</body>
</html>
'''

SYSTEM_PROMPT = """You are a professional content writer. Write helpful, practical blog articles for small business owners.

RULES:
1. Write 1000-1500 words - AIM HIGH
2. NO emojis
3. NO fake stories or statistics  
4. Be specific and actionable
5. Include a checklist (use ✓), comparison table, or step-by-step guide
6. Output ONLY valid JSON

OUTPUT FORMAT:
{
  "intro": "Opening paragraph (2-3 sentences)",
  "sections": [{"h2": "Heading", "content": "Content with \\n\\n between paragraphs"}],
  "conclusion": "Closing paragraph with call to action"
}"""

ENHANCE_PROMPT = """Enhance this article. Add a checklist or table if missing. Keep all content, ADD more value. Output JSON only."""

# Stats tracking
stats = {
    'total': 0,
    'success': 0,
    'errors': 0,
    'cost': 0.0,
    'lock': threading.Lock()
}

def log(msg, level='INFO'):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"[{timestamp}] [{level}] {msg}")

def generate_article_content(client, article, model="gpt-4o-mini"):
    """Generate article with two-pass enhancement."""
    # First pass
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Write article:\nTITLE: {article['title']}\nKEYWORD: {article['keyword']}\nTYPE: {article.get('article_type', 'guide')}\n\nOutput JSON only."}
        ],
        temperature=0.7,
        max_tokens=3000
    )
    
    content = response.choices[0].message.content.strip()
    cost = (response.usage.prompt_tokens * 0.00015 + response.usage.completion_tokens * 0.0006) / 1000
    
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    
    first_pass = json.loads(content)
    
    # Second pass - enhance
    response2 = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ENHANCE_PROMPT},
            {"role": "user", "content": f"Enhance:\n{json.dumps(first_pass)}\n\nOutput JSON."}
        ],
        temperature=0.7,
        max_tokens=3500
    )
    
    content2 = response2.choices[0].message.content.strip()
    cost += (response2.usage.prompt_tokens * 0.00015 + response2.usage.completion_tokens * 0.0006) / 1000
    
    if "```json" in content2:
        content2 = content2.split("```json")[1].split("```")[0]
    elif "```" in content2:
        content2 = content2.split("```")[1].split("```")[0]
    
    try:
        enhanced = json.loads(content2)
        return enhanced, cost
    except:
        return first_pass, cost

def create_article_html(article, gpt_data, folder):
    """Create HTML file."""
    category_display = CATEGORY_DISPLAY.get(folder, folder.replace('-websites', '').replace('-', ' ').title())
    
    sections_html = ""
    for section in gpt_data.get('sections', []):
        h2 = section.get('h2', '')
        content = section.get('content', '')
        paragraphs = content.split('\n\n')
        content_html = '\n\n'.join([f"        <p>{p.strip()}</p>" for p in paragraphs if p.strip()])
        sections_html += f"        <h2>{h2}</h2>\n\n{content_html}\n\n"
    
    intro = gpt_data.get('intro', '')
    meta_description = intro[:155].rsplit(' ', 1)[0] + '...' if len(intro) > 155 else intro
    
    html = ARTICLE_HTML_TEMPLATE.format(
        title=article['title'],
        meta_description=meta_description,
        folder=folder,
        category_display=category_display,
        slug=article['slug'],
        date=datetime.now().strftime('%Y-%m-%d'),
        read_time=article.get('read_time', '8'),
        intro=intro,
        sections_html=sections_html,
        conclusion=gpt_data.get('conclusion', '')
    )
    
    output_dir = os.path.join(SCRIPT_DIR, folder)
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, f"{article['slug']}.html")
    with open(output_path, 'w') as f:
        f.write(html)
    
    return output_path

def process_article(client, article, folder):
    """Process a single article."""
    try:
        gpt_data, cost = generate_article_content(client, article)
        create_article_html(article, gpt_data, folder)
        
        with stats['lock']:
            stats['success'] += 1
            stats['cost'] += cost
        
        return True, article['slug'], cost
    except Exception as e:
        with stats['lock']:
            stats['errors'] += 1
        return False, article['slug'], str(e)

def load_articles_from_csv(csv_path, category_config):
    """Load articles from CSV, excluding already-generated ones."""
    articles = []
    
    if not os.path.exists(csv_path):
        return articles
    
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Determine folder
            if 'folder' in category_config:
                folder = category_config['folder']
            elif 'folder_field' in category_config:
                folder = row[category_config['folder_field']] + category_config.get('folder_suffix', '')
            else:
                folder = row.get('industry', 'general')
            
            # Check if already exists
            output_path = os.path.join(SCRIPT_DIR, folder, f"{row['slug']}.html")
            if not os.path.exists(output_path):
                row['_folder'] = folder
                articles.append(row)
    
    return articles

def run_generator(api_key, test_mode=False):
    """Run the generator for all categories."""
    client = openai.OpenAI(api_key=api_key)
    
    # Load all articles
    all_articles = []
    for cat in CATEGORIES:
        csv_path = os.path.join(SCRIPT_DIR, cat['csv'])
        articles = load_articles_from_csv(csv_path, cat)
        log(f"{cat['name']}: {len(articles)} articles to generate")
        all_articles.extend(articles)
    
    stats['total'] = len(all_articles)
    log(f"TOTAL: {stats['total']} articles")
    
    if test_mode:
        # Get 1 from each category
        test_articles = []
        seen_folders = set()
        for article in all_articles:
            folder = article['_folder']
            if folder not in seen_folders:
                test_articles.append(article)
                seen_folders.add(folder)
        all_articles = test_articles
        log(f"TEST MODE: Generating {len(all_articles)} articles (1 per category)")
    
    log("Starting generation...")
    log("=" * 60)
    
    for i, article in enumerate(all_articles):
        folder = article['_folder']
        success, slug, result = process_article(client, article, folder)
        
        if success:
            log(f"[{stats['success']}/{len(all_articles)}] ✓ {slug}.html (${stats['cost']:.3f} total)", 'SUCCESS')
        else:
            log(f"[{i+1}/{len(all_articles)}] ✗ {slug}: {result}", 'ERROR')
        
        # Small delay to be nice to API (but not too long)
        if i < len(all_articles) - 1:
            time.sleep(0.5)
    
    log("=" * 60)
    log(f"COMPLETE: {stats['success']} success, {stats['errors']} errors, ${stats['cost']:.2f} total cost")
    
    # Update articles-data.js
    log("Updating articles-data.js...")
    import subprocess
    subprocess.run(['python3', 'scan-articles.py'], cwd=SCRIPT_DIR, capture_output=True)
    log("Done!")

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run-all-generators.py <openai-api-key> [--test]")
        print("")
        print("Options:")
        print("  --test    Generate only 1 article from each category first")
        sys.exit(1)
    
    api_key = sys.argv[1]
    test_mode = '--test' in sys.argv
    
    print("=" * 60)
    print("  UNIFIED BLOG GENERATOR")
    print("=" * 60)
    print("")
    
    run_generator(api_key, test_mode)

if __name__ == '__main__':
    main()
