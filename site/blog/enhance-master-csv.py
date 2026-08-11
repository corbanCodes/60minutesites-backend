#!/usr/bin/env python3
"""
Enhance the master CSV with:
1. Question-format titles for voice search/featured snippets
2. Better long-tail keywords
3. More variety in article types
4. Expand to ~1500 lines
"""

import csv
import os

INDUSTRIES = [
    ('construction', 'Construction'),
    ('plumber', 'Plumber'),
    ('electrician', 'Electrician'),
    ('hvac', 'HVAC'),
    ('cleaning', 'Cleaning'),
    ('salon', 'Salon'),
    ('spa', 'Spa'),
    ('barber', 'Barber'),
    ('massage', 'Massage'),
    ('fitness', 'Fitness'),
    ('restaurant', 'Restaurant'),
    ('real-estate', 'Real Estate'),
    ('photography', 'Photography'),
    ('automotive', 'Automotive'),
    ('pest-control', 'Pest Control'),
    ('insurance', 'Insurance'),
    ('mortgage', 'Mortgage'),
    ('architect', 'Architect'),
    ('interior-design', 'Interior Design'),
    ('event', 'Event Planning'),
    ('music', 'Music'),
    ('health-beauty', 'Health & Beauty'),
    ('landscaping', 'Landscaping'),
    ('roofing', 'Roofing'),
    ('painting', 'Painting'),
    ('flooring', 'Flooring'),
    ('dental', 'Dental'),
    ('veterinary', 'Veterinary'),
    ('legal', 'Legal'),
    ('accounting', 'Accounting'),
]

# Question templates - these rank well for featured snippets and voice search
QUESTION_TEMPLATES = [
    ("what-should-{ind}-website-include", "What Should a {Industry} Website Include?", "what should {industry} website include", 8, "guide"),
    ("how-much-{ind}-website-cost", "How Much Does a {Industry} Website Cost in 2026?", "how much does {industry} website cost", 9, "guide"),
    ("do-{ind}s-need-website", "Do {Industry}s Really Need a Website in 2026?", "do {industry}s need a website", 7, "guide"),
    ("why-{ind}-website-not-working", "Why Is My {Industry} Website Not Getting Leads?", "{industry} website not getting leads", 8, "guide"),
    ("how-get-clients-{ind}-website", "How to Get More Clients From Your {Industry} Website", "get more clients {industry} website", 9, "guide"),
    ("what-makes-good-{ind}-website", "What Makes a Good {Industry} Website?", "what makes good {industry} website", 7, "guide"),
    ("how-long-build-{ind}-website", "How Long Does It Take to Build a {Industry} Website?", "how long build {industry} website", 6, "guide"),
    ("should-{ind}-use-wix", "Should {Industry}s Use Wix for Their Website?", "should {industry} use wix", 7, "comparison"),
    ("is-squarespace-good-{ind}", "Is Squarespace Good for {Industry} Websites?", "squarespace {industry} website", 7, "comparison"),
    ("can-build-{ind}-website-myself", "Can I Build My Own {Industry} Website?", "build own {industry} website", 8, "guide"),
    ("how-update-{ind}-website", "How Often Should I Update My {Industry} Website?", "update {industry} website", 6, "guide"),
    ("what-pages-{ind}-website-need", "What Pages Does a {Industry} Website Need?", "pages {industry} website needs", 7, "checklist"),
]

# Long-tail keyword templates - specific, lower competition
LONGTAIL_TEMPLATES = [
    ("{ind}-website-template-free", "Free {Industry} Website Templates: What to Look For", "free {industry} website template", 7, "guide"),
    ("{ind}-website-design-ideas", "{Industry} Website Design Ideas That Convert", "{industry} website design ideas", 8, "examples"),
    ("best-{ind}-website-2026", "Best {Industry} Websites in 2026: Examples to Copy", "best {industry} website 2026", 9, "examples"),
    ("{ind}-website-before-after", "{Industry} Website Redesign: Before and After Examples", "{industry} website redesign examples", 7, "examples"),
    ("{ind}-website-color-scheme", "Best Color Schemes for {Industry} Websites", "{industry} website colors", 6, "guide"),
    ("{ind}-website-fonts", "Best Fonts for {Industry} Websites", "{industry} website fonts", 5, "guide"),
    ("{ind}-website-images", "Where to Get Images for Your {Industry} Website", "{industry} website images", 6, "guide"),
    ("{ind}-website-copywriting", "Website Copywriting Tips for {Industry}s", "{industry} website copywriting", 8, "guide"),
    ("{ind}-website-testimonials-examples", "Testimonial Examples for {Industry} Websites", "{industry} website testimonials examples", 6, "examples"),
    ("{ind}-website-call-to-action", "Best Call-to-Action Buttons for {Industry} Websites", "{industry} website call to action", 7, "examples"),
    ("{ind}-website-hero-section", "Hero Section Ideas for {Industry} Websites", "{industry} website hero section", 6, "examples"),
    ("{ind}-website-contact-page", "Contact Page Best Practices for {Industry}s", "{industry} contact page", 6, "guide"),
    ("{ind}-website-about-us", "How to Write an About Page for {Industry} Websites", "{industry} about page", 7, "guide"),
    ("{ind}-website-services-list", "How to List Services on Your {Industry} Website", "{industry} services page", 7, "guide"),
    ("{ind}-website-pricing-page", "Should {Industry}s Show Prices on Their Website?", "{industry} pricing page", 7, "guide"),
    ("{ind}-website-booking-system", "Best Online Booking Systems for {Industry}s", "{industry} online booking", 8, "comparison"),
    ("{ind}-website-chat-widget", "Should {Industry}s Add Live Chat to Their Website?", "{industry} website live chat", 6, "guide"),
    ("{ind}-website-google-reviews", "How to Add Google Reviews to Your {Industry} Website", "{industry} google reviews website", 7, "guide"),
    ("{ind}-website-social-proof", "Social Proof Ideas for {Industry} Websites", "{industry} website social proof", 7, "guide"),
    ("{ind}-website-trust-badges", "Trust Badges for {Industry} Websites", "{industry} website trust badges", 5, "guide"),
]

# Comparison/alternative templates
COMPARISON_TEMPLATES = [
    ("{ind}-website-vs-social-media", "{Industry} Website vs Social Media: Which Matters More?", "{industry} website vs social media", 8, "comparison"),
    ("{ind}-website-vs-google-business", "{Industry} Website vs Google Business Profile", "{industry} website vs google business", 7, "comparison"),
    ("{ind}-website-vs-yelp", "Does a {Industry} Need a Website If They Have Yelp?", "{industry} website vs yelp", 6, "comparison"),
    ("{ind}-diy-vs-professional-website", "DIY vs Professional {Industry} Website: Real Costs", "diy vs professional {industry} website", 9, "comparison"),
    ("{ind}-website-builder-vs-custom", "Website Builder vs Custom Site for {Industry}s", "{industry} website builder vs custom", 8, "comparison"),
    ("wix-vs-squarespace-{ind}", "Wix vs Squarespace for {Industry} Websites", "wix vs squarespace {industry}", 8, "comparison"),
    ("wordpress-vs-wix-{ind}", "WordPress vs Wix for {Industry} Websites", "wordpress vs wix {industry}", 8, "comparison"),
    ("{ind}-website-agency-vs-freelancer", "Agency vs Freelancer for Your {Industry} Website", "{industry} website agency vs freelancer", 7, "comparison"),
]

# Problem/solution templates - high intent
PROBLEM_TEMPLATES = [
    ("{ind}-website-no-traffic", "Why Your {Industry} Website Gets No Traffic (And How to Fix It)", "{industry} website no traffic", 9, "guide"),
    ("{ind}-website-no-calls", "Why Your {Industry} Website Isn't Getting Phone Calls", "{industry} website not getting calls", 8, "guide"),
    ("{ind}-website-high-bounce-rate", "How to Fix High Bounce Rate on Your {Industry} Website", "{industry} website bounce rate", 8, "guide"),
    ("{ind}-website-slow-loading", "How to Speed Up Your {Industry} Website", "{industry} website slow", 7, "guide"),
    ("{ind}-website-not-mobile-friendly", "How to Make Your {Industry} Website Mobile-Friendly", "{industry} website mobile friendly", 7, "guide"),
    ("{ind}-website-outdated", "Signs Your {Industry} Website Looks Outdated", "{industry} website outdated", 6, "checklist"),
    ("{ind}-website-not-ranking", "Why Your {Industry} Website Isn't Ranking on Google", "{industry} website not ranking", 9, "guide"),
    ("{ind}-website-bad-reviews", "How to Handle Bad Reviews on Your {Industry} Website", "{industry} website bad reviews", 7, "guide"),
]

# Numbered list templates - great for CTR
NUMBERED_TEMPLATES = [
    ("5-{ind}-website-mistakes", "5 {Industry} Website Mistakes That Cost You Customers", "{industry} website mistakes", 7, "mistakes"),
    ("7-{ind}-website-must-haves", "7 Must-Have Features for {Industry} Websites", "{industry} website features", 8, "checklist"),
    ("10-{ind}-website-tips", "10 {Industry} Website Tips to Get More Leads", "{industry} website tips", 9, "guide"),
    ("3-{ind}-website-quick-wins", "3 Quick Wins for Your {Industry} Website Today", "{industry} website quick wins", 5, "guide"),
    ("12-{ind}-website-elements", "12 Essential Elements Every {Industry} Website Needs", "{industry} website elements", 8, "checklist"),
    ("6-{ind}-seo-tips", "6 SEO Tips for {Industry} Websites", "{industry} seo tips", 8, "guide"),
    ("8-{ind}-website-trends", "{Industry} Website Trends for 2026", "{industry} website trends 2026", 7, "guide"),
    ("4-{ind}-landing-page-tips", "4 Landing Page Tips for {Industry}s", "{industry} landing page tips", 6, "guide"),
]

# Local SEO templates
LOCAL_SEO_TEMPLATES = [
    ("{ind}-website-local-seo", "Local SEO for {Industry}s: Complete Guide", "{industry} local seo", 10, "guide"),
    ("{ind}-google-business-setup", "Google Business Profile Setup for {Industry}s", "{industry} google business profile", 9, "guide"),
    ("{ind}-website-service-areas", "How to Set Up Service Area Pages for {Industry} Websites", "{industry} service area pages", 8, "guide"),
    ("{ind}-website-local-keywords", "Local Keywords for {Industry} Websites", "{industry} local keywords", 7, "guide"),
    ("{ind}-website-map-embed", "How to Add Google Maps to Your {Industry} Website", "{industry} website google maps", 5, "guide"),
    ("{ind}-website-nap-consistency", "NAP Consistency for {Industry} Websites", "{industry} nap consistency", 6, "guide"),
    ("{ind}-website-local-citations", "Local Citations for {Industry}s: Where to List Your Business", "{industry} local citations", 8, "guide"),
    ("{ind}-website-schema-local", "Local Business Schema for {Industry} Websites", "{industry} local schema", 7, "guide"),
]

def generate_articles():
    """Generate all article entries."""
    articles = []
    
    all_templates = (
        QUESTION_TEMPLATES + 
        LONGTAIL_TEMPLATES + 
        COMPARISON_TEMPLATES + 
        PROBLEM_TEMPLATES + 
        NUMBERED_TEMPLATES +
        LOCAL_SEO_TEMPLATES
    )
    
    for ind_slug, ind_name in INDUSTRIES:
        # Handle plural forms
        ind_lower = ind_name.lower()
        ind_plural = ind_lower + 's' if not ind_lower.endswith('s') else ind_lower
        
        for template in all_templates:
            slug_template, title_template, keyword_template, read_time, article_type = template
            
            # Generate slug
            slug = slug_template.format(ind=ind_slug)
            
            # Generate title
            title = title_template.format(Industry=ind_name, industry=ind_lower)
            
            # Generate keyword
            keyword = keyword_template.format(industry=ind_lower)
            
            articles.append({
                'industry': ind_slug,
                'slug': slug,
                'title': title,
                'keyword': keyword,
                'read_time': read_time,
                'article_type': article_type
            })
    
    return articles

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(script_dir, 'blog-articles-master.csv')
    backup_file = os.path.join(script_dir, 'blog-articles-master-backup.csv')
    
    # Backup existing
    if os.path.exists(output_file):
        import shutil
        shutil.copy(output_file, backup_file)
        print(f"Backed up existing CSV to {backup_file}")
    
    # Generate new articles
    articles = generate_articles()
    
    # Write CSV
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['industry', 'slug', 'title', 'keyword', 'read_time', 'article_type'])
        writer.writeheader()
        writer.writerows(articles)
    
    print(f"Generated {len(articles)} articles")
    print(f"Written to {output_file}")
    
    # Stats
    industries = {}
    types = {}
    for a in articles:
        industries[a['industry']] = industries.get(a['industry'], 0) + 1
        types[a['article_type']] = types.get(a['article_type'], 0) + 1
    
    print(f"\nIndustries: {len(industries)}")
    print(f"Articles per industry: {len(articles) // len(industries)}")
    print(f"\nArticle types:")
    for t, count in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count}")

if __name__ == '__main__':
    main()
