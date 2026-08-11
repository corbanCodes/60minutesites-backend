#!/usr/bin/env python3
"""
Generate custom website blog articles.
Run: python3 generate-custom-blogs.py
"""

import os
import json
from datetime import datetime

# Template for blog articles
ARTICLE_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} | 60 Minute Sites</title>
  <meta name="description" content="{meta}">
  <link rel="canonical" href="https://60minutesites.com/blog/custom-websites/{slug}.html">

  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{meta}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="https://60minutesites.com/blog/custom-websites/{slug}.html">

  <link rel="apple-touch-icon" sizes="180x180" href="/favicon_io (4)/apple-touch-icon.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon_io (4)/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon_io (4)/favicon-16x16.png">

  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Article",
    "headline": "{title}",
    "description": "{meta}",
    "url": "https://60minutesites.com/blog/custom-websites/{slug}.html",
    "datePublished": "{date}",
    "dateModified": "{date}",
    "publisher": {{
      "@type": "Organization",
      "name": "60 Minute Sites",
      "url": "https://60minutesites.com"
    }},
    "mainEntityOfPage": {{
      "@type": "WebPage",
      "@id": "https://60minutesites.com/blog/custom-websites/{slug}.html"
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
          <a href="/blog/custom-websites/">Custom Websites</a>
        </div>
        <span class="category-badge">Custom Websites</span>
        <h1>{title}</h1>
        <p class="post-meta">
          <span><i class="fas fa-clock"></i> {read_time} min read</span>
          <span><i class="fas fa-calendar"></i> January 2026</span>
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
        <h4>More Custom Website Resources</h4>
        <div class="hub-links-list">
          <a href="/blog/custom-websites/">Complete Guide</a>
          <a href="/blog/custom-websites/custom-website-cost.html">Cost Guide</a>
          <a href="/blog/custom-websites/custom-website-vs-template.html">Custom vs Template</a>
          <a href="/blog/custom-websites/hiring-web-developer.html">Hiring Developers</a>
        </div>
      </div>

      <!-- CTA Block -->
      <div class="blog-post-cta">
        <h3>Need a Custom Website?</h3>
        <p>Book a free consultation to discuss your custom web development needs.</p>
        <div class="cta-buttons">
          <a href="/book-demo.html" class="btn btn-secondary">Book Free Consultation</a>
          <a href="/checkout.html" class="btn btn-outline-white">View Pricing</a>
        </div>
      </div>

      <!-- Related Posts -->
      <section class="related-posts">
        <h3>Related Articles</h3>
        <div class="related-posts-grid">
{related_html}
        </div>
      </section>

    </div>
  </article>

  <div id="blog-footer"></div>

  <script src="/js/main.js"></script>
  <script src="/blog/js/components.js"></script>
</body>
</html>
'''

def generate_sections_html(sections):
    """Generate HTML for article sections."""
    html = ""
    for heading, content in sections:
        html += f"        <h2>{heading}</h2>\n\n"
        html += f"        <p>{content}</p>\n\n"
    return html

def generate_related_html(articles, current_slug):
    """Generate HTML for related articles."""
    related = [a for a in articles if a['slug'] != current_slug][:3]
    html = ""
    for article in related:
        html += f'''          <a href="/blog/custom-websites/{article['slug']}.html" class="post-card">
            <div class="post-card-content">
              <span class="category-badge">Custom Websites</span>
              <h3>{article['title']}</h3>
              <p>{article['meta'][:100]}...</p>
            </div>
          </a>
'''
    return html

def generate_article(article, all_articles):
    """Generate a single blog article HTML file."""
    sections_html = generate_sections_html(article['sections'])
    related_html = generate_related_html(all_articles, article['slug'])
    
    html = ARTICLE_TEMPLATE.format(
        title=article['title'],
        meta=article['meta'],
        slug=article['slug'],
        date=datetime.now().strftime('%Y-%m-%d'),
        read_time=article['read_time'],
        intro=article['intro'],
        sections_html=sections_html,
        conclusion=article['conclusion'],
        related_html=related_html
    )
    return html

# Load articles from JSON file
script_dir = os.path.dirname(os.path.abspath(__file__))
articles_file = os.path.join(script_dir, 'custom-websites-articles.json')

if os.path.exists(articles_file):
    with open(articles_file, 'r') as f:
        ARTICLES = json.load(f)
    
    # Generate all articles
    output_dir = os.path.join(script_dir, 'custom-websites')
    os.makedirs(output_dir, exist_ok=True)
    
    for article in ARTICLES:
        html = generate_article(article, ARTICLES)
        output_path = os.path.join(output_dir, f"{article['slug']}.html")
        with open(output_path, 'w') as f:
            f.write(html)
        print(f"Created: {article['slug']}.html")
    
    print(f"\nGenerated {len(ARTICLES)} blog articles!")
else:
    print(f"Error: {articles_file} not found. Create the articles JSON file first.")
