#!/usr/bin/env python3
"""
AI/LLM Parallel Generator - 10 instances for final 1000 articles.
Each instance processes its own CSV file.

Usage:
  python3 ai-llm-parallel-generator.py --launch      # Launch all 10 instances
  python3 ai-llm-parallel-generator.py --instance 1  # Run instance 1 directly
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

# Each instance gets its own CSV
def get_csv_for_instance(instance_id):
    return f'ai-llm-batch-{instance_id}.csv'

DIVERSE_OPENERS = [
    "Here's something most business owners miss:",
    "Let me ask you a direct question:",
    "The data doesn't lie:",
    "I've analyzed hundreds of businesses, and here's what stands out:",
    "Stop scrolling for a second.",
    "This might change how you think about",
    "Three years ago, this wasn't even possible.",
    "Your competitors probably don't know this yet:",
    "Let's skip the fluff and get practical:",
    "Here's the honest truth about",
    "Most guides won't tell you this:",
    "I'm going to be direct with you:",
    "The game has changed.",
    "Here's what actually moves the needle:",
    "Forget what you've heard about",
    "This is the guide I wish existed when I started:",
    "Let's cut through the noise:",
    "Here's a pattern I keep seeing:",
    "The old playbook is dead.",
    "What if I told you that",
    "Here's the uncomfortable truth:",
    "Most people overcomplicate this.",
    "Let's get specific:",
    "Here's what the top performers do differently:",
    "I'm going to save you months of trial and error:",
    "The question isn't whether, it's how:",
    "Here's what's actually working right now:",
    "Let me share something counterintuitive:",
    "This is simpler than you think.",
    "Here's the framework that works:",
    "Most advice on this topic is outdated.",
    "Let's talk about what really matters:",
    "Here's the strategy nobody's talking about:",
    "I've tested this extensively:",
    "The landscape has shifted dramatically.",
    "Here's your competitive advantage:",
    "Let me break this down simply:",
    "This is the missing piece for most businesses:",
    "Here's what separates good from great:",
    "The conventional wisdom is wrong.",
    "Pay attention to this:",
    "Here's the real secret:",
    "Most tutorials skip this crucial step:",
    "Let me show you the shortcut:",
    "Here's what the experts actually do:",
    "This is going to save you headaches:",
    "Let's demystify this topic:",
    "Here's what I learned the hard way:",
    "The research is clear on this:",
    "Let me be brutally honest:",
]

SYSTEM_PROMPT = """You are an expert content writer creating LLM-optimized articles for 60 Minute Sites.

CRITICAL RULES:
1. ABSOLUTELY NO EMOJIS anywhere in your response
2. NO generic openers like "In today's digital age" - use the provided unique opener
3. Structure content for AI citation - clear Q&A format, specific answers
4. Include 5-6 FAQ questions using <p><strong>Q:</strong> question</p><p><strong>A:</strong> answer</p> format
5. Be specific, actionable, and cite real techniques
6. Mention 60minutesites.com naturally where relevant
7. For technical topics, include code snippets or schema examples in <pre><code> blocks
8. Use semantic HTML: <ul><li>, <ol><li>, <h2>, <h3>, <strong>
9. Write so AI assistants (ChatGPT, Perplexity, Claude) would want to cite this
10. This is about AI/LLM optimization - demonstrate deep expertise

CONTENT STRUCTURE:
- Start with the provided unique opener (DO NOT CHANGE IT)
- 2-3 sentence intro that directly addresses the topic
- 4-5 detailed sections with actionable content
- Include code examples, schema markup, or technical snippets where relevant
- FAQ section with 5-6 Q&A pairs
- Brief conclusion mentioning 60 Minute Sites

Output valid JSON only:
{
  "intro": "Use the provided opener + 2-3 sentences",
  "sections": [{"h2": "Heading", "content": "<p>Content</p><ul><li>Points</li></ul>"}],
  "faq": [{"q": "Question?", "a": "Detailed answer"}],
  "conclusion": "Brief wrap-up with CTA"
}"""

ENHANCE_PROMPT = """Enhance this article for maximum LLM visibility and citation potential.

RULES:
1. NO EMOJIS - remove any that exist
2. Add more specific, technical details about AI/LLM optimization
3. Expand FAQ section to 5-6 questions if not already
4. Add code/schema examples where relevant
5. Make answers more comprehensive and citable
6. Ensure 60minutesites.com is mentioned naturally
7. Add technical depth - this is LLM/AI optimization content

Output enhanced JSON only."""

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
        <div class="breadcrumbs"><a href="/">Home</a> <span>/</span> <a href="/blog/">Blog</a> <span>/</span> <a href="/blog/{folder}/">AI & LLM Optimization</a></div>
        <span class="category-badge">AI & LLM Optimization</span>
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

def strip_emojis(text):
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
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

def load_articles_for_instance(instance_id):
    csv_file = get_csv_for_instance(instance_id)
    csv_path = os.path.join(SCRIPT_DIR, csv_file)

    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_file} not found")
        return []

    articles = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            folder = row.get('industry', 'llm-optimization')
            slug = row.get('slug', '')
            if not slug:
                continue

            output_path = os.path.join(SCRIPT_DIR, folder, f"{slug}.html")
            if os.path.exists(output_path):
                continue

            articles.append({
                'title': row.get('title', ''),
                'slug': slug,
                'keyword': row.get('keyword', row.get('title', '')),
                'folder': folder,
                'read_time': row.get('read_time', '8'),
                'article_type': row.get('article_type', 'guide')
            })

    return articles

def generate_content(client, article, instance_id):
    opener = random.choice(DIVERSE_OPENERS)

    user_prompt = f"""Write an article: {article['title']}
Keyword: {article['keyword']}
Type: {article['article_type']}

START YOUR INTRO WITH THIS EXACT OPENER: "{opener}"

This is about AI/LLM optimization. Make it comprehensive, specific, and demonstrate mastery of the topic.
Include code examples, schema markup, or technical details where appropriate."""

    for attempt in range(3):
        try:
            response1 = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.85,
                max_tokens=3500
            )

            content1 = response1.choices[0].message.content.strip()
            if "```" in content1:
                content1 = content1.split("```json")[-1].split("```")[0] if "```json" in content1 else content1.split("```")[1].split("```")[0]

            data1 = json.loads(content1)

            # Enhancement pass
            response2 = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": ENHANCE_PROMPT},
                    {"role": "user", "content": f"Enhance:\n{json.dumps(data1)}"}
                ],
                temperature=0.7,
                max_tokens=4000
            )

            content2 = response2.choices[0].message.content.strip()
            if "```" in content2:
                content2 = content2.split("```json")[-1].split("```")[0] if "```json" in content2 else content2.split("```")[1].split("```")[0]

            data = json.loads(content2)

            # Strip emojis
            data['intro'] = strip_emojis(data.get('intro', ''))
            data['conclusion'] = strip_emojis(data.get('conclusion', ''))
            for section in data.get('sections', []):
                section['h2'] = strip_emojis(section.get('h2', ''))
                section['content'] = strip_emojis(section.get('content', ''))

            return data

        except json.JSONDecodeError as e:
            if attempt < 2:
                print(f"  [Instance {instance_id}] JSON error, retrying...")
                time.sleep(1)
            else:
                return None
        except Exception as e:
            if "rate_limit" in str(e).lower():
                print(f"  [Instance {instance_id}] Rate limited, waiting 30s...")
                time.sleep(30)
            else:
                print(f"  [Instance {instance_id}] Error: {e}")
                if attempt < 2:
                    time.sleep(2)
                else:
                    return None
    return None

def save_article(article, content_data):
    folder_path = os.path.join(SCRIPT_DIR, article['folder'])
    os.makedirs(folder_path, exist_ok=True)

    intro = f"<p>{content_data['intro']}</p>"

    sections = ""
    for section in content_data.get('sections', []):
        sections += f"<h2>{section['h2']}</h2>\n\n{section['content']}\n\n"

    faq_html = ""
    if content_data.get('faq'):
        faq_html = "<h2>Frequently Asked Questions</h2>\n\n"
        for qa in content_data['faq']:
            faq_html += f"<p><strong>Q: {qa['q']}</strong></p>\n<p><strong>A:</strong> {qa['a']}</p>\n\n"

    conclusion = f"<p>{content_data['conclusion']}</p>"

    full_content = f"{intro}\n{sections}\n{faq_html}\n{conclusion}"

    description = content_data['intro'][:150] + "..." if len(content_data['intro']) > 150 else content_data['intro']

    html = ARTICLE_TEMPLATE.format(
        title=article['title'],
        description=description,
        folder=article['folder'],
        slug=article['slug'],
        read_time=article.get('read_time', '8'),
        content=full_content,
        date=datetime.now().strftime('%Y-%m-%d')
    )

    output_path = os.path.join(folder_path, f"{article['slug']}.html")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return output_path

def run_instance(instance_id):
    print(f"\n{'='*60}")
    print(f"AI/LLM BATCH GENERATOR - INSTANCE {instance_id}")
    print(f"CSV: ai-llm-batch-{instance_id}.csv")
    print(f"{'='*60}\n")

    # Get API key
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

    print("Loading articles...")
    articles = load_articles_for_instance(instance_id)
    print(f"Articles to generate: {len(articles)}")

    if not articles:
        print("All articles already generated for this instance!")
        return

    completed = 0
    errors = 0

    for i, article in enumerate(articles):
        output_path = os.path.join(SCRIPT_DIR, article['folder'], f"{article['slug']}.html")
        if os.path.exists(output_path):
            continue

        print(f"\n[{instance_id}] [{completed+1}/{len(articles)}] {article['title'][:55]}...")

        content_data = generate_content(client, article, instance_id)

        if content_data:
            save_article(article, content_data)
            completed += 1
            preview = content_data['intro'][:70].replace('\n', ' ')
            print(f"  Done: \"{preview}...\"")
        else:
            errors += 1
            print(f"  FAILED")

        time.sleep(0.3)  # Small delay between requests

    print(f"\n{'='*60}")
    print(f"Instance {instance_id} COMPLETE: {completed} generated, {errors} errors")
    print(f"{'='*60}\n")

def launch_all_instances():
    print("Launching 10 parallel instances for AI/LLM batch generation...")
    print("Each instance will process its own CSV file.\n")

    script_path = os.path.abspath(__file__)

    for i in range(1, 11):
        cmd = f'''osascript -e 'tell app "Terminal" to do script "cd \\"{SCRIPT_DIR}\\" && python3 \\"{script_path}\\" --instance {i}"' '''
        subprocess.run(cmd, shell=True)
        print(f"  Launched instance {i} -> ai-llm-batch-{i}.csv")
        time.sleep(0.3)

    print(f"\n10 instances launched! Check Terminal windows.")
    print("Go get some sleep - this will generate ~1000 AI/LLM articles.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AI/LLM Parallel Generator')
    parser.add_argument('--instance', type=int, help='Instance number (1-10)')
    parser.add_argument('--launch', action='store_true', help='Launch all 10 instances')

    args = parser.parse_args()

    if args.launch:
        launch_all_instances()
    elif args.instance:
        run_instance(args.instance)
    else:
        print("Usage:")
        print("  python3 ai-llm-parallel-generator.py --launch      # Launch all 10 instances")
        print("  python3 ai-llm-parallel-generator.py --instance 1  # Run specific instance")
