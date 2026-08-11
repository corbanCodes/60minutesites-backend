#!/usr/bin/env python3
"""
Blog Article Generator - GUI App
Generates blog articles using OpenAI API and creates HTML files.

Run: python3 blog-generator-app.py
"""

import os
import sys
import json
import csv
import threading
from datetime import datetime

# Check for required packages
try:
    from flask import Flask, render_template_string, request, jsonify
    import openai
except ImportError:
    print("Installing required packages...")
    os.system(f"{sys.executable} -m pip install flask openai")
    from flask import Flask, render_template_string, request, jsonify
    import openai

app = Flask(__name__)

# ============================================
# CONFIGURATION
# ============================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Use remaining CSV (excludes already-generated articles)
CSV_FILE = os.path.join(SCRIPT_DIR, "blog-articles-remaining.csv")
# Fallback to master if remaining doesn't exist
if not os.path.exists(CSV_FILE):
    CSV_FILE = os.path.join(SCRIPT_DIR, "blog-articles-master.csv")

# Industry display names
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

# ============================================
# HTML TEMPLATE FOR GENERATED ARTICLES
# ============================================

ARTICLE_HTML_TEMPLATE = '''<!DOCTYPE html>
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

# ============================================
# GUI HTML TEMPLATE
# ============================================

GUI_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Blog Article Generator | 60 Minute Sites</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 100%);
            min-height: 100vh;
            color: #fff;
            padding: 2rem;
        }
        .container {
            max-width: 1000px;
            margin: 0 auto;
        }
        h1 {
            font-size: 2rem;
            margin-bottom: 0.5rem;
            color: #FF6B35;
        }
        .subtitle {
            color: #999;
            margin-bottom: 2rem;
        }
        .card {
            background: #2d2d2d;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            border: 1px solid #3d3d3d;
        }
        .card h2 {
            font-size: 1.25rem;
            margin-bottom: 1rem;
            color: #fff;
        }
        label {
            display: block;
            margin-bottom: 0.5rem;
            color: #ccc;
            font-size: 0.875rem;
        }
        input, select {
            width: 100%;
            padding: 0.75rem 1rem;
            border: 1px solid #3d3d3d;
            border-radius: 8px;
            background: #1a1a1a;
            color: #fff;
            font-size: 1rem;
            margin-bottom: 1rem;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #FF6B35;
        }
        .row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
        }
        .btn {
            padding: 0.875rem 1.5rem;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-primary {
            background: #FF6B35;
            color: #fff;
        }
        .btn-primary:hover {
            background: #E55A2B;
        }
        .btn-primary:disabled {
            background: #666;
            cursor: not-allowed;
        }
        .btn-secondary {
            background: #3d3d3d;
            color: #fff;
        }
        .btn-secondary:hover {
            background: #4d4d4d;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        .stat {
            background: #1a1a1a;
            padding: 1rem;
            border-radius: 8px;
            text-align: center;
        }
        .stat-value {
            font-size: 1.5rem;
            font-weight: 700;
            color: #FF6B35;
        }
        .stat-label {
            font-size: 0.75rem;
            color: #999;
            text-transform: uppercase;
        }
        .progress-container {
            background: #1a1a1a;
            border-radius: 8px;
            height: 8px;
            overflow: hidden;
            margin-bottom: 1rem;
        }
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #FF6B35, #FF8C5A);
            width: 0%;
            transition: width 0.3s;
        }
        .log {
            background: #1a1a1a;
            border-radius: 8px;
            padding: 1rem;
            height: 300px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 0.875rem;
            line-height: 1.6;
        }
        .log-entry {
            padding: 0.25rem 0;
            border-bottom: 1px solid #2d2d2d;
        }
        .log-success { color: #4ade80; }
        .log-error { color: #f87171; }
        .log-info { color: #60a5fa; }
        .log-warning { color: #fbbf24; }
        .actions {
            display: flex;
            gap: 1rem;
            margin-top: 1rem;
        }
        .badge {
            display: inline-block;
            padding: 0.25rem 0.75rem;
            background: #FF6B35;
            color: #fff;
            border-radius: 50px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .api-key-input {
            font-family: monospace;
        }
        .warning {
            background: rgba(251, 191, 36, 0.1);
            border: 1px solid #fbbf24;
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1rem;
            color: #fbbf24;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Blog Article Generator</h1>
        <p class="subtitle">Generate SEO-optimized blog articles using OpenAI GPT-4o</p>

        <div class="stats">
            <div class="stat">
                <div class="stat-value" id="total-articles">{{ total_articles }}</div>
                <div class="stat-label">Total Articles</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="industries-count">{{ industries_count }}</div>
                <div class="stat-label">Industries</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="generated-count">0</div>
                <div class="stat-label">Generated</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="cost-estimate">$0.00</div>
                <div class="stat-label">Est. Cost</div>
            </div>
        </div>

        <div class="card">
            <h2>Configuration</h2>
            <div class="warning">
                Your API key is stored locally and never sent anywhere except OpenAI.
            </div>
            <label for="api-key">OpenAI API Key</label>
            <input type="password" id="api-key" class="api-key-input" placeholder="sk-..." />
            
            <div class="row">
                <div>
                    <label for="industry">Industry</label>
                    <select id="industry">
                        <option value="all">All Industries ({{ total_articles }} articles)</option>
                        {% for ind, count in industries %}
                        <option value="{{ ind }}">{{ ind|title }} ({{ count }} articles)</option>
                        {% endfor %}
                    </select>
                </div>
                <div>
                    <label for="batch-size">Batch Size</label>
                    <select id="batch-size">
                        <option value="5">5 articles (test)</option>
                        <option value="10" selected>10 articles</option>
                        <option value="25">25 articles</option>
                        <option value="50">50 articles</option>
                        <option value="100">100 articles</option>
                        <option value="all">All available</option>
                    </select>
                </div>
            </div>
            
            <div class="row">
                <div>
                    <label for="model">Model</label>
                    <select id="model">
                        <option value="gpt-4o-mini">GPT-4o Mini (cheaper, good quality)</option>
                        <option value="gpt-4o">GPT-4o (best quality, more expensive)</option>
                        <option value="gpt-3.5-turbo">GPT-3.5 Turbo (cheapest)</option>
                    </select>
                </div>
                <div>
                    <label for="delay">Delay Between Requests (seconds)</label>
                    <input type="number" id="delay" value="0" min="0" max="10" />
                </div>
            </div>
        </div>

        <div class="card">
            <h2>Progress</h2>
            <div class="progress-container">
                <div class="progress-bar" id="progress-bar"></div>
            </div>
            <div id="progress-text" style="margin-bottom: 1rem; color: #999;">Ready to generate</div>
            
            <div class="log" id="log">
                <div class="log-entry log-info">Welcome! Configure your settings and click "Start Generation"</div>
            </div>
            
            <div class="actions">
                <button class="btn btn-primary" id="start-btn" onclick="startGeneration()">
                    Start Generation
                </button>
                <button class="btn btn-secondary" id="stop-btn" onclick="stopGeneration()" disabled>
                    Stop
                </button>
            </div>
        </div>
    </div>

    <script>
        let isRunning = false;
        let generatedCount = 0;
        let totalCost = 0;
        
        // Industry article counts from server
        const industryCounts = {
            {% for ind, count in industries %}
            '{{ ind }}': {{ count }},
            {% endfor %}
            'all': {{ total_articles }}
        };
        
        // Cost per article by model (with 2 API calls for enhancement)
        const costPerArticle = {
            'gpt-4o-mini': 0.005,    // ~$0.005 per article (2 calls)
            'gpt-4o': 0.08,          // ~$0.08 per article (2 calls)
            'gpt-3.5-turbo': 0.003   // ~$0.003 per article (2 calls)
        };
        
        function updateCostEstimate() {
            const industry = document.getElementById('industry').value;
            const batchSize = document.getElementById('batch-size').value;
            const model = document.getElementById('model').value;
            
            // Get article count
            let articleCount;
            if (batchSize === 'all') {
                articleCount = industryCounts[industry] || industryCounts['all'];
            } else {
                const maxAvailable = industryCounts[industry] || industryCounts['all'];
                articleCount = Math.min(parseInt(batchSize), maxAvailable);
            }
            
            // Calculate estimated cost
            const cost = articleCount * costPerArticle[model];
            document.getElementById('cost-estimate').textContent = `~$${cost.toFixed(2)}`;
            
            // Update batch info
            const maxAvailable = industryCounts[industry] || industryCounts['all'];
            document.getElementById('progress-text').textContent = 
                `Ready: ${articleCount} articles selected (${maxAvailable} available) - Est. $${cost.toFixed(2)}`;
        }
        
        // Add event listeners for dynamic cost update
        document.addEventListener('DOMContentLoaded', function() {
            document.getElementById('industry').addEventListener('change', updateCostEstimate);
            document.getElementById('batch-size').addEventListener('change', updateCostEstimate);
            document.getElementById('model').addEventListener('change', updateCostEstimate);
            updateCostEstimate(); // Initial calculation
        });

        function log(message, type = 'info') {
            const logDiv = document.getElementById('log');
            const entry = document.createElement('div');
            entry.className = `log-entry log-${type}`;
            entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
            logDiv.appendChild(entry);
            logDiv.scrollTop = logDiv.scrollHeight;
        }

        function updateProgress(current, total) {
            const percent = (current / total) * 100;
            document.getElementById('progress-bar').style.width = `${percent}%`;
            document.getElementById('progress-text').textContent = `Processing ${current} of ${total} articles (${percent.toFixed(1)}%)`;
        }

        function updateStats(generated, cost) {
            document.getElementById('generated-count').textContent = generated;
            document.getElementById('cost-estimate').textContent = `$${cost.toFixed(2)}`;
        }

        async function startGeneration() {
            const apiKey = document.getElementById('api-key').value.trim();
            if (!apiKey || !apiKey.startsWith('sk-')) {
                log('Please enter a valid OpenAI API key', 'error');
                return;
            }

            const industry = document.getElementById('industry').value;
            const batchSize = document.getElementById('batch-size').value;
            const model = document.getElementById('model').value;
            const delay = parseInt(document.getElementById('delay').value) || 2;

            isRunning = true;
            document.getElementById('start-btn').disabled = true;
            document.getElementById('stop-btn').disabled = false;

            log(`Starting generation: ${industry}, batch size: ${batchSize}, model: ${model}`, 'info');

            try {
                const response = await fetch('/generate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        api_key: apiKey,
                        industry: industry,
                        batch_size: batchSize,
                        model: model,
                        delay: delay
                    })
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    const text = decoder.decode(value);
                    const lines = text.split('\\n').filter(l => l.trim());
                    
                    for (const line of lines) {
                        try {
                            const data = JSON.parse(line);
                            if (data.type === 'progress') {
                                updateProgress(data.current, data.total);
                                generatedCount = data.current;
                            } else if (data.type === 'success') {
                                log(`Created: ${data.slug}.html`, 'success');
                                totalCost += data.cost || 0;
                                updateStats(generatedCount, totalCost);
                            } else if (data.type === 'error') {
                                log(`Error: ${data.message}`, 'error');
                            } else if (data.type === 'complete') {
                                log(`Generation complete! ${data.count} articles created.`, 'success');
                            } else if (data.type === 'log') {
                                log(data.message, data.level || 'info');
                            }
                        } catch (e) {
                            // Ignore JSON parse errors for partial data
                        }
                    }
                }
            } catch (error) {
                log(`Error: ${error.message}`, 'error');
            }

            isRunning = false;
            document.getElementById('start-btn').disabled = false;
            document.getElementById('stop-btn').disabled = true;
        }

        function stopGeneration() {
            fetch('/stop', { method: 'POST' });
            log('Stopping generation...', 'warning');
            isRunning = false;
            document.getElementById('start-btn').disabled = false;
            document.getElementById('stop-btn').disabled = true;
        }
    </script>
</body>
</html>
'''

# ============================================
# OPENAI GENERATION
# ============================================

SYSTEM_PROMPT = """You are a professional content writer for 60 Minute Sites, a done-for-you website service. You write helpful, practical blog articles about websites for small business owners.

STRICT RULES:
1. Write 1000-1500 words of genuinely helpful content - AIM FOR THE HIGHER END
2. NO emojis anywhere
3. NO fake client stories or testimonials
4. NO lies or made-up statistics
5. NO fluff or filler content
6. Use "you" and "your" to address the reader directly
7. Be specific and actionable, not generic
8. Include at least ONE of: checklist, comparison table, step-by-step guide, or do/don't list
9. Output ONLY valid JSON - no markdown, no explanation
10. If the title mentions a number (e.g., "7 tips", "5 mistakes"), MAKE SURE you include exactly that many items

OUTPUT FORMAT (JSON only):
{
  "intro": "Opening paragraph (2-3 sentences)",
  "sections": [
    {
      "h2": "Section Heading",
      "content": "Section content (2-4 paragraphs, use \\n\\n between paragraphs)"
    }
  ],
  "conclusion": "Closing paragraph with clear next step"
}"""

ENHANCE_PROMPT = """You are enhancing an existing blog article. Your job is to ADD more valuable content.

RULES:
1. Keep ALL existing content - do not remove anything
2. ADD 300-500 more words of valuable content
3. Add ONE of these if not already present:
   - A checklist with checkmark items (use ✓ character)
   - A comparison table in HTML format
   - A numbered step-by-step guide
   - A "Do This / Not That" list
4. Add more specific examples or details to thin sections
5. If the title promises a number (e.g., "7 tips"), verify that number is met - add more if needed
6. NO emojis (except ✓ for checklists)
7. Output ONLY valid JSON

OUTPUT FORMAT:
{
  "intro": "Keep or slightly expand the intro",
  "sections": [
    {
      "h2": "Section Heading",
      "content": "Enhanced section content with more detail"
    }
  ],
  "conclusion": "Keep or slightly expand conclusion"
}"""

stop_flag = False

def generate_article_content(api_key, article, model="gpt-4o-mini"):
    """Call OpenAI API to generate article content with second-pass enhancement."""
    client = openai.OpenAI(api_key=api_key)
    total_cost = 0
    
    # FIRST PASS: Generate initial content
    user_prompt = f"""Write a blog article with these specifications:

INDUSTRY: {article['industry']}
TITLE: {article['title']}
TARGET KEYWORD: {article['keyword']}
ARTICLE TYPE: {article['article_type']}
READ TIME: {article['read_time']} minutes

The article should help {article['industry']} business owners understand {article['keyword']}. 

Include 5-7 sections with H2 headings. Make the content specific to {article['industry']} businesses, not generic advice.

Write as much valuable content as possible. Aim for 1000+ words.

Remember: Output ONLY the JSON object, nothing else."""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,
        max_tokens=3000
    )
    
    content = response.choices[0].message.content.strip()
    
    # Calculate cost for first pass
    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    
    if model == "gpt-4o-mini":
        total_cost += (input_tokens * 0.00015 + output_tokens * 0.0006) / 1000
    elif model == "gpt-4o":
        total_cost += (input_tokens * 0.005 + output_tokens * 0.015) / 1000
    else:
        total_cost += (input_tokens * 0.0005 + output_tokens * 0.0015) / 1000
    
    # Parse first pass JSON
    try:
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        first_pass_data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response (pass 1): {e}")
    
    # SECOND PASS: Enhance the content
    enhance_prompt = f"""Enhance this blog article about "{article['title']}" for {article['industry']} businesses.

CURRENT ARTICLE:
{json.dumps(first_pass_data, indent=2)}

ENHANCE IT:
1. Add more specific details and examples
2. If missing, add a checklist, comparison table, or step-by-step guide
3. If title mentions a number (like "7 tips"), make sure that many items exist
4. Expand thin sections with more practical advice
5. Keep all existing content, just ADD more value

Output the enhanced article as JSON in the same format."""

    response2 = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ENHANCE_PROMPT},
            {"role": "user", "content": enhance_prompt}
        ],
        temperature=0.7,
        max_tokens=3500
    )
    
    content2 = response2.choices[0].message.content.strip()
    
    # Calculate cost for second pass
    input_tokens2 = response2.usage.prompt_tokens
    output_tokens2 = response2.usage.completion_tokens
    
    if model == "gpt-4o-mini":
        total_cost += (input_tokens2 * 0.00015 + output_tokens2 * 0.0006) / 1000
    elif model == "gpt-4o":
        total_cost += (input_tokens2 * 0.005 + output_tokens2 * 0.015) / 1000
    else:
        total_cost += (input_tokens2 * 0.0005 + output_tokens2 * 0.0015) / 1000
    
    # Parse second pass JSON
    try:
        if "```json" in content2:
            content2 = content2.split("```json")[1].split("```")[0]
        elif "```" in content2:
            content2 = content2.split("```")[1].split("```")[0]
        
        enhanced_data = json.loads(content2)
        return enhanced_data, total_cost
    except json.JSONDecodeError:
        # If second pass fails, return first pass
        return first_pass_data, total_cost

def create_article_html(article, gpt_data):
    """Create HTML file from GPT response."""
    industry_key = article['industry'].lower().replace(' ', '-')
    industry_display = INDUSTRY_DISPLAY.get(industry_key, article['industry'].title())
    
    # Generate sections HTML
    sections_html = ""
    for section in gpt_data.get('sections', []):
        h2 = section.get('h2', '')
        content = section.get('content', '')
        paragraphs = content.split('\n\n')
        content_html = '\n\n'.join([f"        <p>{p.strip()}</p>" for p in paragraphs if p.strip()])
        sections_html += f"        <h2>{h2}</h2>\n\n{content_html}\n\n"
    
    # Meta description
    intro = gpt_data.get('intro', '')
    meta_description = intro[:155].rsplit(' ', 1)[0] + '...' if len(intro) > 155 else intro
    
    now = datetime.now()
    
    html = ARTICLE_HTML_TEMPLATE.format(
        title=article['title'],
        meta_description=meta_description,
        industry=industry_key,
        industry_display=industry_display,
        slug=article['slug'],
        date=now.strftime('%Y-%m-%d'),
        month_year=now.strftime('%B %Y'),
        read_time=article['read_time'],
        intro=intro,
        sections_html=sections_html,
        conclusion=gpt_data.get('conclusion', '')
    )
    
    # Save file
    output_dir = os.path.join(SCRIPT_DIR, f"{industry_key}-websites")
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, f"{article['slug']}.html")
    with open(output_path, 'w') as f:
        f.write(html)
    
    return output_path

# ============================================
# FLASK ROUTES
# ============================================

def load_articles():
    """Load articles from CSV."""
    articles = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                articles.append(row)
    return articles

@app.route('/')
def index():
    articles = load_articles()
    
    # Count by industry
    industry_counts = {}
    for article in articles:
        ind = article['industry']
        industry_counts[ind] = industry_counts.get(ind, 0) + 1
    
    industries = sorted(industry_counts.items(), key=lambda x: x[1], reverse=True)
    
    return render_template_string(
        GUI_HTML,
        total_articles=len(articles),
        industries_count=len(industry_counts),
        industries=industries
    )

@app.route('/generate', methods=['POST'])
def generate():
    global stop_flag
    stop_flag = False
    
    data = request.json
    api_key = data.get('api_key')
    industry = data.get('industry', 'all')
    batch_size = data.get('batch_size', '10')
    model = data.get('model', 'gpt-4o-mini')
    delay = data.get('delay', 2)
    
    def generate_stream():
        global stop_flag
        
        articles = load_articles()
        
        # Filter by industry
        if industry != 'all':
            articles = [a for a in articles if a['industry'] == industry]
        
        # Limit batch size
        if batch_size != 'all':
            articles = articles[:int(batch_size)]
        
        total = len(articles)
        yield json.dumps({"type": "log", "message": f"Starting generation of {total} articles", "level": "info"}) + "\n"
        
        for i, article in enumerate(articles):
            if stop_flag:
                yield json.dumps({"type": "log", "message": "Generation stopped by user", "level": "warning"}) + "\n"
                break
            
            try:
                yield json.dumps({"type": "progress", "current": i + 1, "total": total}) + "\n"
                yield json.dumps({"type": "log", "message": f"Generating: {article['title']}", "level": "info"}) + "\n"
                
                # Generate content
                gpt_data, cost = generate_article_content(api_key, article, model)
                
                # Create HTML
                output_path = create_article_html(article, gpt_data)
                
                yield json.dumps({
                    "type": "success",
                    "slug": article['slug'],
                    "cost": cost
                }) + "\n"
                
                # Delay between requests
                if delay > 0 and i < total - 1:
                    import time
                    time.sleep(delay)
                    
            except Exception as e:
                yield json.dumps({"type": "error", "message": f"{article['slug']}: {str(e)}"}) + "\n"
        
        yield json.dumps({"type": "complete", "count": i + 1}) + "\n"
        
        # Regenerate articles-data.js so blog index picks up new articles
        yield json.dumps({"type": "log", "message": "Updating articles data...", "level": "info"}) + "\n"
        try:
            import subprocess
            subprocess.run(['python3', 'scan-articles.py'], cwd=SCRIPT_DIR, capture_output=True)
            yield json.dumps({"type": "log", "message": "Articles data updated!", "level": "success"}) + "\n"
        except Exception as e:
            yield json.dumps({"type": "log", "message": f"Could not update articles data: {e}", "level": "warning"}) + "\n"
    
    return app.response_class(generate_stream(), mimetype='application/json')

@app.route('/stop', methods=['POST'])
def stop():
    global stop_flag
    stop_flag = True
    return jsonify({"status": "stopping"})

# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5050)
    args = parser.parse_args()
    
    print(f"\n{'='*50}")
    print("Blog Article Generator")
    print(f"{'='*50}")
    print(f"\nOpen in browser: http://localhost:{args.port}")
    print(f"\nPress Ctrl+C to stop\n")
    
    app.run(host='0.0.0.0', port=args.port, debug=False, threaded=True)
