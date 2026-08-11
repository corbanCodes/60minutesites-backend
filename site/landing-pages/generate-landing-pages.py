#!/usr/bin/env python3
"""
Generate landing pages from the plumber template.
Run: python3 generate-landing-pages.py
"""

import os
import re

# Landing page configurations
VERTICALS = [
    {
        "slug": "salon",
        "name": "Salon",
        "headline": "Attract More <span>Salon Clients</span> With a Stunning Website",
        "subtitle": "Your salon website live in 60 minutes. Showcase your stylists, display your services, and let clients book appointments online.",
        "benefit1_icon": "fa-calendar-check",
        "benefit1_title": "Enable Online Booking",
        "benefit1_desc": "Let clients book appointments 24/7 with integrated scheduling that syncs with your calendar.",
        "benefit2_icon": "fa-images",
        "benefit2_title": "Showcase Your Work",
        "benefit2_desc": "Beautiful galleries to display your stylists' best work and attract clients who love your style.",
        "benefit3_icon": "fa-list-alt",
        "benefit3_title": "Display Your Services",
        "benefit3_desc": "Professional service menus with pricing that help clients choose the right services for them.",
        "template1": "Glamour", "template1_style": "Elegant & Modern",
        "template2": "Style Studio", "template2_style": "Bold & Creative",
        "template3": "Beauty Bar", "template3_style": "Clean & Sophisticated",
        "final_cta": "Ready to Grow Your Salon Business?",
        "final_desc": "Get your professional website live today. Start booking more clients and showcasing your talent online.",
        "filter": "salon"
    },
    {
        "slug": "restaurant",
        "name": "Restaurant",
        "headline": "Fill More <span>Restaurant Tables</span> With a Professional Website",
        "subtitle": "Your restaurant website live in 60 minutes. Showcase your menu, enable reservations, and bring more diners through your doors.",
        "benefit1_icon": "fa-utensils",
        "benefit1_title": "Display Your Menu",
        "benefit1_desc": "Beautiful, mobile-friendly menus that make customers hungry and ready to visit or order.",
        "benefit2_icon": "fa-calendar-alt",
        "benefit2_title": "Enable Reservations",
        "benefit2_desc": "Let diners book tables online with integrated reservation systems that reduce no-shows.",
        "benefit3_icon": "fa-map-marker-alt",
        "benefit3_title": "Get Found Locally",
        "benefit3_desc": "SEO-optimized pages help you show up when people search for restaurants in your area.",
        "template1": "Bistro", "template1_style": "Elegant & Appetizing",
        "template2": "Dine", "template2_style": "Modern & Clean",
        "template3": "Feast", "template3_style": "Bold & Inviting",
        "final_cta": "Ready to Grow Your Restaurant Business?",
        "final_desc": "Get your professional website live today. Start filling more tables and growing your reputation online.",
        "filter": "restaurant"
    },
    {
        "slug": "fitness",
        "name": "Fitness",
        "headline": "Get More <span>Gym Members</span> With a Professional Website",
        "subtitle": "Your fitness website live in 60 minutes. Showcase your facility, display class schedules, and convert visitors into members.",
        "benefit1_icon": "fa-dumbbell",
        "benefit1_title": "Showcase Your Facility",
        "benefit1_desc": "Photo galleries and virtual tours that show off your equipment, classes, and atmosphere.",
        "benefit2_icon": "fa-calendar-week",
        "benefit2_title": "Display Class Schedules",
        "benefit2_desc": "Easy-to-read schedules that help members find the perfect classes for their goals.",
        "benefit3_icon": "fa-user-plus",
        "benefit3_title": "Convert Visitors to Members",
        "benefit3_desc": "Membership signup forms and free trial offers that turn website visitors into paying members.",
        "template1": "Iron", "template1_style": "Bold & Powerful",
        "template2": "FitLife", "template2_style": "Modern & Energetic",
        "template3": "Pulse", "template3_style": "Clean & Motivating",
        "final_cta": "Ready to Grow Your Fitness Business?",
        "final_desc": "Get your professional website live today. Start attracting more members and building your community online.",
        "filter": "fitness"
    },
    {
        "slug": "real-estate",
        "name": "Real Estate",
        "headline": "Close More <span>Real Estate Deals</span> With a Professional Website",
        "subtitle": "Your real estate website live in 60 minutes. Showcase your listings, build your personal brand, and generate more leads.",
        "benefit1_icon": "fa-home",
        "benefit1_title": "Showcase Your Listings",
        "benefit1_desc": "Beautiful property galleries with photos, details, and virtual tour integration that sell homes.",
        "benefit2_icon": "fa-user-tie",
        "benefit2_title": "Build Your Brand",
        "benefit2_desc": "Professional agent profiles and testimonials that establish you as the go-to expert in your market.",
        "benefit3_icon": "fa-search-location",
        "benefit3_title": "Capture Buyer Leads",
        "benefit3_desc": "Property search tools and contact forms that capture serious buyers and sellers 24/7.",
        "template1": "Premier", "template1_style": "Luxury & Professional",
        "template2": "HomeBase", "template2_style": "Modern & Trustworthy",
        "template3": "Keystone", "template3_style": "Clean & Conversion-Focused",
        "final_cta": "Ready to Grow Your Real Estate Business?",
        "final_desc": "Get your professional website live today. Start generating more leads and closing more deals online.",
        "filter": "real-estate"
    },
    {
        "slug": "hvac",
        "name": "HVAC",
        "headline": "Get More <span>HVAC Service Calls</span> With a Professional Website",
        "subtitle": "Your HVAC website live in 60 minutes. Capture emergency calls 24/7, showcase your services, and grow your heating and cooling business.",
        "benefit1_icon": "fa-snowflake",
        "benefit1_title": "Capture Emergency Calls",
        "benefit1_desc": "Click-to-call buttons and 24/7 availability badges for when AC breaks down in summer heat.",
        "benefit2_icon": "fa-tools",
        "benefit2_title": "Showcase All Services",
        "benefit2_desc": "Dedicated pages for heating, cooling, maintenance, and installation that rank in local search.",
        "benefit3_icon": "fa-certificate",
        "benefit3_title": "Display Credentials",
        "benefit3_desc": "Show your HVAC certifications, manufacturer partnerships, and insurance to build instant trust.",
        "template1": "Climate Pro", "template1_style": "Professional & Trustworthy",
        "template2": "AirFlow", "template2_style": "Modern & Clean",
        "template3": "Comfort Zone", "template3_style": "Friendly & Approachable",
        "final_cta": "Ready to Grow Your HVAC Business?",
        "final_desc": "Get your professional website live today. Start capturing more service calls and building trust online.",
        "filter": "hvac"
    },
    {
        "slug": "cleaning",
        "name": "Cleaning",
        "headline": "Book More <span>Cleaning Jobs</span> With a Professional Website",
        "subtitle": "Your cleaning business website live in 60 minutes. Showcase your services, display pricing, and let customers book online.",
        "benefit1_icon": "fa-spray-can",
        "benefit1_title": "Showcase Your Services",
        "benefit1_desc": "Detailed service pages for residential, commercial, deep cleaning, and specialty services.",
        "benefit2_icon": "fa-calculator",
        "benefit2_title": "Display Clear Pricing",
        "benefit2_desc": "Transparent pricing or quote request forms that help customers understand your value.",
        "benefit3_icon": "fa-calendar-check",
        "benefit3_title": "Enable Online Booking",
        "benefit3_desc": "Let customers schedule cleanings online with integrated booking that fills your calendar.",
        "template1": "Sparkle", "template1_style": "Fresh & Professional",
        "template2": "CleanSlate", "template2_style": "Modern & Trustworthy",
        "template3": "Pristine", "template3_style": "Clean & Conversion-Focused",
        "final_cta": "Ready to Grow Your Cleaning Business?",
        "final_desc": "Get your professional website live today. Start booking more jobs and building your client base online.",
        "filter": "cleaning"
    },
    {
        "slug": "photography",
        "name": "Photography",
        "headline": "Book More <span>Photography Clients</span> With a Stunning Portfolio Website",
        "subtitle": "Your photography website live in 60 minutes. Showcase your best work, display your packages, and attract dream clients.",
        "benefit1_icon": "fa-camera",
        "benefit1_title": "Showcase Your Portfolio",
        "benefit1_desc": "Beautiful, fast-loading galleries that display your work exactly how you want it seen.",
        "benefit2_icon": "fa-tags",
        "benefit2_title": "Display Your Packages",
        "benefit2_desc": "Clear pricing and package information that helps clients choose the right option for them.",
        "benefit3_icon": "fa-envelope",
        "benefit3_title": "Capture Inquiries",
        "benefit3_desc": "Contact forms that gather the right information to qualify leads before you respond.",
        "template1": "Aperture", "template1_style": "Minimal & Elegant",
        "template2": "Focus", "template2_style": "Bold & Creative",
        "template3": "Capture", "template3_style": "Clean & Professional",
        "final_cta": "Ready to Grow Your Photography Business?",
        "final_desc": "Get your professional website live today. Start attracting dream clients and showcasing your art online.",
        "filter": "photography"
    },
    {
        "slug": "automotive",
        "name": "Automotive",
        "headline": "Get More <span>Auto Shop Customers</span> With a Professional Website",
        "subtitle": "Your auto shop website live in 60 minutes. Showcase your services, build trust with car owners, and fill your bays.",
        "benefit1_icon": "fa-car",
        "benefit1_title": "Showcase All Services",
        "benefit1_desc": "Detailed pages for repairs, maintenance, inspections, and specialty services you offer.",
        "benefit2_icon": "fa-shield-alt",
        "benefit2_title": "Build Customer Trust",
        "benefit2_desc": "Display certifications, warranties, and reviews that make car owners confident choosing you.",
        "benefit3_icon": "fa-calendar-alt",
        "benefit3_title": "Enable Appointments",
        "benefit3_desc": "Online scheduling for oil changes, inspections, and repairs that keeps your shop busy.",
        "template1": "AutoPro", "template1_style": "Professional & Trustworthy",
        "template2": "Garage", "template2_style": "Bold & Industrial",
        "template3": "DriveTime", "template3_style": "Modern & Clean",
        "final_cta": "Ready to Grow Your Auto Shop Business?",
        "final_desc": "Get your professional website live today. Start filling more bays and building customer loyalty online.",
        "filter": "automotive"
    },
    {
        "slug": "spa",
        "name": "Spa",
        "headline": "Attract More <span>Spa Clients</span> With a Relaxing Website Experience",
        "subtitle": "Your spa website live in 60 minutes. Showcase your treatments, create a serene online presence, and let clients book their escape.",
        "benefit1_icon": "fa-spa",
        "benefit1_title": "Showcase Your Treatments",
        "benefit1_desc": "Beautiful service menus with descriptions that help clients choose their perfect relaxation experience.",
        "benefit2_icon": "fa-calendar-check",
        "benefit2_title": "Enable Online Booking",
        "benefit2_desc": "Let clients book massages, facials, and packages online with integrated scheduling.",
        "benefit3_icon": "fa-gift",
        "benefit3_title": "Sell Gift Cards",
        "benefit3_desc": "Gift card purchasing options that drive revenue and bring new clients through your doors.",
        "template1": "Serenity", "template1_style": "Calm & Elegant",
        "template2": "Tranquil", "template2_style": "Modern & Peaceful",
        "template3": "Oasis", "template3_style": "Luxurious & Inviting",
        "final_cta": "Ready to Grow Your Spa Business?",
        "final_desc": "Get your professional website live today. Start booking more treatments and growing your wellness brand online.",
        "filter": "spa"
    },
    {
        "slug": "barber",
        "name": "Barber",
        "headline": "Fill Your <span>Barber Chair</span> With a Professional Website",
        "subtitle": "Your barbershop website live in 60 minutes. Showcase your cuts, let clients book online, and build your reputation.",
        "benefit1_icon": "fa-cut",
        "benefit1_title": "Showcase Your Work",
        "benefit1_desc": "Photo galleries of your best cuts, fades, and styles that show clients what you can do.",
        "benefit2_icon": "fa-calendar-check",
        "benefit2_title": "Enable Online Booking",
        "benefit2_desc": "Let clients book their preferred barber and time slot online, reducing no-shows.",
        "benefit3_icon": "fa-users",
        "benefit3_title": "Feature Your Team",
        "benefit3_desc": "Individual barber profiles with specialties and availability that help clients choose.",
        "template1": "Sharp", "template1_style": "Bold & Modern",
        "template2": "Classic Cut", "template2_style": "Traditional & Professional",
        "template3": "Fade", "template3_style": "Urban & Trendy",
        "final_cta": "Ready to Grow Your Barbershop Business?",
        "final_desc": "Get your professional website live today. Start filling more chairs and building your client base online.",
        "filter": "barber"
    },
    {
        "slug": "painter",
        "name": "Painter",
        "headline": "Book More <span>Painting Jobs</span> With a Professional Website",
        "subtitle": "Your painting business website live in 60 minutes. Showcase your work, display your services, and get more quote requests.",
        "benefit1_icon": "fa-paint-roller",
        "benefit1_title": "Showcase Your Work",
        "benefit1_desc": "Before and after galleries that prove your quality and help clients visualize their projects.",
        "benefit2_icon": "fa-palette",
        "benefit2_title": "Display All Services",
        "benefit2_desc": "Interior, exterior, commercial, residential - show clients everything you offer.",
        "benefit3_icon": "fa-file-invoice",
        "benefit3_title": "Get Quote Requests",
        "benefit3_desc": "Easy quote request forms that capture project details and generate qualified leads.",
        "template1": "BrushPro", "template1_style": "Clean & Professional",
        "template2": "ColorCraft", "template2_style": "Bold & Creative",
        "template3": "PaintMaster", "template3_style": "Modern & Trustworthy",
        "final_cta": "Ready to Grow Your Painting Business?",
        "final_desc": "Get your professional website live today. Start booking more jobs and showcasing your craftsmanship online.",
        "filter": "painter"
    },
    {
        "slug": "pest-control",
        "name": "Pest Control",
        "headline": "Get More <span>Pest Control Calls</span> With a Professional Website",
        "subtitle": "Your pest control website live in 60 minutes. Capture emergency calls, showcase your services, and grow your extermination business.",
        "benefit1_icon": "fa-bug",
        "benefit1_title": "Capture Emergency Calls",
        "benefit1_desc": "Click-to-call buttons for when customers need immediate help with infestations.",
        "benefit2_icon": "fa-shield-alt",
        "benefit2_title": "Build Trust & Safety",
        "benefit2_desc": "Display licenses, certifications, and safe treatment methods that reassure homeowners.",
        "benefit3_icon": "fa-map-marked-alt",
        "benefit3_title": "Show Service Areas",
        "benefit3_desc": "Service area pages that help you rank for local pest control searches in your territory.",
        "template1": "BugShield", "template1_style": "Professional & Trustworthy",
        "template2": "PestFree", "template2_style": "Clean & Reassuring",
        "template3": "Exterminator Pro", "template3_style": "Bold & Confident",
        "final_cta": "Ready to Grow Your Pest Control Business?",
        "final_desc": "Get your professional website live today. Start capturing more service calls and building trust online.",
        "filter": "pest-control"
    },
    {
        "slug": "massage",
        "name": "Massage",
        "headline": "Book More <span>Massage Clients</span> With a Relaxing Website",
        "subtitle": "Your massage therapy website live in 60 minutes. Showcase your services, enable online booking, and grow your practice.",
        "benefit1_icon": "fa-hands",
        "benefit1_title": "Showcase Your Services",
        "benefit1_desc": "Detailed service descriptions for Swedish, deep tissue, sports massage, and specialties.",
        "benefit2_icon": "fa-calendar-check",
        "benefit2_title": "Enable Online Booking",
        "benefit2_desc": "Let clients book appointments online with integrated scheduling that fills your calendar.",
        "benefit3_icon": "fa-certificate",
        "benefit3_title": "Display Credentials",
        "benefit3_desc": "Show your certifications, training, and specializations to build client confidence.",
        "template1": "Therapeutic", "template1_style": "Calm & Professional",
        "template2": "Healing Hands", "template2_style": "Warm & Inviting",
        "template3": "Restore", "template3_style": "Modern & Serene",
        "final_cta": "Ready to Grow Your Massage Practice?",
        "final_desc": "Get your professional website live today. Start booking more clients and building your wellness brand online.",
        "filter": "massage"
    },
    {
        "slug": "health-beauty",
        "name": "Health & Beauty",
        "headline": "Attract More <span>Beauty Clients</span> With a Stunning Website",
        "subtitle": "Your health and beauty website live in 60 minutes. Showcase your services, enable bookings, and grow your wellness business.",
        "benefit1_icon": "fa-spa",
        "benefit1_title": "Showcase Your Services",
        "benefit1_desc": "Beautiful service menus for skincare, wellness treatments, and beauty services.",
        "benefit2_icon": "fa-calendar-check",
        "benefit2_title": "Enable Online Booking",
        "benefit2_desc": "Let clients book treatments online with integrated scheduling and reminders.",
        "benefit3_icon": "fa-star",
        "benefit3_title": "Build Your Brand",
        "benefit3_desc": "Professional design that reflects your aesthetic and attracts your ideal clients.",
        "template1": "Glow", "template1_style": "Elegant & Modern",
        "template2": "Radiance", "template2_style": "Fresh & Clean",
        "template3": "Wellness", "template3_style": "Calm & Sophisticated",
        "final_cta": "Ready to Grow Your Beauty Business?",
        "final_desc": "Get your professional website live today. Start attracting more clients and building your brand online.",
        "filter": "health-beauty"
    },
    {
        "slug": "business-services",
        "name": "Business Services",
        "headline": "Win More <span>Business Clients</span> With a Professional Website",
        "subtitle": "Your business services website live in 60 minutes. Showcase your expertise, build credibility, and generate B2B leads.",
        "benefit1_icon": "fa-briefcase",
        "benefit1_title": "Showcase Your Expertise",
        "benefit1_desc": "Service pages and case studies that demonstrate your capabilities to potential clients.",
        "benefit2_icon": "fa-handshake",
        "benefit2_title": "Build B2B Credibility",
        "benefit2_desc": "Professional design with testimonials and credentials that win corporate clients.",
        "benefit3_icon": "fa-chart-line",
        "benefit3_title": "Generate Quality Leads",
        "benefit3_desc": "Contact forms and consultation booking that capture serious business inquiries.",
        "template1": "Corporate", "template1_style": "Professional & Polished",
        "template2": "Consult", "template2_style": "Modern & Trustworthy",
        "template3": "Enterprise", "template3_style": "Bold & Confident",
        "final_cta": "Ready to Grow Your Business Services?",
        "final_desc": "Get your professional website live today. Start winning more clients and building your reputation online.",
        "filter": "business-services"
    },
    {
        "slug": "insurance",
        "name": "Insurance",
        "headline": "Get More <span>Insurance Leads</span> With a Professional Website",
        "subtitle": "Your insurance agency website live in 60 minutes. Build trust, showcase your coverage options, and generate qualified leads.",
        "benefit1_icon": "fa-shield-alt",
        "benefit1_title": "Build Client Trust",
        "benefit1_desc": "Professional design with credentials and testimonials that make clients confident choosing you.",
        "benefit2_icon": "fa-list-alt",
        "benefit2_title": "Showcase Coverage Options",
        "benefit2_desc": "Clear pages for auto, home, life, business insurance that help clients find what they need.",
        "benefit3_icon": "fa-file-signature",
        "benefit3_title": "Capture Quote Requests",
        "benefit3_desc": "Quote request forms that gather the right information to qualify and convert leads.",
        "template1": "SecureLife", "template1_style": "Trustworthy & Professional",
        "template2": "Coverage Pro", "template2_style": "Modern & Clean",
        "template3": "Shield", "template3_style": "Bold & Reassuring",
        "final_cta": "Ready to Grow Your Insurance Agency?",
        "final_desc": "Get your professional website live today. Start generating more leads and building client trust online.",
        "filter": "insurance"
    },
    {
        "slug": "mortgage",
        "name": "Mortgage",
        "headline": "Close More <span>Mortgage Loans</span> With a Professional Website",
        "subtitle": "Your mortgage website live in 60 minutes. Build trust with borrowers, showcase your rates, and generate qualified applications.",
        "benefit1_icon": "fa-home",
        "benefit1_title": "Build Borrower Trust",
        "benefit1_desc": "Professional design with credentials, reviews, and clear information that wins client confidence.",
        "benefit2_icon": "fa-calculator",
        "benefit2_title": "Showcase Your Services",
        "benefit2_desc": "Pages for purchase, refinance, FHA, VA, and specialty loans that attract the right borrowers.",
        "benefit3_icon": "fa-file-alt",
        "benefit3_title": "Capture Applications",
        "benefit3_desc": "Pre-qualification forms and contact options that generate qualified mortgage leads.",
        "template1": "HomeLoan Pro", "template1_style": "Trustworthy & Professional",
        "template2": "Mortgage Plus", "template2_style": "Modern & Clean",
        "template3": "LendRight", "template3_style": "Friendly & Approachable",
        "final_cta": "Ready to Grow Your Mortgage Business?",
        "final_desc": "Get your professional website live today. Start generating more applications and closing more loans online.",
        "filter": "mortgage"
    },
    {
        "slug": "architect",
        "name": "Architect",
        "headline": "Win More <span>Architecture Projects</span> With a Stunning Portfolio Website",
        "subtitle": "Your architecture website live in 60 minutes. Showcase your designs, build your reputation, and attract dream projects.",
        "benefit1_icon": "fa-drafting-compass",
        "benefit1_title": "Showcase Your Portfolio",
        "benefit1_desc": "Beautiful project galleries with renderings and photos that demonstrate your design vision.",
        "benefit2_icon": "fa-award",
        "benefit2_title": "Build Your Reputation",
        "benefit2_desc": "Professional presentation of your credentials, awards, and design philosophy.",
        "benefit3_icon": "fa-envelope",
        "benefit3_title": "Attract Dream Projects",
        "benefit3_desc": "Contact forms that capture project inquiries from clients who appreciate your style.",
        "template1": "Blueprint", "template1_style": "Minimal & Elegant",
        "template2": "Structure", "template2_style": "Bold & Modern",
        "template3": "Design Studio", "template3_style": "Clean & Sophisticated",
        "final_cta": "Ready to Grow Your Architecture Practice?",
        "final_desc": "Get your professional website live today. Start attracting dream projects and showcasing your vision online.",
        "filter": "architect"
    },
    {
        "slug": "interior-design",
        "name": "Interior Design",
        "headline": "Attract More <span>Design Clients</span> With a Beautiful Portfolio Website",
        "subtitle": "Your interior design website live in 60 minutes. Showcase your projects, define your style, and attract ideal clients.",
        "benefit1_icon": "fa-couch",
        "benefit1_title": "Showcase Your Portfolio",
        "benefit1_desc": "Stunning project galleries that let potential clients experience your design aesthetic.",
        "benefit2_icon": "fa-palette",
        "benefit2_title": "Define Your Style",
        "benefit2_desc": "Professional presentation that communicates your unique design philosophy and approach.",
        "benefit3_icon": "fa-comments",
        "benefit3_title": "Connect With Clients",
        "benefit3_desc": "Consultation booking and contact forms that attract clients who love your style.",
        "template1": "Interiors", "template1_style": "Elegant & Refined",
        "template2": "Design Space", "template2_style": "Modern & Minimal",
        "template3": "Studio", "template3_style": "Bold & Creative",
        "final_cta": "Ready to Grow Your Interior Design Business?",
        "final_desc": "Get your professional website live today. Start attracting dream clients and showcasing your talent online.",
        "filter": "interior-design"
    },
    {
        "slug": "event",
        "name": "Event",
        "headline": "Book More <span>Events</span> With a Professional Website",
        "subtitle": "Your event planning website live in 60 minutes. Showcase your work, display your services, and attract more bookings.",
        "benefit1_icon": "fa-calendar-star",
        "benefit1_title": "Showcase Past Events",
        "benefit1_desc": "Photo galleries of weddings, corporate events, and parties that prove your expertise.",
        "benefit2_icon": "fa-list-check",
        "benefit2_title": "Display Your Services",
        "benefit2_desc": "Clear service packages for different event types and budgets that help clients choose.",
        "benefit3_icon": "fa-envelope-open-text",
        "benefit3_title": "Capture Inquiries",
        "benefit3_desc": "Event inquiry forms that gather the right details to qualify and respond to leads.",
        "template1": "Celebrate", "template1_style": "Elegant & Festive",
        "template2": "EventPro", "template2_style": "Modern & Professional",
        "template3": "Occasions", "template3_style": "Warm & Inviting",
        "final_cta": "Ready to Grow Your Event Planning Business?",
        "final_desc": "Get your professional website live today. Start booking more events and showcasing your creativity online.",
        "filter": "event"
    },
    {
        "slug": "music",
        "name": "Music",
        "headline": "Get More <span>Gigs & Fans</span> With a Professional Website",
        "subtitle": "Your music website live in 60 minutes. Showcase your sound, share your story, and connect with fans and venues.",
        "benefit1_icon": "fa-music",
        "benefit1_title": "Showcase Your Music",
        "benefit1_desc": "Embed your tracks, videos, and streaming links so visitors can experience your sound.",
        "benefit2_icon": "fa-calendar-alt",
        "benefit2_title": "Promote Your Shows",
        "benefit2_desc": "Event calendars and tour dates that keep fans informed and drive ticket sales.",
        "benefit3_icon": "fa-envelope",
        "benefit3_title": "Get Booked",
        "benefit3_desc": "Booking inquiry forms and press kits that make it easy for venues to hire you.",
        "template1": "Amplify", "template1_style": "Bold & Energetic",
        "template2": "Soundwave", "template2_style": "Modern & Dark",
        "template3": "Melody", "template3_style": "Clean & Artistic",
        "final_cta": "Ready to Grow Your Music Career?",
        "final_desc": "Get your professional website live today. Start getting more gigs and building your fanbase online.",
        "filter": "music"
    },
    {
        "slug": "single-page",
        "name": "Single Page",
        "headline": "Launch Your <span>Single Page Website</span> in 60 Minutes",
        "subtitle": "A focused, conversion-optimized single page website. Perfect for landing pages, portfolios, and simple business sites.",
        "benefit1_icon": "fa-bullseye",
        "benefit1_title": "Focused & Effective",
        "benefit1_desc": "One page that tells your story and drives visitors to take action without distractions.",
        "benefit2_icon": "fa-mobile-alt",
        "benefit2_title": "Mobile-Perfect",
        "benefit2_desc": "Smooth scrolling experience that works beautifully on phones, tablets, and desktops.",
        "benefit3_icon": "fa-rocket",
        "benefit3_title": "Fast to Launch",
        "benefit3_desc": "Get online quickly with a streamlined site that covers all the essentials.",
        "template1": "OnePage", "template1_style": "Clean & Modern",
        "template2": "Scroll", "template2_style": "Bold & Dynamic",
        "template3": "Focus", "template3_style": "Minimal & Elegant",
        "final_cta": "Ready to Launch Your Single Page Website?",
        "final_desc": "Get your professional website live today. Simple, focused, and effective.",
        "filter": "single-page"
    },
    {
        "slug": "landing-page",
        "name": "Landing Page",
        "headline": "Convert More <span>Visitors</span> With a High-Converting Landing Page",
        "subtitle": "Your landing page live in 60 minutes. Optimized for conversions, perfect for ads, campaigns, and lead generation.",
        "benefit1_icon": "fa-bullseye",
        "benefit1_title": "Conversion-Optimized",
        "benefit1_desc": "Designed with one goal in mind: turning visitors into leads or customers.",
        "benefit2_icon": "fa-ad",
        "benefit2_title": "Perfect for Ads",
        "benefit2_desc": "Focused messaging that matches your ad campaigns and maximizes your ad spend ROI.",
        "benefit3_icon": "fa-chart-line",
        "benefit3_title": "Track Results",
        "benefit3_desc": "Built for easy tracking and optimization so you can measure what's working.",
        "template1": "Convert", "template1_style": "Clean & Focused",
        "template2": "Launch", "template2_style": "Bold & Action-Driven",
        "template3": "Capture", "template3_style": "Modern & Minimal",
        "final_cta": "Ready to Launch Your Landing Page?",
        "final_desc": "Get your high-converting landing page live today. Start turning more visitors into customers.",
        "filter": "landing-page"
    },
    {
        "slug": "online-store",
        "name": "Online Store",
        "headline": "Start Selling <span>Online</span> With a Professional Store",
        "subtitle": "Your online store live in 60 minutes. Showcase your products, accept payments, and start selling to customers everywhere.",
        "benefit1_icon": "fa-shopping-cart",
        "benefit1_title": "Sell Your Products",
        "benefit1_desc": "Beautiful product pages with photos, descriptions, and easy checkout that drive sales.",
        "benefit2_icon": "fa-credit-card",
        "benefit2_title": "Accept Payments",
        "benefit2_desc": "Secure payment processing that lets customers pay with cards, PayPal, and more.",
        "benefit3_icon": "fa-truck",
        "benefit3_title": "Manage Orders",
        "benefit3_desc": "Order management and shipping integration that keeps your business running smoothly.",
        "template1": "ShopPro", "template1_style": "Clean & Professional",
        "template2": "Storefront", "template2_style": "Modern & Minimal",
        "template3": "Market", "template3_style": "Bold & Inviting",
        "final_cta": "Ready to Start Selling Online?",
        "final_desc": "Get your online store live today. Start reaching customers and growing your sales.",
        "filter": "online-store"
    }
]

# Read the plumber template
script_dir = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(script_dir, 'plumber.html'), 'r') as f:
    template = f.read()

def generate_landing_page(vertical):
    """Generate a landing page for a vertical from the plumber template."""
    content = template
    
    # Replace meta description
    content = re.sub(
        r'<meta name="description" content="[^"]*">',
        f'<meta name="description" content="Get a professional {vertical["name"].lower()} website live in 60 minutes. {vertical["subtitle"][:100]}...">',
        content
    )
    
    # Replace title
    content = re.sub(
        r'<title>[^<]*</title>',
        f'<title>Professional {vertical["name"]} Websites | Live in 60 Minutes | 60 Minute Sites</title>',
        content
    )
    
    # Replace hero headline
    content = re.sub(
        r'<h1>Get More <span>Plumbing Calls</span> With a Professional Website</h1>',
        f'<h1>{vertical["headline"]}</h1>',
        content
    )
    
    # Replace hero subtitle
    content = re.sub(
        r'<p class="subtitle">Your plumbing website live in 60 minutes\. Capture emergency calls 24/7, build trust with homeowners, and grow your business online\.</p>',
        f'<p class="subtitle">{vertical["subtitle"]}</p>',
        content
    )
    
    # Replace video section copy
    content = re.sub(
        r'your plumbing business',
        f'your {vertical["name"].lower()} business',
        content
    )
    content = re.sub(
        r'20\+ plumber-specific templates',
        f'20+ {vertical["name"].lower()}-specific templates',
        content
    )
    content = re.sub(
        r'Live and ready to capture leads',
        f'Live and ready to attract clients',
        content
    )
    
    # Replace benefits section title
    content = re.sub(
        r'Why Plumbers Choose 60 Minute Sites',
        f'Why {vertical["name"]} Businesses Choose 60 Minute Sites',
        content
    )
    
    # Replace benefit cards
    content = re.sub(
        r'<div class="benefit-icon"><i class="fas fa-phone-volume"></i></div>\s*<h3>Capture Emergency Calls</h3>\s*<p>Click-to-call buttons and prominent phone numbers mean customers can reach you instantly, day or night\.</p>',
        f'<div class="benefit-icon"><i class="fas {vertical["benefit1_icon"]}"></i></div>\n          <h3>{vertical["benefit1_title"]}</h3>\n          <p>{vertical["benefit1_desc"]}</p>',
        content
    )
    content = re.sub(
        r'<div class="benefit-icon"><i class="fas fa-map-marker-alt"></i></div>\s*<h3>Rank in Local Search</h3>\s*<p>SEO-optimized templates help you show up when homeowners search "plumber near me" in your service area\.</p>',
        f'<div class="benefit-icon"><i class="fas {vertical["benefit2_icon"]}"></i></div>\n          <h3>{vertical["benefit2_title"]}</h3>\n          <p>{vertical["benefit2_desc"]}</p>',
        content
    )
    content = re.sub(
        r'<div class="benefit-icon"><i class="fas fa-star"></i></div>\s*<h3>Build Instant Trust</h3>\s*<p>Professional design, service pages, and review integration make customers confident in choosing you\.</p>',
        f'<div class="benefit-icon"><i class="fas {vertical["benefit3_icon"]}"></i></div>\n          <h3>{vertical["benefit3_title"]}</h3>\n          <p>{vertical["benefit3_desc"]}</p>',
        content
    )
    
    # Replace templates section
    content = re.sub(r'Plumber Website Templates', f'{vertical["name"]} Website Templates', content)
    content = re.sub(
        r'Professional designs built specifically for plumbing companies\.',
        f'Professional designs built specifically for {vertical["name"].lower()} businesses.',
        content
    )
    
    # Replace template cards
    content = re.sub(r'filter=plumber', f'filter={vertical["filter"]}', content)
    content = re.sub(r'plumber-flow-masters', f'{vertical["slug"]}-template1', content)
    content = re.sub(r'plumber-pipe-pros', f'{vertical["slug"]}-template2', content)
    content = re.sub(r'plumber-drain-experts', f'{vertical["slug"]}-template3', content)
    content = re.sub(r'Flow Masters Plumber Template', f'{vertical["template1"]} {vertical["name"]} Template', content)
    content = re.sub(r'Pipe Pros Plumber Template', f'{vertical["template2"]} {vertical["name"]} Template', content)
    content = re.sub(r'Drain Experts Plumber Template', f'{vertical["template3"]} {vertical["name"]} Template', content)
    content = re.sub(r'<h4>Flow Masters</h4>', f'<h4>{vertical["template1"]}</h4>', content)
    content = re.sub(r'<h4>Pipe Pros</h4>', f'<h4>{vertical["template2"]}</h4>', content)
    content = re.sub(r'<h4>Drain Experts</h4>', f'<h4>{vertical["template3"]}</h4>', content)
    content = re.sub(r'<span>Modern & Professional</span>', f'<span>{vertical["template1_style"]}</span>', content)
    content = re.sub(r'<span>Bold & Trustworthy</span>', f'<span>{vertical["template2_style"]}</span>', content)
    content = re.sub(r'<span>Clean & Conversion-Focused</span>', f'<span>{vertical["template3_style"]}</span>', content)
    content = re.sub(r'View All Plumber Templates', f'View All {vertical["name"]} Templates', content)
    
    # Replace pricing section
    content = re.sub(r'Professional plumber template', f'Professional {vertical["name"].lower()} template', content)
    content = re.sub(r'Click-to-call functionality', f'Industry-specific features', content)
    
    # Replace final CTA
    content = re.sub(r'Ready to Grow Your Plumbing Business\?', vertical["final_cta"], content)
    content = re.sub(
        r'Get your professional website live today\. Start capturing more calls and building trust with customers online\.',
        vertical["final_desc"],
        content
    )
    
    # Replace sticky CTA
    content = re.sub(r'Plumber websites from', f'{vertical["name"]} websites from', content)
    
    return content

# Generate all landing pages
for vertical in VERTICALS:
    content = generate_landing_page(vertical)
    output_path = os.path.join(script_dir, f'{vertical["slug"]}.html')
    with open(output_path, 'w') as f:
        f.write(content)
    print(f'Created: {vertical["slug"]}.html')

print(f'\nGenerated {len(VERTICALS)} landing pages!')
