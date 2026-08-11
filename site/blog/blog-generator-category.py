#!/usr/bin/env python3
"""
Category-specific Blog Generator
Generates articles for a specific category (web-design, local-seo, etc.)

Usage:
  python3 blog-generator-category.py <csv_file> <folder_name> <port>

Example:
  python3 blog-generator-category.py blog-articles-web-design.csv web-design 5051
"""

import os
import sys
import csv
import json
from datetime import datetime

# Check for required packages
try:
    from flask import Flask, render_template_string, request, jsonify
    import openai
except ImportError:
    print("Installing required packages...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "openai"])
    from flask import Flask, render_template_string, request, jsonify
    import openai

# Get arguments
if len(sys.argv) < 4:
    print("Usage: python3 blog-generator-category.py <csv_file> <folder_name> <port>")
    print("Example: python3 blog-generator-category.py blog-articles-web-design.csv web-design 5051")
    sys.exit(1)

CSV_FILE = sys.argv[1]
FOLDER_NAME = sys.argv[2]
PORT = int(sys.argv[3])

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(SCRIPT_DIR, CSV_FILE)

app = Flask(__name__)

# Industry/category display names
CATEGORY_DISPLAY = {
    'web-design': 'Web Design',
    'local-seo': 'Local SEO',
    'comparisons': 'Comparisons',
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

  <link rel="apple-touch-icon" sizes="180x180" href="/favicon_io (4)/apple-touch-icon.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon_io (4)/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon_io (4)/favicon-16x16.png">

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
    }},
    "mainEntityOfPage": {{
      "@type": "WebPage",
      "@id": "https://60minutesites.com/blog/{folder}/{slug}.html"
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

      <!-- CTA Block -->
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
    
    user_prompt = f"""Write a blog article with these specifications:

CATEGORY: {FOLDER_NAME}
TITLE: {article['title']}
TARGET KEYWORD: {article['keyword']}
ARTICLE TYPE: {article['article_type']}
READ TIME: {article['read_time']} minutes

Write helpful, practical content for small business owners.

Include 5-7 sections with H2 headings. Write as much valuable content as possible. Aim for 1000+ words.

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
    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    
    if model == "gpt-4o-mini":
        total_cost += (input_tokens * 0.00015 + output_tokens * 0.0006) / 1000
    elif model == "gpt-4o":
        total_cost += (input_tokens * 0.005 + output_tokens * 0.015) / 1000
    else:
        total_cost += (input_tokens * 0.0005 + output_tokens * 0.0015) / 1000
    
    try:
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        first_pass_data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON response (pass 1): {e}")
    
    # SECOND PASS
    enhance_prompt = f"""Enhance this blog article about "{article['title']}".

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
    input_tokens2 = response2.usage.prompt_tokens
    output_tokens2 = response2.usage.completion_tokens
    
    if model == "gpt-4o-mini":
        total_cost += (input_tokens2 * 0.00015 + output_tokens2 * 0.0006) / 1000
    elif model == "gpt-4o":
        total_cost += (input_tokens2 * 0.005 + output_tokens2 * 0.015) / 1000
    else:
        total_cost += (input_tokens2 * 0.0005 + output_tokens2 * 0.0015) / 1000
    
    try:
        if "```json" in content2:
            content2 = content2.split("```json")[1].split("```")[0]
        elif "```" in content2:
            content2 = content2.split("```")[1].split("```")[0]
        enhanced_data = json.loads(content2)
        return enhanced_data, total_cost
    except json.JSONDecodeError:
        return first_pass_data, total_cost

def create_article_html(article, gpt_data):
    """Create HTML file from GPT response."""
    category_display = CATEGORY_DISPLAY.get(FOLDER_NAME, FOLDER_NAME.replace('-', ' ').title())
    
    sections_html = ""
    for section in gpt_data.get('sections', []):
        h2 = section.get('h2', '')
        content = section.get('content', '')
        paragraphs = content.split('\n\n')
        content_html = '\n\n'.join([f"        <p>{p.strip()}</p>" for p in paragraphs if p.strip()])
        sections_html += f"        <h2>{h2}</h2>\n\n{content_html}\n\n"
    
    intro = gpt_data.get('intro', '')
    meta_description = intro[:155].rsplit(' ', 1)[0] + '...' if len(intro) > 155 else intro
    
    now = datetime.now()
    
    html = ARTICLE_HTML_TEMPLATE.format(
        title=article['title'],
        meta_description=meta_description,
        folder=FOLDER_NAME,
        category_display=category_display,
        slug=article['slug'],
        date=now.strftime('%Y-%m-%d'),
        read_time=article['read_time'],
        intro=intro,
        sections_html=sections_html,
        conclusion=gpt_data.get('conclusion', '')
    )
    
    output_dir = os.path.join(SCRIPT_DIR, FOLDER_NAME)
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, f"{article['slug']}.html")
    with open(output_path, 'w') as f:
        f.write(html)
    
    return output_path

def load_articles():
    """Load articles from CSV."""
    articles = []
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Check if article already exists
                output_path = os.path.join(SCRIPT_DIR, FOLDER_NAME, f"{row['slug']}.html")
                if not os.path.exists(output_path):
                    articles.append(row)
    return articles

# Simple HTML template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>{{ category }} Generator</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, sans-serif; background: #1a1a1a; color: #fff; padding: 2rem; }
        .container { max-width: 800px; margin: 0 auto; }
        h1 { color: #FF6B35; margin-bottom: 1rem; }
        .card { background: #2d2d2d; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; color: #ccc; }
        input, select { width: 100%; padding: 0.75rem; border: 1px solid #3d3d3d; border-radius: 8px; background: #1a1a1a; color: #fff; margin-bottom: 1rem; }
        .btn { padding: 0.875rem 1.5rem; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; }
        .btn-primary { background: #FF6B35; color: #fff; }
        .btn-primary:disabled { background: #666; }
        .log { background: #1a1a1a; border-radius: 8px; padding: 1rem; height: 300px; overflow-y: auto; font-family: monospace; font-size: 0.875rem; }
        .log-entry { padding: 0.25rem 0; border-bottom: 1px solid #2d2d2d; }
        .log-success { color: #10b981; }
        .log-error { color: #ef4444; }
        .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 1rem; }
        .stat { background: #1a1a1a; padding: 1rem; border-radius: 8px; text-align: center; }
        .stat-value { font-size: 1.5rem; font-weight: 700; color: #FF6B35; }
        .stat-label { font-size: 0.75rem; color: #999; }
    </style>
</head>
<body>
    <div class="container">
        <h1>{{ category }} Generator</h1>
        <p style="color: #999; margin-bottom: 1rem;">Port {{ port }} | {{ total }} articles remaining</p>
        
        <div class="stats">
            <div class="stat">
                <div class="stat-value" id="remaining">{{ total }}</div>
                <div class="stat-label">Remaining</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="generated">0</div>
                <div class="stat-label">Generated</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="cost">$0.00</div>
                <div class="stat-label">Cost</div>
            </div>
        </div>
        
        <div class="card">
            <label>OpenAI API Key</label>
            <input type="password" id="api-key" placeholder="sk-..." />
            
            <label>Model</label>
            <select id="model">
                <option value="gpt-4o-mini">GPT-4o Mini (~$0.005/article)</option>
                <option value="gpt-4o">GPT-4o (~$0.08/article)</option>
            </select>
            
            <label>Batch Size</label>
            <select id="batch">
                <option value="5">5 articles</option>
                <option value="10" selected>10 articles</option>
                <option value="25">25 articles</option>
                <option value="all">All remaining</option>
            </select>
            
            <button class="btn btn-primary" id="start-btn" onclick="start()">Start Generation</button>
        </div>
        
        <div class="card">
            <div class="log" id="log"></div>
        </div>
    </div>
    
    <script>
        let running = false;
        
        function log(msg, type='info') {
            const el = document.getElementById('log');
            const entry = document.createElement('div');
            entry.className = 'log-entry log-' + type;
            entry.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
            el.appendChild(entry);
            el.scrollTop = el.scrollHeight;
        }
        
        async function start() {
            const apiKey = document.getElementById('api-key').value;
            if (!apiKey) { log('Enter API key', 'error'); return; }
            
            document.getElementById('start-btn').disabled = true;
            running = true;
            
            const model = document.getElementById('model').value;
            const batch = document.getElementById('batch').value;
            
            log('Starting generation...');
            
            const response = await fetch('/generate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({api_key: apiKey, model: model, batch: batch})
            });
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            while (true) {
                const {value, done} = await reader.read();
                if (done) break;
                
                const lines = decoder.decode(value).split('\\n');
                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const data = JSON.parse(line);
                        if (data.type === 'success') {
                            log('Created: ' + data.slug + '.html', 'success');
                            document.getElementById('generated').textContent = data.count;
                            document.getElementById('cost').textContent = '$' + data.cost.toFixed(2);
                        } else if (data.type === 'error') {
                            log('Error: ' + data.message, 'error');
                        } else if (data.type === 'complete') {
                            log('Complete! Generated ' + data.count + ' articles', 'success');
                        }
                    } catch(e) {}
                }
            }
            
            document.getElementById('start-btn').disabled = false;
            running = false;
        }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    articles = load_articles()
    category_display = CATEGORY_DISPLAY.get(FOLDER_NAME, FOLDER_NAME.replace('-', ' ').title())
    return render_template_string(HTML_TEMPLATE, 
        category=category_display, 
        port=PORT, 
        total=len(articles)
    )

@app.route('/generate', methods=['POST'])
def generate():
    global stop_flag
    stop_flag = False
    
    data = request.json
    api_key = data.get('api_key')
    model = data.get('model', 'gpt-4o-mini')
    batch = data.get('batch', '10')
    
    articles = load_articles()
    
    if batch != 'all':
        articles = articles[:int(batch)]
    
    def generate_stream():
        total_cost = 0
        count = 0
        
        for article in articles:
            if stop_flag:
                break
            
            try:
                gpt_data, cost = generate_article_content(api_key, article, model)
                total_cost += cost
                create_article_html(article, gpt_data)
                count += 1
                
                yield json.dumps({
                    "type": "success",
                    "slug": article['slug'],
                    "count": count,
                    "cost": total_cost
                }) + "\n"
                
            except Exception as e:
                yield json.dumps({"type": "error", "message": str(e)}) + "\n"
        
        yield json.dumps({"type": "complete", "count": count}) + "\n"
        
        # Update articles-data.js
        try:
            import subprocess
            subprocess.run(['python3', 'scan-articles.py'], cwd=SCRIPT_DIR, capture_output=True)
        except:
            pass
    
    return app.response_class(generate_stream(), mimetype='application/json')

if __name__ == '__main__':
    print(f"\n{'='*50}")
    print(f"  {CATEGORY_DISPLAY.get(FOLDER_NAME, FOLDER_NAME)} Generator")
    print(f"{'='*50}")
    print(f"\nCSV: {CSV_FILE}")
    print(f"Folder: {FOLDER_NAME}/")
    print(f"Port: {PORT}")
    
    articles = load_articles()
    print(f"Articles remaining: {len(articles)}")
    print(f"\nOpen: http://localhost:{PORT}")
    print()
    
    app.run(host='0.0.0.0', port=PORT, debug=False)
