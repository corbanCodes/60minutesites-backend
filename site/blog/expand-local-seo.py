#!/usr/bin/env python3
"""
Expand local-seo CSV with city-specific articles
"""

import csv
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Top 100 US cities by population
CITIES = [
    "New York", "Los Angeles", "Chicago", "Houston", "Phoenix",
    "Philadelphia", "San Antonio", "San Diego", "Dallas", "San Jose",
    "Austin", "Jacksonville", "Fort Worth", "Columbus", "Charlotte",
    "San Francisco", "Indianapolis", "Seattle", "Denver", "Washington DC",
    "Boston", "El Paso", "Nashville", "Detroit", "Oklahoma City",
    "Portland", "Las Vegas", "Memphis", "Louisville", "Baltimore",
    "Milwaukee", "Albuquerque", "Tucson", "Fresno", "Sacramento",
    "Mesa", "Kansas City", "Atlanta", "Miami", "Colorado Springs",
    "Raleigh", "Omaha", "Long Beach", "Virginia Beach", "Oakland",
    "Minneapolis", "Tulsa", "Tampa", "Arlington", "New Orleans",
    "Wichita", "Cleveland", "Bakersfield", "Aurora", "Anaheim",
    "Honolulu", "Santa Ana", "Riverside", "Corpus Christi", "Lexington",
    "Henderson", "Stockton", "Saint Paul", "Cincinnati", "St. Louis",
    "Pittsburgh", "Greensboro", "Lincoln", "Anchorage", "Plano",
    "Orlando", "Irvine", "Newark", "Durham", "Chula Vista",
    "Toledo", "Fort Wayne", "St. Petersburg", "Laredo", "Jersey City",
    "Chandler", "Madison", "Lubbock", "Scottsdale", "Reno",
    "Buffalo", "Gilbert", "Glendale", "North Las Vegas", "Winston-Salem",
    "Chesapeake", "Norfolk", "Fremont", "Garland", "Irving",
    "Hialeah", "Richmond", "Boise", "Spokane", "Baton Rouge"
]

# Question templates for each city
CITY_TEMPLATES = [
    ("{city_slug}-local-seo-guide", "Local SEO Guide for {city} Businesses", "local seo {city_lower}", 10, "guide"),
    ("{city_slug}-google-business-profile", "Google Business Profile Setup for {city}", "google business profile {city_lower}", 8, "guide"),
    ("{city_slug}-rank-google-maps", "How to Rank on Google Maps in {city}", "rank google maps {city_lower}", 9, "guide"),
    ("{city_slug}-local-keywords", "Best Local Keywords for {city} Businesses", "local keywords {city_lower}", 7, "guide"),
    ("{city_slug}-get-more-reviews", "How to Get More Google Reviews in {city}", "google reviews {city_lower}", 7, "guide"),
]

def generate_city_articles():
    articles = []
    
    for city in CITIES:
        city_slug = city.lower().replace(' ', '-').replace('.', '')
        city_lower = city.lower()
        
        for template in CITY_TEMPLATES:
            slug_template, title_template, keyword_template, read_time, article_type = template
            
            articles.append({
                'industry': 'local-seo',
                'slug': slug_template.format(city_slug=city_slug),
                'title': title_template.format(city=city),
                'keyword': keyword_template.format(city_lower=city_lower),
                'read_time': read_time,
                'article_type': article_type
            })
    
    return articles

def main():
    # Read existing articles
    existing_path = os.path.join(SCRIPT_DIR, 'blog-articles-local-seo.csv')
    existing = []
    
    if os.path.exists(existing_path):
        with open(existing_path, 'r') as f:
            reader = csv.DictReader(f)
            existing = list(reader)
    
    print(f"Existing articles: {len(existing)}")
    
    # Generate city articles
    city_articles = generate_city_articles()
    print(f"City articles generated: {len(city_articles)}")
    
    # Combine
    all_articles = existing + city_articles
    print(f"Total articles: {len(all_articles)}")
    
    # Write back
    with open(existing_path, 'w', newline='') as f:
        fieldnames = ['industry', 'slug', 'title', 'keyword', 'read_time', 'article_type']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_articles)
    
    print(f"Written to: {existing_path}")

if __name__ == '__main__':
    main()
