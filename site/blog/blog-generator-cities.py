#!/usr/bin/env python3
"""
City-Focused Blog Generator
Generates 2 articles per city from census data:
1. SEO-focused: "How to Improve SEO for Your Business in [City]"
2. 60MinuteSites-focused: "Best Website Builder for [City] Small Businesses"

Run: python3 blog-generator-cities.py
Open: http://localhost:5051
"""

import os
import sys
import csv
import json
import time
import random
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

# Industries for 60MinuteSites
INDUSTRIES = [
    "plumbers", "electricians", "HVAC contractors", "roofers", "landscapers",
    "painters", "cleaning services", "salons", "spas", "barber shops",
    "restaurants", "fitness studios", "photographers", "real estate agents",
    "dentists", "lawyers", "accountants", "veterinarians", "auto repair shops"
]

# LeadSprinter links - randomly include in ~50 articles
LEADSPRINTER_ARTICLES = set()

ARTICLE_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} | 60 Minute Sites</title>
  <meta name="description" content="{meta_description}">
  <link rel="canonical" href="https://60minutesites.com/blog/local-seo/{slug}.html">
  <link rel="apple-touch-icon" sizes="180x180" href="/favicon_io (4)/apple-touch-icon.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon_io (4)/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon_io (4)/favicon-16x16.png">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{meta_description}">
  <meta property="og:type" content="article">
  <script type="application/ld+json">
  {{"@context":"https://schema.org","@type":"Article","headline":"{title}","description":"{meta_description}","url":"https://60minutesites.com/blog/local-seo/{slug}.html","datePublished":"{date}","publisher":{{"@type":"Organization","name":"60 Minute Sites"}}}}
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
        <div class="breadcrumbs"><a href="/">Home</a> <span>/</span> <a href="/blog/">Blog</a> <span>/</span> <a href="/blog/local-seo/">Local SEO</a></div>
        <span class="category-badge">Local SEO</span>
        <h1>{title}</h1>
        <p class="post-meta"><span><i class="fas fa-clock"></i> {read_time} min read</span></p>
      </div>
    </div>
    <div class="blog-post-content">
      <div class="container">
        <p>{intro}</p>
{sections}
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

# System prompts - NO EMOJIS, clean formatting, WITH PERSONALITY
SEO_SYSTEM_PROMPT = """You are a friendly, down-to-earth local SEO expert who genuinely wants to help small business owners succeed.
Write like you're chatting with a friend who owns a local business - warm, practical, no BS.

CRITICAL RULES:
- NO emojis anywhere
- NO markdown tables
- Use simple bullet lists with dashes (-)
- Include 3-5 FAQ questions with answers (Q: and A: format)
- Mention the specific city naturally throughout - reference local landmarks, neighborhoods, or culture if you can
- Add personality! Use phrases like "Here's the thing...", "Look, I get it...", "The good news is..."
- Be specific and practical, not generic corporate speak
- Acknowledge the challenges small business owners face
- Write like a helpful neighbor, not a textbook
- IMPORTANT: Include a section called "What Makes [City] Special" that talks about the local vibe, culture, what it's like doing business there, local pride, community feel, weather, local events, or anything that makes the city unique. Make it feel like you actually know the place!

Output JSON only:
{
  "intro": "2-3 sentence intro mentioning the city with personality",
  "sections": [
    {"h2": "Section Title", "content": "Paragraph content with bullet lists using dashes"},
    {"h2": "What Makes [City] Special", "content": "A warm paragraph about the local culture, vibe, and what makes doing business there unique"},
    {"h2": "Frequently Asked Questions", "content": "Q: Question?\\nA: Answer.\\n\\nQ: Question?\\nA: Answer."}
  ],
  "conclusion": "Brief conclusion with call to action"
}"""

WEBSITE_SYSTEM_PROMPT = """You are a friendly web design consultant who genuinely cares about helping local businesses succeed online.
Write like you're giving advice to a friend who just asked "Do I really need a website?"

CRITICAL RULES:
- NO emojis anywhere
- NO markdown tables
- Use simple bullet lists with dashes (-)
- Include 3-5 FAQ questions with answers (Q: and A: format)
- Mention the specific city naturally - reference what makes it unique, local culture, neighborhoods
- Reference these industries naturally: plumbers, electricians, HVAC, roofers, landscapers, painters, cleaners, salons, spas, barbers, restaurants, gyms, photographers, real estate agents, dentists, lawyers, accountants, vets, auto repair
- Mention that small agencies often provide better, more personal service than big faceless companies
- Add personality! Be conversational, use "you" and "your" a lot
- Acknowledge that business owners are busy and need simple solutions
- Write like a helpful friend, not a sales pitch
- IMPORTANT: Include a section called "Life and Business in [City]" that captures the local spirit - the community feel, what locals are proud of, the pace of life, local quirks, weather, events, or anything that shows you get what it's like there. Give it some soul!

Output JSON only:
{
  "intro": "2-3 sentence intro about web design for businesses in this city",
  "sections": [
    {"h2": "Section Title", "content": "Paragraph content with bullet lists using dashes"},
    {"h2": "Life and Business in [City]", "content": "A warm, personable paragraph about what makes the city tick and why local businesses matter there"},
    {"h2": "Frequently Asked Questions", "content": "Q: Question?\\nA: Answer.\\n\\nQ: Question?\\nA: Answer."}
  ],
  "conclusion": "Brief conclusion encouraging them to try 60 Minute Sites"
}"""

GBP_SYSTEM_PROMPT = """You are a friendly local marketing expert helping small business owners get found on Google.
Write like you're explaining Google Business Profile to a friend over coffee - simple, practical, encouraging.

CRITICAL RULES:
- NO emojis anywhere
- NO markdown tables
- Use simple bullet lists with dashes (-)
- Include 3-5 FAQ questions with answers (Q: and A: format)
- Mention the specific city naturally - talk about how locals search for businesses there
- Add personality! Use phrases like "Here's the secret...", "Trust me on this one...", "The best part is..."
- Be specific about what makes a great Google Business Profile
- Acknowledge that this stuff can feel overwhelming but it's actually pretty simple
- Write like you're rooting for them to succeed
- IMPORTANT: Include a section called "How [City] Locals Search" that talks about the local search behavior, what people in that area look for, how word-of-mouth and online discovery work together there, and any local flavor about how the community finds and supports local businesses. Make it feel authentic!

Output JSON only:
{
  "intro": "2-3 sentence intro about Google Business Profile for this city",
  "sections": [
    {"h2": "Section Title", "content": "Paragraph content with bullet lists using dashes"},
    {"h2": "How [City] Locals Search", "content": "A personable paragraph about local search behavior and community dynamics"},
    {"h2": "Frequently Asked Questions", "content": "Q: Question?\\nA: Answer.\\n\\nQ: Question?\\nA: Answer."}
  ],
  "conclusion": "Brief encouraging conclusion"
}"""

LEADS_SYSTEM_PROMPT = """You are a friendly business growth consultant who helps local service businesses get more customers.
Write like you're sharing insider tips with a friend who just started their business - real talk, no fluff.

CRITICAL RULES:
- NO emojis anywhere
- NO markdown tables
- Use simple bullet lists with dashes (-)
- Include 3-5 FAQ questions with answers (Q: and A: format)
- Mention the specific city naturally - reference the local market, competition, opportunities
- Add personality! Use phrases like "Here's what actually works...", "I've seen this work time and time again...", "The truth is..."
- Cover multiple channels: website, Google, reviews, referrals, social media, networking
- Mention that a professional website is the foundation of getting customers online
- Acknowledge the hustle of running a local business
- Write like a mentor sharing hard-won wisdom
- IMPORTANT: Include a section called "The [City] Business Scene" that paints a picture of what it's like running a business there - the local economy, competition level, community support for local businesses, networking opportunities, local events, and the general vibe. Make it feel like you've actually spent time there!

Output JSON only:
{
  "intro": "2-3 sentence intro about getting customers in this city",
  "sections": [
    {"h2": "Section Title", "content": "Paragraph content with bullet lists using dashes"},
    {"h2": "The [City] Business Scene", "content": "A vivid paragraph about the local business landscape, community, and opportunities"},
    {"h2": "Frequently Asked Questions", "content": "Q: Question?\\nA: Answer.\\n\\nQ: Question?\\nA: Answer."}
  ],
  "conclusion": "Brief motivating conclusion"
}"""

AUTOMATION_SYSTEM_PROMPT = """You are a tech-savvy business consultant who helps companies leverage AI and automation to scale their content marketing.
Write like you're letting someone in on a secret that's been working incredibly well - excited but practical.

CRITICAL RULES:
- NO emojis anywhere
- NO markdown tables
- Use simple bullet lists with dashes (-)
- Include 3-5 FAQ questions with answers (Q: and A: format)
- Mention the specific city naturally - talk about how local businesses there can compete with bigger companies using smart automation
- Add personality! Use phrases like "Here's the game-changer...", "This is what the big guys don't want you to know...", "Imagine this..."
- Explain how AI can generate SEO-optimized blog content at scale
- Mention that 60minutesites.com and their sister company leadsprinter.com offer custom software development for exactly this kind of automation
- Talk about long-tail keywords, LLM optimization, Q&A format for voice search
- Make it sound achievable, not intimidating
- Write like you're sharing a competitive advantage
- IMPORTANT: Include a section called "Why [City] Businesses Need This Edge" that explains how local businesses in that specific market can use AI content automation to outcompete larger companies and dominate local search. Make it feel like a secret weapon!

Output JSON only:
{
  "intro": "2-3 sentence intro about AI blog automation for businesses in this city",
  "sections": [
    {"h2": "Section Title", "content": "Paragraph content with bullet lists using dashes"},
    {"h2": "Why [City] Businesses Need This Edge", "content": "A compelling paragraph about how local businesses can use this to compete"},
    {"h2": "Frequently Asked Questions", "content": "Q: Question?\\nA: Answer.\\n\\nQ: Question?\\nA: Answer."}
  ],
  "conclusion": "Brief conclusion mentioning 60minutesites.com and leadsprinter.com for custom solutions"
}"""


def load_cities():
    """Load cities from census CSV."""
    cities = []
    csv_path = os.path.join(SCRIPT_DIR, '..', 'consensu-data-csv.csv')
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i < 6:  # Skip header rows
                continue
            if len(row) >= 2 and row[1]:
                # Parse "City city, State" format
                geo = row[1].strip()
                if ',' in geo:
                    city_part = geo.split(',')[0].strip()
                    state_part = geo.split(',')[1].strip()
                    # Remove " city", " town", etc.
                    for suffix in [' city', ' town', ' village', ' CDP', ' municipality', ' borough', ' (balance)', ' metropolitan government (balance)', '/Jefferson County metro government (balance)']:
                        city_part = city_part.replace(suffix, '')
                    cities.append({
                        'city': city_part.strip(),
                        'state': state_part.strip(),
                        'full': f"{city_part.strip()}, {state_part.strip()}"
                    })
    return cities


def generate_articles_list(cities, test_mode=False):
    """Generate list of articles to create."""
    articles = []
    
    if test_mode:
        cities = cities[:5]  # Only first 5 cities for testing
    
    # Randomly select ~50 articles to include LeadSprinter link
    total_articles = len(cities) * 5  # Now 5 articles per city
    leadsprinter_indices = set(random.sample(range(total_articles), min(50, total_articles)))
    
    for i, city_data in enumerate(cities):
        city = city_data['city']
        state = city_data['state']
        city_slug = city.lower().replace(' ', '-').replace('.', '')
        
        # Article 1: SEO focused (Q&A title)
        seo_slug = f"how-do-i-rank-higher-on-google-in-{city_slug}"
        seo_path = os.path.join(SCRIPT_DIR, 'local-seo', f"{seo_slug}.html")
        if not os.path.exists(seo_path):
            articles.append({
                'type': 'seo',
                'city': city,
                'state': state,
                'slug': seo_slug,
                'title': f"How Do I Rank Higher on Google in {city}?",
                'include_leadsprinter': (i * 5) in leadsprinter_indices
            })
        
        # Article 2: Website/60MinuteSites focused (Q&A title)
        web_slug = f"what-is-the-best-website-builder-for-{city_slug}-businesses"
        web_path = os.path.join(SCRIPT_DIR, 'local-seo', f"{web_slug}.html")
        if not os.path.exists(web_path):
            articles.append({
                'type': 'website',
                'city': city,
                'state': state,
                'slug': web_slug,
                'title': f"What Is the Best Website Builder for {city} Businesses?",
                'include_leadsprinter': (i * 5 + 1) in leadsprinter_indices
            })
        
        # Article 3: Google Business Profile focused (Q&A title)
        gbp_slug = f"how-do-i-set-up-google-business-profile-in-{city_slug}"
        gbp_path = os.path.join(SCRIPT_DIR, 'local-seo', f"{gbp_slug}.html")
        if not os.path.exists(gbp_path):
            articles.append({
                'type': 'gbp',
                'city': city,
                'state': state,
                'slug': gbp_slug,
                'title': f"How Do I Set Up Google Business Profile in {city}?",
                'include_leadsprinter': (i * 5 + 2) in leadsprinter_indices
            })
        
        # Article 4: Getting customers/leads focused (Q&A title)
        leads_slug = f"how-do-i-get-more-customers-in-{city_slug}"
        leads_path = os.path.join(SCRIPT_DIR, 'local-seo', f"{leads_slug}.html")
        if not os.path.exists(leads_path):
            articles.append({
                'type': 'leads',
                'city': city,
                'state': state,
                'slug': leads_slug,
                'title': f"How Do I Get More Customers in {city}?",
                'include_leadsprinter': (i * 5 + 3) in leadsprinter_indices
            })
        
        # Article 5: AI Blog Automation / Custom Software (Q&A title)
        auto_slug = f"how-do-i-automate-blog-content-with-ai-in-{city_slug}"
        auto_path = os.path.join(SCRIPT_DIR, 'local-seo', f"{auto_slug}.html")
        if not os.path.exists(auto_path):
            articles.append({
                'type': 'automation',
                'city': city,
                'state': state,
                'slug': auto_slug,
                'title': f"How Do I Automate Blog Content with AI in {city}?",
                'include_leadsprinter': True  # Always include for this type
            })
    
    return articles


def generate_content(client, article, retries=2):
    """Generate article content with retry logic."""
    city = article['city']
    state = article['state']
    extra = ""
    if article.get('include_leadsprinter'):
        extra = "\n\nAlso briefly mention that for lead generation, businesses can check out leadsprinter.com for automated lead finding tools."
    
    if article['type'] == 'seo':
        system_prompt = SEO_SYSTEM_PROMPT
        user_prompt = f"Write an article about improving local SEO for small businesses in {city}, {state}. Include specific tips for ranking in {city} searches.{extra}"
    elif article['type'] == 'website':
        system_prompt = WEBSITE_SYSTEM_PROMPT
        user_prompt = f"Write an article about why small businesses in {city}, {state} need professional websites and how 60 Minute Sites can help them get online quickly.{extra}"
    elif article['type'] == 'gbp':
        system_prompt = GBP_SYSTEM_PROMPT
        user_prompt = f"Write an article about setting up and optimizing Google Business Profile for small businesses in {city}, {state}. Make it practical and encouraging.{extra}"
    elif article['type'] == 'leads':
        system_prompt = LEADS_SYSTEM_PROMPT
        user_prompt = f"Write an article about how small businesses in {city}, {state} can get more customers. Cover online and offline strategies that actually work.{extra}"
    elif article['type'] == 'automation':
        system_prompt = AUTOMATION_SYSTEM_PROMPT
        user_prompt = f"Write an article about how businesses in {city}, {state} can use AI to automatically generate SEO-optimized blog content. Explain how this levels the playing field against bigger competitors. Mention 60minutesites.com and leadsprinter.com as providers of custom software solutions for this."
    else:
        system_prompt = WEBSITE_SYSTEM_PROMPT
        user_prompt = f"Write an article for small businesses in {city}, {state}.{extra}"
    
    for attempt in range(retries + 1):
        try:
            # Pass 1: Generate
            r1 = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7, max_tokens=2500
            )
            c1 = r1.choices[0].message.content.strip()
            cost = (r1.usage.prompt_tokens * 0.00015 + r1.usage.completion_tokens * 0.0006) / 1000
            
            if "```" in c1:
                c1 = c1.split("```json")[-1].split("```")[0] if "```json" in c1 else c1.split("```")[1].split("```")[0]
            data1 = json.loads(c1)
            
            # Pass 2: Enhance
            r2 = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Enhance this article. Add more specific details about the city. Keep Q&A format. NO emojis. NO tables. JSON only."},
                    {"role": "user", "content": f"Enhance for {city}, {state}: {json.dumps(data1)}"}
                ],
                temperature=0.7, max_tokens=3000
            )
            c2 = r2.choices[0].message.content.strip()
            cost += (r2.usage.prompt_tokens * 0.00015 + r2.usage.completion_tokens * 0.0006) / 1000
            
            if "```" in c2:
                c2 = c2.split("```json")[-1].split("```")[0] if "```json" in c2 else c2.split("```")[1].split("```")[0]
            try:
                return json.loads(c2), cost
            except:
                return data1, cost
                
        except json.JSONDecodeError:
            if attempt < retries:
                continue
            raise


def create_html(article, data):
    """Create HTML file."""
    sections = ""
    for s in data.get('sections', []):
        content = s.get('content', '')
        # Convert bullet lists properly
        lines = content.split('\n')
        formatted_lines = []
        for line in lines:
            line = line.strip()
            if line.startswith('- '):
                formatted_lines.append(f"<li>{line[2:]}</li>")
            elif line.startswith('Q: '):
                formatted_lines.append(f"<p><strong>{line}</strong></p>")
            elif line.startswith('A: '):
                formatted_lines.append(f"<p>{line[3:]}</p>")
            elif line:
                formatted_lines.append(f"<p>{line}</p>")
        
        # Wrap consecutive li items in ul
        final_content = []
        in_list = False
        for line in formatted_lines:
            if line.startswith('<li>'):
                if not in_list:
                    final_content.append('<ul>')
                    in_list = True
                final_content.append(line)
            else:
                if in_list:
                    final_content.append('</ul>')
                    in_list = False
                final_content.append(line)
        if in_list:
            final_content.append('</ul>')
        
        sections += f"        <h2>{s.get('h2', '')}</h2>\n\n{''.join(final_content)}\n\n"
    
    intro = data.get('intro', '')
    meta = intro[:155].rsplit(' ', 1)[0] + '...' if len(intro) > 155 else intro
    
    html = ARTICLE_TEMPLATE.format(
        title=article['title'],
        meta_description=meta,
        slug=article['slug'],
        date=datetime.now().strftime('%Y-%m-%d'),
        read_time="9",
        intro=intro,
        sections=sections,
        conclusion=data.get('conclusion', '')
    )
    
    # Ensure local-seo folder exists
    folder_path = os.path.join(SCRIPT_DIR, 'local-seo')
    os.makedirs(folder_path, exist_ok=True)
    
    output_path = os.path.join(folder_path, f"{article['slug']}.html")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return output_path


HTML_TEMPLATE = '''<!DOCTYPE html>
<html>
<head>
    <title>City Blog Generator - 60 Minute Sites</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1a1a1a; color: #fff; min-height: 100vh; padding: 20px; }
        .container { max-width: 900px; margin: 0 auto; }
        h1 { color: #FF6B35; margin-bottom: 10px; font-size: 1.8rem; }
        .subtitle { color: #888; margin-bottom: 30px; }
        .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 30px; }
        .stat { background: #2a2a2a; padding: 20px; border-radius: 8px; text-align: center; }
        .stat-value { font-size: 2rem; font-weight: bold; color: #FF6B35; }
        .stat-label { color: #888; font-size: 0.85rem; }
        .card { background: #2a2a2a; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
        .card h3 { margin-bottom: 15px; color: #fff; }
        input[type="text"] { width: 100%; padding: 12px; border: 1px solid #444; border-radius: 6px; background: #333; color: #fff; font-size: 1rem; margin-bottom: 15px; }
        .btn { padding: 12px 24px; border: none; border-radius: 6px; cursor: pointer; font-size: 1rem; font-weight: 600; margin-right: 10px; }
        .btn-test { background: #444; color: #fff; }
        .btn-test:hover { background: #555; }
        .btn-primary { background: #FF6B35; color: #fff; }
        .btn-primary:hover { background: #e55a2b; }
        .btn-stop { background: #dc3545; color: #fff; }
        .log { background: #111; border-radius: 6px; padding: 15px; height: 400px; overflow-y: auto; font-family: monospace; font-size: 0.85rem; }
        .log-entry { margin-bottom: 5px; }
        .log-success { color: #28a745; }
        .log-error { color: #dc3545; }
        .log-info { color: #888; }
    </style>
</head>
<body>
    <div class="container">
        <h1>City Blog Generator</h1>
        <p class="subtitle">Generate 5 articles per city: SEO + Website + Google Business + Customers + AI Blog Automation</p>
        
        <div class="stats">
            <div class="stat">
                <div class="stat-value" id="totalCities">{{ total_cities }}</div>
                <div class="stat-label">Total Cities</div>
            </div>
            <div class="stat">
                <div class="stat-value" id="totalArticles">{{ total_articles }}</div>
                <div class="stat-label">Articles Remaining</div>
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
            <h3>Configuration</h3>
            <input type="text" id="apiKey" placeholder="OpenAI API Key">
            <div>
                <button class="btn btn-test" onclick="startGeneration(true)">Test (5 Cities = 10 Articles)</button>
                <button class="btn btn-primary" onclick="startGeneration(false)">Generate All (~{{ total_articles }} Articles)</button>
                <button class="btn btn-stop" onclick="stopGeneration()">Stop</button>
            </div>
        </div>
        
        <div class="card">
            <h3>Progress Log</h3>
            <div class="log" id="log"></div>
        </div>
    </div>
    
    <script>
        let isRunning = false;
        let generated = 0;
        let totalCost = 0;
        
        function log(msg, type='info') {
            const log = document.getElementById('log');
            const time = new Date().toLocaleTimeString();
            log.innerHTML = `<div class="log-entry log-${type}">[${time}] ${msg}</div>` + log.innerHTML;
        }
        
        async function startGeneration(testMode) {
            const apiKey = document.getElementById('apiKey').value;
            if (!apiKey) { alert('Enter API key'); return; }
            
            isRunning = true;
            generated = 0;
            totalCost = 0;
            document.getElementById('generated').textContent = '0';
            document.getElementById('cost').textContent = '$0.00';
            
            log(testMode ? 'Starting TEST mode (5 cities)...' : 'Starting FULL generation...', 'info');
            
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
                            totalCost = data.cost;
                            document.getElementById('generated').textContent = generated;
                            document.getElementById('cost').textContent = '$' + totalCost.toFixed(2);
                            log(`✓ ${data.slug}.html (${data.city})`, 'success');
                        } else if (data.type === 'error') {
                            log(`✗ ${data.message}`, 'error');
                        } else if (data.type === 'done') {
                            log(`Complete! Generated ${data.total} articles.`, 'info');
                        }
                    } catch(e) {}
                }
            }
            isRunning = false;
        }
        
        async function stopGeneration() {
            await fetch('/stop', {method: 'POST'});
            log('Stopping...', 'info');
        }
    </script>
</body>
</html>'''

stop_flag = False

@app.route('/')
def index():
    cities = load_cities()
    articles = generate_articles_list(cities)
    return render_template_string(HTML_TEMPLATE, total_cities=len(cities), total_articles=len(articles))

@app.route('/generate', methods=['POST'])
def generate():
    global stop_flag
    stop_flag = False
    
    data = request.json
    api_key = data.get('api_key')
    test_mode = data.get('test_mode', False)
    
    client = openai.OpenAI(api_key=api_key)
    cities = load_cities()
    articles = generate_articles_list(cities, test_mode)
    
    def gen():
        total_cost = 0
        for i, article in enumerate(articles):
            if stop_flag:
                break
            try:
                content, cost = generate_content(client, article)
                create_html(article, content)
                total_cost += cost
                yield json.dumps({"type": "success", "slug": article['slug'], "city": article['city'], "cost": total_cost}) + "\n"
                time.sleep(0.3)
            except Exception as e:
                yield json.dumps({"type": "error", "message": f"{article['slug']}: {str(e)}"}) + "\n"
        
        yield json.dumps({"type": "done", "total": i + 1}) + "\n"
    
    return app.response_class(gen(), mimetype='application/json')

@app.route('/stop', methods=['POST'])
def stop():
    global stop_flag
    stop_flag = True
    return jsonify({"success": True})

if __name__ == '__main__':
    print("\n" + "="*50)
    print("City Blog Generator")
    print("="*50)
    cities = load_cities()
    articles = generate_articles_list(cities)
    print(f"Total cities: {len(cities)}")
    print(f"Articles to generate: {len(articles)}")
    print(f"\nOpen: http://localhost:5051")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5051, debug=False)
