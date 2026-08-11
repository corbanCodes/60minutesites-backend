# 60 Minute Sites - UI/UX Update PRD

## Overview
Comprehensive update to improve the design, user experience, and conversion optimization of 60minutesites.com.

---

## 1. Pricing Changes

### Remove Setup Fee - Make it FREE
- **Old**: $100 one-time setup + $50/month
- **New**: FREE setup + $50/month

### Update pricing messaging across all pages:
- index.html (pricing preview section)
- pricing.html (main pricing cards)
- Solution card in problem/solution section

### Add Value Proposition List
Add a compelling list of why this is the best deal:
- FREE professional website setup (normally $100+)
- 560+ premium templates to choose from
- 1-hour personalized onboarding call included
- Full template customization at no extra cost
- Domain connection assistance
- Mobile-responsive design guaranteed
- SEO basics configured
- Contact forms set up and ready
- Launch support included
- No long-term contracts
- Cancel anytime
- 100% satisfaction guarantee
- All hosting included in $50/mo
- SSL certificate included
- Monthly maintenance & security updates
- Email support included

---

## 2. Navigation Updates

### Modernize Logo/Brand
- Update "60MinuteSites" to a more modern look
- Use gradient or icon-based approach
- Consider adding a small icon (lightning bolt or clock)

### Update CTA Button
- Change "Get Started Free" to "Book a Demo" (Calendly link)
- Add "Get Started" button linking to Stripe payment

### Pages to update:
- index.html
- gallery.html
- pricing.html
- about.html
- contact.html

---

## 3. Payment Integration

### Add Stripe Payment Button
- Payment link: https://buy.stripe.com/6oUdR96wG9ID1MwcuOeAg03
- Add alongside "Book a Demo" button
- Label: "Get Started" or "Start Now"

---

## 4. Footer Updates

### Remove Social Media Icons
- Remove Facebook, Instagram, LinkedIn links

### Add All Industries
Display all 28 industries in a clean grid layout:
- Construction
- Plumber
- Electrician
- Painter
- HVAC
- Cleaning
- Pest Control
- Salon
- Spa
- Barber
- Massage
- Health & Beauty
- Fitness
- Business Services
- Real Estate
- Insurance
- Mortgage
- Architect
- Interior Design
- Restaurant
- Automotive
- Event
- Photography
- Music
- Single Page
- Landing Page
- Online Store
- Full Website

---

## 5. Template Page Announcement Bar

### Add Dismissible Green Banner
- Position: Fixed at top of template pages
- Color: Green (#22c55e)
- Dismissible: X button to close
- Persist: Use localStorage to remember dismissal
- Content options:
  - "Schedule a free consultation"
  - "Click here to check-out"
- Links: Calendly for consultation, Stripe for checkout

---

## 6. UI/Design Improvements

### Button Styling Fixes
- Ensure consistent button sizes and spacing
- Fix alignment issues in pricing section
- Improve button hover states

### Overall Modern Design Updates
- Improve card shadows and hover effects
- Better spacing and visual hierarchy
- More refined typography
- Subtle animations and transitions

---

## 7. SEO Optimization

### Meta Tags
- Update descriptions to be more compelling
- Add relevant keywords
- Improve Open Graph tags

### Structured Data
- Add JSON-LD for local business
- Add FAQ schema where applicable

### Technical SEO
- Ensure proper heading hierarchy
- Add alt text to images
- Improve internal linking

---

## Implementation Order

1. CSS updates for modern design
2. Navbar/logo modernization
3. Pricing section overhaul
4. Button text changes across all pages
5. Footer updates
6. Announcement bar for templates
7. SEO improvements

---

## Files to Modify

### Main Site
- css/main.css
- index.html
- gallery.html
- pricing.html
- about.html
- contact.html

### Templates (560 files)
- All template index.html files need announcement bar
