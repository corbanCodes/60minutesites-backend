# PRD: Technical SEO & LLM Optimization

## Scope
No UI changes. Backend/technical optimizations only.

---

## Phase 1: AI Crawler Configuration (DO NOW)

### 1.1 robots.txt Updates
```
# AI Crawlers - Welcome
User-agent: GPTBot
Allow: /

User-agent: Claude-Web
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: Anthropic-AI
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: Applebot-Extended
Allow: /

# Standard crawlers
User-agent: *
Allow: /
Sitemap: https://60minutesites.com/sitemap.xml
```

### 1.2 llms.txt File (New Standard)
Create `/llms.txt` - tells AI crawlers what your site is about:
```
# 60 Minute Sites
> Done-for-you websites live in 60 minutes. $100 setup + $50/month.

## About
Professional websites for small businesses, contractors, and local services.
AI-optimized content for maximum visibility in ChatGPT, Claude, Perplexity.

## Services
- Website design and development
- LLM/AI search optimization
- Local SEO
- Lead generation

## Contact
- Website: https://60minutesites.com
- Pricing: $100 setup + $50/month OR $500/year

## Documentation
- Blog: https://60minutesites.com/blog/
- Templates: https://60minutesites.com/templates.html
```

---

## Phase 2: After 1K Articles Complete

### 2.1 Regenerate Sitemap
- Run `python3 generate-sitemap.py`
- Should now include ~15k URLs
- Verify sitemap.xml is under 50MB limit

### 2.2 Sitemap Index (if needed)
If sitemap exceeds limits, split into:
- sitemap-blog-1.xml (industries A-M)
- sitemap-blog-2.xml (industries N-Z)
- sitemap-pages.xml (main pages)
- sitemap-index.xml (master)

### 2.3 Submit to Search Engines
```bash
# Ping Google
curl "https://www.google.com/ping?sitemap=https://60minutesites.com/sitemap.xml"

# Bing Webmaster submit via portal
```

---

## Phase 3: Schema Enhancements (Optional)

### 3.1 Organization Schema (homepage)
```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "name": "60 Minute Sites",
  "url": "https://60minutesites.com",
  "description": "Done-for-you websites live in 60 minutes",
  "priceRange": "$100-$500"
}
```

### 3.2 WebSite Schema with SearchAction
```json
{
  "@context": "https://schema.org",
  "@type": "WebSite",
  "url": "https://60minutesites.com",
  "potentialAction": {
    "@type": "SearchAction",
    "target": "https://60minutesites.com/blog/?q={search_term_string}",
    "query-input": "required name=search_term_string"
  }
}
```

---

## Execution Order

1. **NOW**: robots.txt + llms.txt (5 min)
2. **WAIT**: Let 1k articles finish generating
3. **THEN**: Regenerate sitemap, ping search engines

---

## How to Run Dangerously

```bash
claude --dangerously-skip-permissions
```

This bypasses all permission prompts. Use in trusted repos only.
