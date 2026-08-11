#!/usr/bin/env python3
"""
Process GPT-4o blog article JSON output and generate HTML files.

USAGE:
1. Put your GPT output JSON in a file or paste into the script
2. Run: python3 process-blog-articles.py

INPUT FORMAT (from spreadsheet):
- Column A: industry
- Column B: slug  
- Column C: title
- Column D: keyword
- Column E: read_time
- Column F: article_type
- Column G: gpt_json_output (the JSON from GPT-4o)

Or use the process_single() function for one article at a time.
"""

import os
import json
import csv
from datetime import datetime

# HTML Template for blog articles
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} | 60 Minute Sites</title>
  <meta name="description" content="{meta_description}">
  <link rel="canonical" href="https://60minutesites.com/blog/{industry}-websites/{slug}.html">

  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{meta_description}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="https://60minutesites.com/blog/{industry}-websites/{slug}.html">

  <link rel="apple-touch-icon" sizes="180x180" href="/favicon_io (4)/apple-touch-icon.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon_io (4)/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon_io (4)/favicon-16x16.png">

  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Article",
    "headline": "{title}",
    "description": "{meta_description}",
    "url": "https://60minutesites.com/blog/{industry}-websites/{slug}.html",
    "datePublished": "{date}",
    "dateModified": "{date}",
    "publisher": {{
      "@type": "Organization",
      "name": "60 Minute Sites",
      "url": "https://60minutesites.com"
    }},
    "mainEntityOfPage": {{
      "@type": "WebPage",
      "@id": "https://60minutesites.com/blog/{industry}-websites/{slug}.html"
    }}
  }}
  </script>

  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
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
          <a href="/blog/{industry}-websites/">{industry_display}</a>
        </div>
        <span class="category-badge">{industry_display}</span>
        <h1>{title}</h1>
        <p class="post-meta">
          <span><i class="fas fa-clock"></i> {read_time} min read</span>
          <span><i class="fas fa-calendar"></i> {month_year}</span>
        </p>
      </div>
    </div>

    <div class="container">
      <div class="blog-post-content">

        <p>{intro}</p>

{sections_html}

        <p>{conclusion}</p>

      </div>

      <!-- Hub Link -->
      <div class="hub-links">
        <h4>More {industry_display} Website Resources</h4>
        <div class="hub-links-list">
          <a href="/blog/{industry}-websites/">Complete Guide</a>
          <a href="/blog/{industry}-websites/{industry}-website-checklist.html">Checklist</a>
          <a href="/blog/{industry}-websites/{industry}-website-cost.html">Cost Guide</a>
          <a href="/blog/{industry}-websites/{industry}-website-seo.html">SEO Guide</a>
        </div>
      </div>

      <!-- CTA Block -->
      <div class="blog-post-cta">
        <h3>Ready to Launch Your {industry_display} Website?</h3>
        <p>Get a professional website that includes all these elements. Live in 60 minutes. From $41.67/month.</p>
        <div class="cta-buttons">
          <a href="/landing-pages/{industry}.html" class="btn btn-secondary">View {industry_display} Templates</a>
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

# Industry display names (for proper capitalization)
INDUSTRY_DISPLAY = {
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
}

def generate_sections_html(sections):
    """Convert sections array to HTML."""
    html = ""
    for section in sections:
        h2 = section.get('h2', '')
        content = section.get('content', '')
        
        # Convert \n\n to paragraph breaks
        paragraphs = content.split('\n\n')
        content_html = '\n\n'.join([f"        <p>{p.strip()}</p>" for p in paragraphs if p.strip()])
        
        html += f"        <h2>{h2}</h2>\n\n{content_html}\n\n"
    
    return html

def process_single(industry, slug, title, keyword, read_time, gpt_json):
    """Process a single article and return HTML."""
    
    # Parse GPT JSON output
    if isinstance(gpt_json, str):
        data = json.loads(gpt_json)
    else:
        data = gpt_json
    
    intro = data.get('intro', '')
    sections = data.get('sections', [])
    conclusion = data.get('conclusion', '')
    
    # Generate sections HTML
    sections_html = generate_sections_html(sections)
    
    # Get display name
    industry_key = industry.lower().replace(' ', '-')
    industry_display = INDUSTRY_DISPLAY.get(industry_key, industry.title())
    
    # Generate meta description (first 155 chars of intro)
    meta_description = intro[:155].rsplit(' ', 1)[0] + '...' if len(intro) > 155 else intro
    
    # Current date info
    now = datetime.now()
    date = now.strftime('%Y-%m-%d')
    month_year = now.strftime('%B %Y')
    
    # Fill template
    html = HTML_TEMPLATE.format(
        title=title,
        meta_description=meta_description,
        industry=industry_key,
        industry_display=industry_display,
        slug=slug,
        date=date,
        month_year=month_year,
        read_time=read_time,
        intro=intro,
        sections_html=sections_html,
        conclusion=conclusion
    )
    
    return html

def process_csv(input_csv, output_dir=None):
    """Process a CSV file with GPT outputs and generate HTML files."""
    
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))
    
    with open(input_csv, 'r') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            industry = row['industry']
            slug = row['slug']
            title = row['title']
            keyword = row.get('keyword', '')
            read_time = row.get('read_time', '7')
            gpt_json = row.get('gpt_json_output', '')
            
            if not gpt_json:
                print(f"Skipping {slug} - no GPT output")
                continue
            
            try:
                html = process_single(industry, slug, title, keyword, read_time, gpt_json)
                
                # Create directory if needed
                industry_dir = os.path.join(output_dir, f"{industry}-websites")
                os.makedirs(industry_dir, exist_ok=True)
                
                # Write HTML file
                output_path = os.path.join(industry_dir, f"{slug}.html")
                with open(output_path, 'w') as out:
                    out.write(html)
                
                print(f"Created: {output_path}")
                
            except json.JSONDecodeError as e:
                print(f"JSON error for {slug}: {e}")
            except Exception as e:
                print(f"Error processing {slug}: {e}")

def process_json_file(json_file, output_dir=None):
    """Process a JSON file with multiple articles."""
    
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))
    
    with open(json_file, 'r') as f:
        articles = json.load(f)
    
    for article in articles:
        industry = article['industry']
        slug = article['slug']
        title = article['title']
        read_time = article.get('read_time', '7')
        gpt_output = article.get('gpt_output', {})
        
        try:
            html = process_single(industry, slug, title, '', read_time, gpt_output)
            
            # Create directory if needed
            industry_dir = os.path.join(output_dir, f"{industry}-websites")
            os.makedirs(industry_dir, exist_ok=True)
            
            # Write HTML file
            output_path = os.path.join(industry_dir, f"{slug}.html")
            with open(output_path, 'w') as out:
                out.write(html)
            
            print(f"Created: {output_path}")
            
        except Exception as e:
            print(f"Error processing {slug}: {e}")

# ============================================
# STEP 7: UPDATE HUB PAGES WITH ARTICLE LINKS
# ============================================

def update_hub_page(industry, articles, output_dir=None):
    """
    Update or create a hub index page with links to all articles.
    This is STEP 7 - linking articles back to the hub.
    """
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))
    
    industry_key = industry.lower().replace(' ', '-')
    industry_display = INDUSTRY_DISPLAY.get(industry_key, industry.title())
    hub_dir = os.path.join(output_dir, f"{industry_key}-websites")
    hub_path = os.path.join(hub_dir, "index.html")
    
    # Generate article links HTML
    article_links = ""
    for article in articles:
        article_links += f'''          <a href="/blog/{industry_key}-websites/{article['slug']}.html" class="post-card">
            <div class="post-card-content">
              <span class="category-badge">{industry_display}</span>
              <h3>{article['title']}</h3>
              <div class="post-card-meta">
                <span><i class="fas fa-clock"></i> {article.get('read_time', 7)} min read</span>
              </div>
            </div>
          </a>
'''
    
    # Check if hub page exists
    if os.path.exists(hub_path):
        # Update existing hub page - find the articles section and replace
        with open(hub_path, 'r') as f:
            content = f.read()
        
        # Look for posts-grid section to update
        import re
        pattern = r'(<div class="posts-grid"[^>]*>)(.*?)(</div>\s*</section>)'
        replacement = f'\\1\n{article_links}        \\3'
        
        if re.search(pattern, content, re.DOTALL):
            new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
            with open(hub_path, 'w') as f:
                f.write(new_content)
            print(f"Updated hub page: {hub_path}")
        else:
            print(f"Could not find posts-grid in {hub_path} - manual update needed")
    else:
        # Create new hub page
        create_hub_page(industry, articles, output_dir)

def create_hub_page(industry, articles, output_dir=None):
    """Create a new hub index page for an industry."""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))
    
    industry_key = industry.lower().replace(' ', '-')
    industry_display = INDUSTRY_DISPLAY.get(industry_key, industry.title())
    hub_dir = os.path.join(output_dir, f"{industry_key}-websites")
    os.makedirs(hub_dir, exist_ok=True)
    
    # Generate article links
    article_links = ""
    for article in articles:
        article_links += f'''          <a href="/blog/{industry_key}-websites/{article['slug']}.html" class="post-card">
            <div class="post-card-content">
              <span class="category-badge">{industry_display}</span>
              <h3>{article['title']}</h3>
              <div class="post-card-meta">
                <span><i class="fas fa-clock"></i> {article.get('read_time', 7)} min read</span>
              </div>
            </div>
          </a>
'''
    
    now = datetime.now()
    date = now.strftime('%Y-%m-%d')
    
    hub_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{industry_display} Website Guide | 60 Minute Sites</title>
  <meta name="description" content="Complete guide to {industry_display.lower()} websites. Tips, checklists, and best practices for building an effective {industry_display.lower()} website.">
  <link rel="canonical" href="https://60minutesites.com/blog/{industry_key}-websites/">

  <meta property="og:title" content="{industry_display} Website Guide">
  <meta property="og:description" content="Complete guide to {industry_display.lower()} websites.">
  <meta property="og:type" content="article">
  <meta property="og:url" content="https://60minutesites.com/blog/{industry_key}-websites/">

  <link rel="apple-touch-icon" sizes="180x180" href="/favicon_io (4)/apple-touch-icon.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon_io (4)/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon_io (4)/favicon-16x16.png">

  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Article",
    "headline": "Complete Guide to {industry_display} Websites",
    "description": "Everything you need to know about building an effective {industry_display.lower()} website.",
    "url": "https://60minutesites.com/blog/{industry_key}-websites/",
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
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/css/main.css">
  <link rel="stylesheet" href="/blog/css/blog.css">
</head>
<body>
  <div id="blog-header"></div>

  <!-- Hub Hero -->
  <section class="hub-hero">
    <div class="container">
      <span class="category-badge">{industry_display}</span>
      <h1>Complete Guide to {industry_display} Websites</h1>
      <p>Everything you need to know about building a {industry_display.lower()} website that generates leads and grows your business.</p>
    </div>
  </section>

  <!-- Articles Grid -->
  <section class="blog-posts-section">
    <div class="container">
      <h2>All {industry_display} Website Articles</h2>
      <div class="posts-grid">
{article_links}
      </div>
    </div>
  </section>

  <!-- CTA Section -->
  <section class="cta-section cta-final">
    <div class="container">
      <div class="cta-content">
        <h2>Ready for Your {industry_display} Website?</h2>
        <p>Get a professional website live in 60 minutes. From $41.67/month.</p>
        <div class="hero-buttons">
          <a href="/landing-pages/{industry_key}.html" class="btn btn-secondary btn-lg">View {industry_display} Templates</a>
          <a href="/checkout.html" class="btn btn-outline-white btn-lg">Get Started Now</a>
        </div>
      </div>
    </div>
  </section>

  <div id="blog-footer"></div>

  <script src="/js/main.js"></script>
  <script src="/blog/js/components.js"></script>
</body>
</html>
'''
    
    hub_path = os.path.join(hub_dir, "index.html")
    with open(hub_path, 'w') as f:
        f.write(hub_html)
    print(f"Created hub page: {hub_path}")

def process_and_update_hubs(input_csv, output_dir=None):
    """
    Process CSV, generate articles, AND update hub pages (Steps 1-7).
    """
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Group articles by industry
    articles_by_industry = {}
    
    with open(input_csv, 'r') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            industry = row['industry']
            slug = row['slug']
            title = row['title']
            keyword = row.get('keyword', '')
            read_time = row.get('read_time', '7')
            gpt_json = row.get('gpt_json_output', '')
            
            # Track article info for hub update
            if industry not in articles_by_industry:
                articles_by_industry[industry] = []
            
            articles_by_industry[industry].append({
                'slug': slug,
                'title': title,
                'read_time': read_time
            })
            
            # Generate article HTML if GPT output exists
            if gpt_json:
                try:
                    html = process_single(industry, slug, title, keyword, read_time, gpt_json)
                    
                    industry_key = industry.lower().replace(' ', '-')
                    industry_dir = os.path.join(output_dir, f"{industry_key}-websites")
                    os.makedirs(industry_dir, exist_ok=True)
                    
                    output_path = os.path.join(industry_dir, f"{slug}.html")
                    with open(output_path, 'w') as out:
                        out.write(html)
                    
                    print(f"Created: {output_path}")
                    
                except Exception as e:
                    print(f"Error processing {slug}: {e}")
    
    # STEP 7: Update hub pages for each industry
    print("\n" + "=" * 50)
    print("STEP 7: Updating Hub Pages")
    print("=" * 50)
    
    for industry, articles in articles_by_industry.items():
        update_hub_page(industry, articles, output_dir)
    
    print(f"\nProcessed {sum(len(a) for a in articles_by_industry.values())} articles across {len(articles_by_industry)} industries")

# Example usage
if __name__ == '__main__':
    print("Blog Article Processor")
    print("=" * 50)
    print()
    print("USAGE OPTIONS:")
    print()
    print("1. Process CSV with GPT outputs AND update hubs (RECOMMENDED):")
    print("   python3 process-blog-articles.py --full input.csv")
    print()
    print("2. Process CSV (articles only, no hub update):")
    print("   python3 process-blog-articles.py --csv input.csv")
    print()
    print("3. Process JSON file:")
    print("   python3 process-blog-articles.py --json articles.json")
    print()
    print("4. Update hub pages only (from CSV without GPT output):")
    print("   python3 process-blog-articles.py --hubs input.csv")
    print()
    print("CSV FORMAT:")
    print("industry,slug,title,keyword,read_time,article_type,gpt_json_output")
    print()
    
    # Check for command line args
    import sys
    if len(sys.argv) > 2:
        if sys.argv[1] == '--csv':
            process_csv(sys.argv[2])
        elif sys.argv[1] == '--json':
            process_json_file(sys.argv[2])
        elif sys.argv[1] == '--full':
            process_and_update_hubs(sys.argv[2])
        elif sys.argv[1] == '--hubs':
            # Just update hubs from CSV (no GPT output needed)
            articles_by_industry = {}
            with open(sys.argv[2], 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    industry = row['industry']
                    if industry not in articles_by_industry:
                        articles_by_industry[industry] = []
                    articles_by_industry[industry].append({
                        'slug': row['slug'],
                        'title': row['title'],
                        'read_time': row.get('read_time', '7')
                    })
            for industry, articles in articles_by_industry.items():
                update_hub_page(industry, articles)
