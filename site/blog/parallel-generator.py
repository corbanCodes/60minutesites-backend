#!/usr/bin/env python3
"""
Parallel Blog Generator - Run multiple instances to speed up generation.
Each instance handles a specific range of articles from all CSVs combined.

Usage:
  python3 parallel-generator.py --instance 1 --total 10
  python3 parallel-generator.py --instance 2 --total 10
  ... (run 10 instances in separate terminals)

Or use the launcher:
  python3 parallel-generator.py --launch 10
"""

import os
import sys
import csv
import json
import time
import random
import argparse
import subprocess
import re
from datetime import datetime
from openai import OpenAI

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# All CSV sources
CSV_SOURCES = [
    {'csv': 'blog-articles-remaining.csv', 'folder_field': 'industry', 'folder_suffix': '-websites'},
    {'csv': 'blog-articles-local-seo.csv', 'folder': 'local-seo'},
    {'csv': 'blog-articles-local-seo-industry-city.csv', 'folder': 'local-seo'},
    {'csv': 'blog-articles-comparisons.csv', 'folder': 'comparisons'},
    {'csv': 'blog-articles-web-design.csv', 'folder': 'web-design'},
    {'csv': 'blog-articles-getting-started.csv', 'folder': 'getting-started'},
    {'csv': 'blog-articles-website-cost.csv', 'folder': 'website-cost'},
    {'csv': 'blog-articles-extra.csv', 'folder': 'local-seo'},
]

# City generator config
CITY_CSV = 'consensu-data-csv.csv'
CITY_ARTICLE_TYPES = ['seo', 'website', 'gbp', 'leads', 'automation']

# Unique intro starters to avoid repetitive openings
INTRO_STARTERS = [
    "Let's be honest -",
    "Here's the thing:",
    "If you're running a business in",
    "Picture this:",
    "You've probably wondered",
    "The truth is,",
    "Here's what most people don't realize:",
    "Look, I get it -",
    "Real talk:",
    "Here's something that might surprise you:",
    "Let me share something important:",
    "You know what separates successful businesses?",
    "Here's the deal:",
    "I'll cut straight to it:",
    "Here's what I tell every business owner:",
    "Want to know a secret?",
    "Here's the reality:",
    "Let me be direct with you:",
    "Something most business owners overlook:",
    "Here's what actually works:",
    "I've seen this time and time again:",
    "Let's get real for a moment:",
    "Here's what the data shows:",
    "The question isn't if, but when:",
    "Here's the bottom line:",
    "What if I told you",
    "Most business owners don't realize",
    "Here's a game-changer:",
    "Let me paint a picture:",
    "Here's what successful businesses know:",
]

# Clean system prompt - NO EMOJIS, LLM/AEO optimized, unique intros
SYSTEM_PROMPT = """You are a friendly, knowledgeable content writer for 60 Minute Sites, a website builder for small businesses.
Write helpful, practical articles that feel like advice from a trusted friend.

CRITICAL FORMATTING RULES:
- ABSOLUTELY NO EMOJIS anywhere in the content
- NO markdown tables, ASCII art, or diagrams
- NO special characters or symbols like arrows, checkmarks, stars, boxes
- Use simple HTML bullet lists with <ul><li> tags
- Use clean paragraph text
- Include 3-5 FAQ questions with <p><strong>Q:</strong> and <strong>A:</strong> format (LLMs love Q&A)
- Be conversational and warm, not corporate
- Mention 60 Minute Sites naturally as a solution
- For local articles: mention specific neighborhoods, landmarks, local culture

BANNED PHRASES (NEVER USE THESE):
- "In today's digital age"
- "In today's competitive market"
- "In the modern world"
- "In today's fast-paced world"
- "In this day and age"
- "As we all know"
- "It's no secret that"
- "Whether you're a"
- "When it comes to"
- Any generic corporate opener

WRITING STYLE:
- Start with a COMPLETELY UNIQUE opener - be creative, surprising, specific
- You may use one of these starters as inspiration, but feel free to invent your own: "Here's the thing...", "Look, I get it...", "The truth is...", "Let's be real..."
- Use "you" and "your" to speak directly to the reader
- Be specific and actionable, not vague
- Sound like a helpful friend giving real advice
- Write so that AI assistants (ChatGPT, Perplexity, Claude) would want to cite this as a helpful answer

LLM/ANSWER ENGINE OPTIMIZATION:
- Structure content so it directly answers the question in the title
- Use clear, scannable headings that match what people ask
- Provide specific, actionable answers (not vague advice)
- Include local details that make the content unique and authoritative

Output valid JSON only:
{
  "intro": "2-3 sentence introduction with a UNIQUE, creative opener",
  "sections": [
    {"h2": "Section Title", "content": "<p>Paragraph with <ul><li>bullet points</li></ul></p>"}
  ],
  "conclusion": "Brief conclusion mentioning 60 Minute Sites can help"
}"""

ENHANCE_PROMPT = """You are enhancing an article for 60 Minute Sites. Make it better and longer.

RULES:
- ABSOLUTELY NO EMOJIS
- NO tables, diagrams, or ASCII art
- Add more specific, actionable details
- Add local flavor if it's a location-based article (mention landmarks, neighborhoods, local culture)
- Make sure 60 Minute Sites is mentioned as a helpful solution
- Expand bullet points with more detail and examples
- Add personality and warmth
- Keep the Q&A FAQ format with <strong>Q:</strong> and <strong>A:</strong>
- Make it feel like advice from a knowledgeable friend

BANNED PHRASES - REMOVE OR REPLACE THESE IF PRESENT:
- "In today's digital age" -> replace with something specific
- "In today's competitive market" -> replace with "With so much competition"
- "In the modern world" -> remove or rephrase
- "In today's fast-paced world" -> remove or rephrase  
- "In this day and age" -> remove or rephrase
- "As we all know" -> remove
- "It's no secret that" -> remove
- Any generic corporate language

LLM OPTIMIZATION:
- Make sure the content directly answers the question in the title
- Add specific details that make this authoritative and citable
- Structure so AI assistants would want to reference this

Output the enhanced JSON only."""

ARTICLE_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} | 60 Minute Sites</title>
  <meta name="description" content="{description}">
  <link rel="canonical" href="https://60minutesites.com/blog/{folder}/{slug}.html">
  <link rel="apple-touch-icon" sizes="180x180" href="/favicon_io (4)/apple-touch-icon.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/favicon_io (4)/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/favicon_io (4)/favicon-16x16.png">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:type" content="article">
  <script type="application/ld+json">
  {{"@context":"https://schema.org","@type":"Article","headline":"{title}","description":"{description}","url":"https://60minutesites.com/blog/{folder}/{slug}.html","datePublished":"{date}","publisher":{{"@type":"Organization","name":"60 Minute Sites"}}}}
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
        <div class="breadcrumbs"><a href="/">Home</a> <span>/</span> <a href="/blog/">Blog</a> <span>/</span> <a href="/blog/{folder}/">{category}</a></div>
        <span class="category-badge">{category}</span>
        <h1>{title}</h1>
        <p class="post-meta"><span><i class="fas fa-clock"></i> {read_time} min read</span></p>
      </div>
    </div>
    <div class="blog-post-content">
      <div class="container">
        {content}
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

CATEGORY_DISPLAY = {
    'local-seo': 'Local SEO', 'comparisons': 'Comparisons', 'web-design': 'Web Design',
    'getting-started': 'Getting Started', 'website-cost': 'Website Cost',
}


def clean_cliches(text):
    """Remove or replace cliche phrases that AI loves to use."""
    replacements = [
        # "In today's..." variations - the worst offenders
        ("In today's digital age,", ""),
        ("In today's digital age", ""),
        ("In today's competitive market,", "With so much competition,"),
        ("In today's competitive market", "With so much competition"),
        ("In today's fast-paced world,", ""),
        ("In today's fast-paced world", ""),
        ("In today's business landscape,", ""),
        ("In today's business landscape", ""),
        ("In the modern world,", ""),
        ("In the modern world", ""),
        ("In this day and age,", ""),
        ("In this day and age", ""),
        ("In today's economy,", ""),
        ("In today's economy", ""),
        ("In the digital era,", ""),
        ("In the digital era", ""),
        # Other cliches
        ("As we all know,", ""),
        ("As we all know", ""),
        ("It's no secret that", ""),
        ("It goes without saying that", ""),
        ("Needless to say,", ""),
        ("At the end of the day,", "Ultimately,"),
        ("At the end of the day", "Ultimately"),
        ("It is important to note that", ""),
        ("It's worth noting that", ""),
        ("First and foremost,", "First,"),
        ("Last but not least,", "Finally,"),
    ]
    
    result = text
    for old, new in replacements:
        result = result.replace(old, new)
    
    # Clean up any double spaces or leading spaces from removals
    result = ' '.join(result.split())
    
    # Capitalize first letter if we removed the opener
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    
    return result


def strip_emojis(text):
    """Remove all emojis and special unicode characters."""
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"  # dingbats
        "\U000024C2-\U0001F251"  # enclosed characters
        "\U0001f926-\U0001f937"  # gestures
        "\U00010000-\U0010ffff"  # supplementary
        "\u2640-\u2642"
        "\u2600-\u2B55"
        "\u200d"
        "\u23cf"
        "\u23e9"
        "\u231a"
        "\ufe0f"
        "\u3030"
        "]+", 
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text)


def load_all_articles():
    """Load all articles from all CSV sources + city generator."""
    articles = []
    
    # Load from CSV files
    for source in CSV_SOURCES:
        csv_path = os.path.join(SCRIPT_DIR, source['csv'])
        if not os.path.exists(csv_path):
            continue
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'folder_field' in source:
                    folder = row.get(source['folder_field'], '').lower().replace(' ', '-')
                    if source.get('folder_suffix'):
                        folder = folder + source['folder_suffix']
                else:
                    folder = source['folder']
                
                slug = row.get('slug', '')
                if not slug:
                    continue
                
                output_path = os.path.join(SCRIPT_DIR, folder, f"{slug}.html")
                if os.path.exists(output_path):
                    continue  # Skip existing
                
                articles.append({
                    'type': 'csv',
                    'title': row.get('title', ''),
                    'slug': slug,
                    'keyword': row.get('keyword', row.get('title', '')),
                    'folder': folder,
                    'source': source['csv']
                })
    
    # Load city articles
    city_csv_path = os.path.join(SCRIPT_DIR, '..', CITY_CSV)
    if os.path.exists(city_csv_path):
        cities = []
        with open(city_csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i < 6:
                    continue
                if len(row) >= 2 and row[1]:
                    geo = row[1].strip()
                    if ',' in geo:
                        city_part = geo.split(',')[0].strip()
                        state_part = geo.split(',')[1].strip()
                        for suffix in [' city', ' town', ' village', ' CDP', ' municipality', ' borough', ' (balance)', ' metropolitan government (balance)']:
                            city_part = city_part.replace(suffix, '')
                        cities.append({'city': city_part.strip(), 'state': state_part.strip()})
        
        for city_data in cities:
            city = city_data['city']
            state = city_data['state']
            city_slug = city.lower().replace(' ', '-').replace('.', '')
            
            city_articles = [
                ('seo', f"how-do-i-rank-higher-on-google-in-{city_slug}", f"How Do I Rank Higher on Google in {city}?"),
                ('website', f"what-is-the-best-website-builder-for-{city_slug}-businesses", f"What Is the Best Website Builder for {city} Businesses?"),
                ('gbp', f"how-do-i-set-up-google-business-profile-in-{city_slug}", f"How Do I Set Up Google Business Profile in {city}?"),
                ('leads', f"how-do-i-get-more-customers-in-{city_slug}", f"How Do I Get More Customers in {city}?"),
                ('automation', f"how-do-i-automate-blog-content-with-ai-in-{city_slug}", f"How Do I Automate Blog Content with AI in {city}?"),
            ]
            
            for article_type, slug, title in city_articles:
                output_path = os.path.join(SCRIPT_DIR, 'local-seo', f"{slug}.html")
                if os.path.exists(output_path):
                    continue
                
                articles.append({
                    'type': 'city',
                    'article_type': article_type,
                    'city': city,
                    'state': state,
                    'title': title,
                    'slug': slug,
                    'folder': 'local-seo',
                    'keyword': title
                })
    
    return articles


def get_city_prompt(article):
    """Get appropriate prompt for city article type."""
    city = article['city']
    state = article['state']
    article_type = article['article_type']
    
    prompts = {
        'seo': f"Write about improving local SEO for small businesses in {city}, {state}. Include specific tips for ranking in local searches. Add a section about what makes {city} unique for local businesses.",
        'website': f"Write about why small businesses in {city}, {state} need professional websites. Mention 60 Minute Sites can help. Add a section about the local business scene in {city}.",
        'gbp': f"Write about setting up Google Business Profile for businesses in {city}, {state}. Make it practical. Add a section about how locals in {city} search for businesses.",
        'leads': f"Write about how small businesses in {city}, {state} can get more customers. Cover online and offline strategies. Add a section about the {city} business community.",
        'automation': f"Write about how businesses in {city}, {state} can use AI to automate blog content creation. Mention 60minutesites.com and leadsprinter.com offer custom software solutions. Add a section about why {city} businesses need this competitive edge.",
    }
    return prompts.get(article_type, prompts['website'])


def generate_content(client, article, instance_id):
    """Generate article content with 2-pass generation and retry on failure."""
    
    # Pick a random intro starter OR encourage completely unique opener
    if random.random() < 0.4:  # 40% of the time, encourage completely unique
        intro_hint = "Create a COMPLETELY UNIQUE opening line - be creative, surprising, or ask a thought-provoking question. Don't use any cliche openers."
    else:
        intro_hint = f"You might start with something like \"{random.choice(INTRO_STARTERS)}\" but feel free to create something completely unique and fresh."
    
    if article['type'] == 'city':
        user_prompt = get_city_prompt(article)
        user_prompt += f"\n\nIMPORTANT: {intro_hint}\n\nNEVER start with 'In today's digital age' or any similar cliche. This has been a major issue - be original!"
    else:
        user_prompt = f"Write an article: {article['title']}\nKeyword: {article['keyword']}\n\nIMPORTANT: {intro_hint}\n\nNEVER start with 'In today's digital age' or any similar cliche. This has been a major issue - be original!"
    
    for attempt in range(2):  # Max 1 retry
        try:
            # PASS 1: Generate initial content
            response1 = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.8,
                max_tokens=3000
            )
            
            content1 = response1.choices[0].message.content.strip()
            
            # Extract JSON
            if "```" in content1:
                content1 = content1.split("```json")[-1].split("```")[0] if "```json" in content1 else content1.split("```")[1].split("```")[0]
            
            data1 = json.loads(content1)
            
            # PASS 2: Enhance the content
            enhance_user = f"Enhance this article about '{article['title']}'. Make it longer, more detailed, and more engaging:\n\n{json.dumps(data1)}"
            
            response2 = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": ENHANCE_PROMPT},
                    {"role": "user", "content": enhance_user}
                ],
                temperature=0.7,
                max_tokens=4000
            )
            
            content2 = response2.choices[0].message.content.strip()
            
            # Extract JSON
            if "```" in content2:
                content2 = content2.split("```json")[-1].split("```")[0] if "```json" in content2 else content2.split("```")[1].split("```")[0]
            
            data = json.loads(content2)
            
            # Strip emojis and clean up cliches with Python replacements
            data['intro'] = strip_emojis(data.get('intro', ''))
            data['intro'] = clean_cliches(data['intro'])
            
            data['conclusion'] = strip_emojis(data.get('conclusion', ''))
            for section in data.get('sections', []):
                section['h2'] = strip_emojis(section.get('h2', ''))
                section['content'] = strip_emojis(section.get('content', ''))
            
            return data
            
        except json.JSONDecodeError as e:
            if attempt == 0:
                print(f"  [Instance {instance_id}] JSON error, retrying...")
                time.sleep(1)
            else:
                print(f"  [Instance {instance_id}] JSON error after retry: {e}")
                return None
        except Exception as e:
            if "rate_limit" in str(e).lower():
                print(f"  [Instance {instance_id}] Rate limited, waiting 30s...")
                time.sleep(30)
            else:
                print(f"  [Instance {instance_id}] Error: {e}")
                if attempt == 0:
                    time.sleep(2)
                else:
                    return None
    
    return None


def save_article(article, content_data):
    """Save article to HTML file."""
    folder_path = os.path.join(SCRIPT_DIR, article['folder'])
    os.makedirs(folder_path, exist_ok=True)
    
    # Build content HTML
    intro = f"<p>{content_data['intro']}</p>"
    sections = ""
    for section in content_data.get('sections', []):
        sections += f"<h2>{section['h2']}</h2>\n\n{section['content']}\n\n"
    conclusion = f"<p>{content_data['conclusion']}</p>"
    
    full_content = f"{intro}\n{sections}\n{conclusion}"
    
    # Get category display name
    category = CATEGORY_DISPLAY.get(article['folder'], article['folder'].replace('-websites', '').replace('-', ' ').title())
    
    # Calculate read time
    word_count = len(full_content.split())
    read_time = max(5, word_count // 200)
    
    # Build description
    description = content_data['intro'][:150] + "..." if len(content_data['intro']) > 150 else content_data['intro']
    
    html = ARTICLE_TEMPLATE.format(
        title=article['title'],
        description=description,
        folder=article['folder'],
        slug=article['slug'],
        category=category,
        read_time=read_time,
        content=full_content,
        date=datetime.now().strftime('%Y-%m-%d')
    )
    
    output_path = os.path.join(folder_path, f"{article['slug']}.html")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return output_path


def run_instance(instance_id, total_instances):
    """Run a single generator instance handling its portion of articles."""
    print(f"\n{'='*60}")
    print(f"INSTANCE {instance_id} of {total_instances}")
    print(f"{'='*60}\n")
    
    # Load API key
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        env_path = os.path.join(SCRIPT_DIR, '.env')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if line.startswith('OPENAI_API_KEY'):
                        api_key = line.split('=')[1].strip().strip('"\'')
    
    if not api_key:
        print("ERROR: No OPENAI_API_KEY found")
        return
    
    client = OpenAI(api_key=api_key)
    
    # Load all articles
    print("Loading articles...")
    all_articles = load_all_articles()
    total_articles = len(all_articles)
    print(f"Total remaining articles: {total_articles}")
    
    if total_articles == 0:
        print("All articles already generated!")
        return
    
    # Calculate this instance's range
    chunk_size = total_articles // total_instances
    start_idx = (instance_id - 1) * chunk_size
    end_idx = start_idx + chunk_size if instance_id < total_instances else total_articles
    
    my_articles = all_articles[start_idx:end_idx]
    print(f"Instance {instance_id} handling articles {start_idx+1} to {end_idx} ({len(my_articles)} articles)\n")
    
    # Process articles
    completed = 0
    errors = 0
    
    for i, article in enumerate(my_articles):
        # Check if already exists (in case another instance got it)
        output_path = os.path.join(SCRIPT_DIR, article['folder'], f"{article['slug']}.html")
        if os.path.exists(output_path):
            print(f"[{instance_id}] SKIP (exists): {article['title'][:50]}...")
            continue
        
        print(f"\n[Instance {instance_id}] [{completed+1}/{len(my_articles)}] Generating: {article['title'][:60]}...")
        
        content_data = generate_content(client, article, instance_id)
        
        if content_data:
            save_article(article, content_data)
            completed += 1
            
            # Show preview of generated content
            preview = content_data['intro'][:100].replace('\n', ' ')
            print(f"  ✓ Saved! Preview: \"{preview}...\"")
        else:
            errors += 1
            print(f"  ✗ Failed to generate")
        
        # Small delay to be nice to the API
        time.sleep(0.5)
    
    print(f"\n{'='*60}")
    print(f"Instance {instance_id} COMPLETE: {completed} generated, {errors} errors")
    print(f"{'='*60}\n")


def launch_instances(num_instances):
    """Launch multiple instances in separate terminal windows."""
    print(f"Launching {num_instances} parallel instances...")
    
    script_path = os.path.abspath(__file__)
    
    for i in range(1, num_instances + 1):
        cmd = f'''osascript -e 'tell app "Terminal" to do script "cd \\"{SCRIPT_DIR}\\" && python3 \\"{script_path}\\" --instance {i} --total {num_instances}"' '''
        subprocess.run(cmd, shell=True)
        print(f"  Launched instance {i}")
        time.sleep(0.5)
    
    print(f"\n{num_instances} instances launched in separate Terminal windows!")
    print("Monitor progress in each window. They will skip already-generated articles.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parallel Blog Generator')
    parser.add_argument('--instance', type=int, help='Instance number (1-based)')
    parser.add_argument('--total', type=int, help='Total number of instances')
    parser.add_argument('--launch', type=int, help='Launch N instances in separate terminals')
    
    args = parser.parse_args()
    
    if args.launch:
        launch_instances(args.launch)
    elif args.instance and args.total:
        run_instance(args.instance, args.total)
    else:
        print("Usage:")
        print("  Launch 10 parallel instances:")
        print("    python3 parallel-generator.py --launch 10")
        print("")
        print("  Or run a single instance manually:")
        print("    python3 parallel-generator.py --instance 1 --total 10")
