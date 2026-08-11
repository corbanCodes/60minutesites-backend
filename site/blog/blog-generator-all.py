#!/usr/bin/env python3
"""
Unified Blog Generator GUI - All Categories
Includes test mode to generate 1 of each category first.

Run: python3 blog-generator-all.py
Open: http://localhost:5050
"""

import os
import sys
import csv
import json
import time
from datetime import datetime

try:
    from flask import Flask, render_template_string, request, jsonify
    import openai
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "openai"])
    from flask import Flask, render_template_string, request, jsonify
    import openai

app = Flask(__name__)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# All categories
CATEGORIES = [
    {'name': 'Industry', 'csv': 'blog-articles-remaining.csv', 'folder_field': 'industry', 'folder_suffix': '-websites'},
    {'name': 'Local SEO (General)', 'csv': 'blog-articles-local-seo.csv', 'folder': 'local-seo'},
    {'name': 'Local SEO (Industry+City)', 'csv': 'blog-articles-local-seo-industry-city.csv', 'folder': 'local-seo'},
    {'name': 'Comparisons', 'csv': 'blog-articles-comparisons.csv', 'folder': 'comparisons'},
    {'name': 'Web Design', 'csv': 'blog-articles-web-design.csv', 'folder': 'web-design'},
    {'name': 'Getting Started', 'csv': 'blog-articles-getting-started.csv', 'folder': 'getting-started'},
    {'name': 'Website Cost', 'csv': 'blog-articles-website-cost.csv', 'folder': 'website-cost'},
    {'name': 'Extra (Voice AI, Software, Leads)', 'csv': 'blog-articles-extra.csv', 'folder': 'local-seo'},
]

CATEGORY_DISPLAY = {
    'local-seo': 'Local SEO', 'comparisons': 'Comparisons', 'web-design': 'Web Design',
    'getting-started': 'Getting Started', 'website-cost': 'Website Cost',
    'construction-websites': 'Construction', 'plumber-websites': 'Plumber',
    'electrician-websites': 'Electrician', 'hvac-websites': 'HVAC',
    'salon-websites': 'Salon', 'spa-websites': 'Spa', 'barber-websites': 'Barber',
    'restaurant-websites': 'Restaurant', 'real-estate-websites': 'Real Estate',
    'fitness-websites': 'Fitness', 'photography-websites': 'Photography',
}

ARTICLE_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} | 60 Minute Sites</title>
  <meta name="description" content="{meta_description}">
  <link rel="canonical" href="https://60minutesites.com/blog/{folder}/{slug}.html">
  <link rel="apple-touch-icon" sizes="180x180" href="/favicon_io (4)/apple-touch-icon.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon_io (4)/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon_io (4)/favicon-16x16.png">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{meta_description}">
  <meta property="og:type" content="article">
  <script type="application/ld+json">
  {{"@context":"https://schema.org","@type":"Article","headline":"{title}","description":"{meta_description}","url":"https://60minutesites.com/blog/{folder}/{slug}.html","datePublished":"{date}","publisher":{{"@type":"Organization","name":"60 Minute Sites"}}}}
  </script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/css/main.css">
  <link rel="stylesheet" href="/blog/css/blog.css">
</head>
<body>
  <div id="blog-header"></div>
  <article class="blog-post">
    <div class="blog-post-header">
      <div class="container">
        <div class="breadcrumbs"><a href="/">Home</a> <span>/</span> <a href="/blog/">Blog</a> <span>/</span> <a href="/blog/{folder}/">{category_display}</a></div>
        <span class="category-badge">{category_display}</span>
        <h1>{title}</h1>
        <p class="post-meta"><span><i class="fas fa-clock"></i> {read_time} min read</span></p>
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
</html>'''

SYSTEM_PROMPT = """You are a professional content writer. Write helpful blog articles for small business owners.
RULES: 1) 1000-1500 words 2) NO emojis 3) NO fake stats 4) Include checklist (✓) or table 5) Output ONLY JSON
FORMAT: {"intro":"...","sections":[{"h2":"...","content":"..."}],"conclusion":"..."}"""

stop_flag = False

def load_all_articles():
    """Load articles from all CSVs."""
    all_articles = []
    category_counts = {}
    
    for cat in CATEGORIES:
        csv_path = os.path.join(SCRIPT_DIR, cat['csv'])
        if not os.path.exists(csv_path):
            continue
        
        count = 0
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'folder' in cat:
                    folder = cat['folder']
                elif 'folder_field' in cat:
                    folder = row[cat['folder_field']] + cat.get('folder_suffix', '')
                else:
                    folder = 'general'
                
                output_path = os.path.join(SCRIPT_DIR, folder, f"{row['slug']}.html")
                if not os.path.exists(output_path):
                    row['_folder'] = folder
                    row['_category'] = cat['name']
                    all_articles.append(row)
                    count += 1
        
        category_counts[cat['name']] = count
    
    return all_articles, category_counts

def generate_content(client, article, retries=2):
    """Two-pass generation with retry on JSON errors."""
    for attempt in range(retries + 1):
        try:
            # Pass 1
            r1 = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Write article: {article['title']}\nKeyword: {article['keyword']}\nOutput JSON only."}
                ],
                temperature=0.7, max_tokens=3000
            )
            c1 = r1.choices[0].message.content.strip()
            cost = (r1.usage.prompt_tokens * 0.00015 + r1.usage.completion_tokens * 0.0006) / 1000
            
            if "```" in c1: c1 = c1.split("```json")[-1].split("```")[0] if "```json" in c1 else c1.split("```")[1].split("```")[0]
            data1 = json.loads(c1)
            break  # Success, exit retry loop
        except json.JSONDecodeError:
            if attempt < retries:
                continue  # Retry
            raise  # Give up after retries
    
    # Pass 2 - enhance
    r2 = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Enhance article. Add checklist/table if missing. Keep content, ADD more. JSON only."},
            {"role": "user", "content": f"Enhance: {json.dumps(data1)}"}
        ],
        temperature=0.7, max_tokens=3500
    )
    c2 = r2.choices[0].message.content.strip()
    cost += (r2.usage.prompt_tokens * 0.00015 + r2.usage.completion_tokens * 0.0006) / 1000
    
    if "```" in c2: c2 = c2.split("```json")[-1].split("```")[0] if "```json" in c2 else c2.split("```")[1].split("```")[0]
    try:
        return json.loads(c2), cost
    except:
        return data1, cost

def create_html(article, data, folder):
    """Create HTML file."""
    cat_display = CATEGORY_DISPLAY.get(folder, folder.replace('-websites', '').replace('-', ' ').title())
    
    sections = ""
    for s in data.get('sections', []):
        paras = '\n\n'.join([f"        <p>{p.strip()}</p>" for p in s.get('content', '').split('\n\n') if p.strip()])
        sections += f"        <h2>{s.get('h2', '')}</h2>\n\n{paras}\n\n"
    
    intro = data.get('intro', '')
    meta = intro[:155].rsplit(' ', 1)[0] + '...' if len(intro) > 155 else intro
    
    html = ARTICLE_TEMPLATE.format(
        title=article['title'], meta_description=meta, folder=folder,
        category_display=cat_display, slug=article['slug'],
        date=datetime.now().strftime('%Y-%m-%d'), read_time=article.get('read_time', '8'),
        intro=intro, sections_html=sections, conclusion=data.get('conclusion', '')
    )
    
    os.makedirs(os.path.join(SCRIPT_DIR, folder), exist_ok=True)
    with open(os.path.join(SCRIPT_DIR, folder, f"{article['slug']}.html"), 'w') as f:
        f.write(html)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>Blog Generator - All Categories</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, sans-serif; background: #1a1a1a; color: #fff; padding: 2rem; }
        .container { max-width: 900px; margin: 0 auto; }
        h1 { color: #FF6B35; margin-bottom: 0.5rem; }
        .subtitle { color: #999; margin-bottom: 2rem; }
        .card { background: #2d2d2d; border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; color: #ccc; font-size: 0.875rem; }
        input { width: 100%; padding: 0.75rem; border: 1px solid #3d3d3d; border-radius: 8px; background: #1a1a1a; color: #fff; margin-bottom: 1rem; }
        .btn { padding: 0.875rem 1.5rem; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; margin-right: 0.5rem; }
        .btn-primary { background: #FF6B35; color: #fff; }
        .btn-secondary { background: #3d3d3d; color: #fff; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin-bottom: 1rem; }
        .stat { background: #1a1a1a; padding: 1rem; border-radius: 8px; text-align: center; }
        .stat-value { font-size: 1.5rem; font-weight: 700; color: #FF6B35; }
        .stat-label { font-size: 0.75rem; color: #999; }
        .log { background: #1a1a1a; border-radius: 8px; padding: 1rem; height: 350px; overflow-y: auto; font-family: monospace; font-size: 0.8rem; }
        .log-entry { padding: 0.25rem 0; border-bottom: 1px solid #2d2d2d; }
        .log-success { color: #10b981; }
        .log-error { color: #ef4444; }
        .categories { display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.5rem; margin-bottom: 1rem; font-size: 0.875rem; }
        .cat-item { background: #1a1a1a; padding: 0.5rem 1rem; border-radius: 6px; }
        .cat-count { color: #FF6B35; font-weight: 600; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Blog Generator - All Categories</h1>
        <p class="subtitle">Generate all blog articles with one click</p>
        
        <div class="stats">
            <div class="stat"><div class="stat-value" id="total">{{ total }}</div><div class="stat-label">Total Remaining</div></div>
            <div class="stat"><div class="stat-value" id="generated">0</div><div class="stat-label">Generated</div></div>
            <div class="stat"><div class="stat-value" id="errors">0</div><div class="stat-label">Errors</div></div>
            <div class="stat"><div class="stat-value" id="cost">$0.00</div><div class="stat-label">Cost</div></div>
        </div>
        
        <div class="card">
            <label>Categories to Generate:</label>
            <div class="categories">
                {% for name, count in categories.items() %}
                <div class="cat-item">{{ name }}: <span class="cat-count">{{ count }}</span></div>
                {% endfor %}
            </div>
            
            <label>OpenAI API Key</label>
            <input type="password" id="api-key" placeholder="sk-..." />
            
            <button class="btn btn-secondary" id="test-btn" onclick="runTest()">🧪 Test (1 of each)</button>
            <button class="btn btn-primary" id="start-btn" onclick="runAll()">🚀 Generate All</button>
            <button class="btn btn-secondary" id="stop-btn" onclick="stop()" disabled>Stop</button>
        </div>
        
        <div class="card">
            <div class="log" id="log"></div>
        </div>
    </div>
    
    <script>
        let running = false;
        let generated = 0;
        let errors = 0;
        let cost = 0;
        
        function log(msg, type='info') {
            const el = document.getElementById('log');
            const entry = document.createElement('div');
            entry.className = 'log-entry log-' + type;
            entry.textContent = '[' + new Date().toLocaleTimeString() + '] ' + msg;
            el.appendChild(entry);
            el.scrollTop = el.scrollHeight;
        }
        
        function updateStats() {
            document.getElementById('generated').textContent = generated;
            document.getElementById('errors').textContent = errors;
            document.getElementById('cost').textContent = '$' + cost.toFixed(2);
        }
        
        async function runGenerator(testMode) {
            const apiKey = document.getElementById('api-key').value;
            if (!apiKey || !apiKey.startsWith('sk-')) {
                log('Please enter a valid API key', 'error');
                return;
            }
            
            running = true;
            document.getElementById('test-btn').disabled = true;
            document.getElementById('start-btn').disabled = true;
            document.getElementById('stop-btn').disabled = false;
            
            generated = 0; errors = 0; cost = 0;
            updateStats();
            
            log(testMode ? 'Starting TEST mode (1 of each category)...' : 'Starting FULL generation...');
            
            try {
                const response = await fetch('/generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({api_key: apiKey, test_mode: testMode})
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
                                generated++;
                                cost = data.cost;
                                updateStats();
                                log('✓ ' + data.slug + '.html (' + data.category + ')', 'success');
                            } else if (data.type === 'error') {
                                errors++;
                                updateStats();
                                log('✗ ' + data.message, 'error');
                            } else if (data.type === 'complete') {
                                log('COMPLETE! ' + data.success + ' articles, $' + data.cost.toFixed(2), 'success');
                            } else if (data.type === 'log') {
                                log(data.message);
                            }
                        } catch(e) {}
                    }
                }
            } catch(e) {
                log('Error: ' + e.message, 'error');
            }
            
            running = false;
            document.getElementById('test-btn').disabled = false;
            document.getElementById('start-btn').disabled = false;
            document.getElementById('stop-btn').disabled = true;
        }
        
        function runTest() { runGenerator(true); }
        function runAll() { runGenerator(false); }
        function stop() { fetch('/stop', {method: 'POST'}); log('Stopping...'); }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    articles, counts = load_all_articles()
    return render_template_string(HTML, total=len(articles), categories=counts)

@app.route('/generate', methods=['POST'])
def generate():
    global stop_flag
    stop_flag = False
    
    data = request.json
    api_key = data.get('api_key')
    test_mode = data.get('test_mode', False)
    
    client = openai.OpenAI(api_key=api_key)
    articles, _ = load_all_articles()
    
    if test_mode:
        # Get 1 from each unique folder
        test_articles = []
        seen = set()
        for a in articles:
            if a['_folder'] not in seen:
                test_articles.append(a)
                seen.add(a['_folder'])
        articles = test_articles
    
    def stream():
        total_cost = 0
        success = 0
        
        yield json.dumps({"type": "log", "message": f"Processing {len(articles)} articles..."}) + "\n"
        
        for i, article in enumerate(articles):
            if stop_flag:
                yield json.dumps({"type": "log", "message": "Stopped by user"}) + "\n"
                break
            
            try:
                gpt_data, cost = generate_content(client, article)
                create_html(article, gpt_data, article['_folder'])
                total_cost += cost
                success += 1
                
                yield json.dumps({
                    "type": "success",
                    "slug": article['slug'],
                    "category": article['_category'],
                    "cost": total_cost
                }) + "\n"
                
                time.sleep(0.3)  # Small delay
                
            except Exception as e:
                yield json.dumps({"type": "error", "message": f"{article['slug']}: {str(e)}"}) + "\n"
        
        yield json.dumps({"type": "complete", "success": success, "cost": total_cost}) + "\n"
        
        # Update articles-data.js
        import subprocess
        subprocess.run(['python3', 'scan-articles.py'], cwd=SCRIPT_DIR, capture_output=True)
    
    return app.response_class(stream(), mimetype='application/json')

@app.route('/stop', methods=['POST'])
def stop():
    global stop_flag
    stop_flag = True
    return jsonify({"status": "stopping"})

if __name__ == '__main__':
    articles, counts = load_all_articles()
    print("\n" + "="*50)
    print("  BLOG GENERATOR - ALL CATEGORIES")
    print("="*50)
    print(f"\nTotal articles to generate: {len(articles)}")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    print(f"\nOpen: http://localhost:5050")
    print("="*50 + "\n")
    
    app.run(host='0.0.0.0', port=5050, debug=False)
