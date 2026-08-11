#!/bin/bash

# Template Generator for 60minutesites.com
# Generates 20 templates per category with unique styles

BASE_DIR="/Users/corbandamukaitis/Desktop/Personal Projects/60minutesites.com/templates"

# Color palettes for 20 styles
declare -A STYLES
STYLES[1]="Modern Minimal|#1A1A1A|#FFFFFF|#FF6B35|#F5F5F5"
STYLES[2]="Bold & Dark|#0D0D0D|#1A1A1A|#FF4444|#121212"
STYLES[3]="Classic Professional|#1E3A5F|#2C5282|#C9A227|#FFFFFF"
STYLES[4]="Vibrant & Colorful|#FF6B6B|#4ECDC4|#FFE66D|#FFFFFF"
STYLES[5]="Elegant & Luxurious|#2C2C2C|#B8860B|#D4AF37|#1A1A1A"
STYLES[6]="Rustic & Warm|#8B4513|#D2691E|#F4A460|#FFF8DC"
STYLES[7]="Tech & Futuristic|#0A192F|#64FFDA|#00D9FF|#0A192F"
STYLES[8]="Clean & Corporate|#2563EB|#1E40AF|#3B82F6|#F8FAFC"
STYLES[9]="Playful & Fun|#FF6B9D|#C44DFF|#FFD93D|#FFF5F5"
STYLES[10]="Sophisticated & Sleek|#18181B|#27272A|#A78BFA|#09090B"
STYLES[11]="Natural & Organic|#2D5016|#4A7C23|#84CC16|#F7FEE7"
STYLES[12]="Urban & Industrial|#374151|#4B5563|#F59E0B|#1F2937"
STYLES[13]="Vintage & Retro|#B45309|#92400E|#FCD34D|#FFFBEB"
STYLES[14]="Fresh & Bright|#0EA5E9|#06B6D4|#22D3EE|#F0F9FF"
STYLES[15]="Calm & Serene|#5B8C85|#7FB3AC|#A7D7C5|#F5FFFA"
STYLES[16]="Dynamic & Energetic|#DC2626|#EF4444|#FCA5A5|#FEF2F2"
STYLES[17]="Premium & Exclusive|#1C1917|#292524|#A3A3A3|#0C0A09"
STYLES[18]="Friendly & Approachable|#059669|#10B981|#34D399|#ECFDF5"
STYLES[19]="Sharp & Geometric|#4F46E5|#6366F1|#818CF8|#EEF2FF"
STYLES[20]="Soft & Rounded|#EC4899|#F472B6|#FBCFE8|#FDF2F8"

generate_template() {
    local category=$1
    local template_num=$2
    local template_name=$3
    local industry_title=$4
    local industry_desc=$5
    local services=$6

    local style_data="${STYLES[$template_num]}"
    IFS='|' read -r style_name primary secondary accent background <<< "$style_data"

    local template_dir="$BASE_DIR/$category/$template_num-$template_name"
    mkdir -p "$template_dir/assets"

    # Determine text color based on background
    local text_color="#333333"
    local text_light="#666666"
    if [[ "$background" == "#0"* ]] || [[ "$background" == "#1"* ]] || [[ "$background" == "#2"* ]]; then
        text_color="#FFFFFF"
        text_light="#CCCCCC"
    fi

    # Format template name for display
    local display_name=$(echo "$template_name" | sed 's/-/ /g' | sed 's/\b\(.\)/\u\1/g')

    # Generate index.html
    cat > "$template_dir/index.html" << HTMLEOF
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="$display_name - Professional $industry_title services. $industry_desc">
    <meta name="keywords" content="$industry_title, $category, professional services, local business">
    <meta name="author" content="60 Minute Sites">
    <meta property="og:title" content="$display_name | Professional $industry_title">
    <meta property="og:description" content="$industry_desc">
    <meta property="og:type" content="website">
    <title>$display_name | Professional $industry_title</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <header class="header">
        <nav class="nav">
            <a href="#" class="logo">$display_name</a>
            <ul class="nav-links">
                <li><a href="#services">Services</a></li>
                <li><a href="#about">About</a></li>
                <li><a href="#contact">Contact</a></li>
                <li><a href="tel:817-403-2179" class="nav-cta">Call Now</a></li>
            </ul>
            <button class="mobile-menu-btn" aria-label="Toggle menu">
                <span></span>
                <span></span>
                <span></span>
            </button>
        </nav>
    </header>

    <section class="hero">
        <div class="hero-content">
            <h1>$display_name</h1>
            <p>$industry_desc</p>
            <div class="hero-buttons">
                <a href="#contact" class="btn btn-primary">Get Free Quote</a>
                <a href="https://calendly.com/corban-leadsprinter/new-meeting" target="_blank" class="btn btn-secondary">Book Consultation</a>
            </div>
        </div>
    </section>

    <section id="services" class="services">
        <div class="container">
            <h2>Our Services</h2>
            <div class="services-grid">
                $services
            </div>
        </div>
    </section>

    <section id="about" class="about">
        <div class="container">
            <div class="about-content">
                <h2>About Us</h2>
                <p>We are dedicated $industry_title professionals committed to delivering exceptional results. With years of experience and a passion for quality, we ensure every project exceeds expectations.</p>
                <p>Our team brings expertise, reliability, and attention to detail to every job. We pride ourselves on transparent communication, fair pricing, and customer satisfaction.</p>
                <ul class="about-features">
                    <li>Licensed & Insured</li>
                    <li>Free Estimates</li>
                    <li>Quality Guaranteed</li>
                    <li>24/7 Support Available</li>
                </ul>
            </div>
        </div>
    </section>

    <section id="contact" class="contact">
        <div class="container">
            <h2>Contact Us</h2>
            <div class="contact-wrapper">
                <div class="contact-info">
                    <h3>Get In Touch</h3>
                    <p><strong>Phone:</strong> <a href="tel:817-403-2179">817-403-2179</a></p>
                    <p><strong>Email:</strong> <a href="mailto:info@example.com">info@example.com</a></p>
                    <p><strong>Hours:</strong> Mon-Fri 8am-6pm</p>
                    <a href="https://calendly.com/corban-leadsprinter/new-meeting" target="_blank" class="btn btn-primary">Schedule a Call</a>
                </div>
                <form action="https://formspree.io/f/xojeqvng" method="POST" class="contact-form">
                    <input type="text" name="name" placeholder="Your Name" required>
                    <input type="email" name="email" placeholder="Your Email" required>
                    <input type="tel" name="phone" placeholder="Your Phone">
                    <textarea name="message" placeholder="Tell us about your project" required></textarea>
                    <button type="submit" class="btn btn-primary">Send Message</button>
                </form>
            </div>
        </div>
    </section>

    <footer class="footer">
        <div class="container">
            <p>&copy; 2024 $display_name. All rights reserved.</p>
            <p>Website by <a href="https://60minutesites.com" target="_blank">60 Minute Sites</a></p>
        </div>
    </footer>

    <script src="script.js"></script>
</body>
</html>
HTMLEOF

    # Generate styles.css
    cat > "$template_dir/styles.css" << CSSEOF
/* $display_name - $style_name Style */
/* Template by 60 Minute Sites */

:root {
    --primary: $primary;
    --secondary: $secondary;
    --accent: $accent;
    --background: $background;
    --text: $text_color;
    --text-light: $text_light;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

html {
    scroll-behavior: smooth;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
    background: var(--background);
    color: var(--text);
    line-height: 1.6;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 20px;
}

/* Header & Navigation */
.header {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    background: var(--primary);
    padding: 1rem 2rem;
    z-index: 1000;
    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
}

.nav {
    display: flex;
    justify-content: space-between;
    align-items: center;
    max-width: 1200px;
    margin: 0 auto;
}

.logo {
    font-size: 1.5rem;
    font-weight: 700;
    color: var(--accent);
    text-decoration: none;
}

.nav-links {
    display: flex;
    list-style: none;
    gap: 2rem;
    align-items: center;
}

.nav-links a {
    color: #fff;
    text-decoration: none;
    font-weight: 500;
    transition: color 0.3s;
}

.nav-links a:hover {
    color: var(--accent);
}

.nav-cta {
    background: var(--accent);
    padding: 0.5rem 1.5rem;
    border-radius: 5px;
    color: var(--primary) !important;
}

.mobile-menu-btn {
    display: none;
    flex-direction: column;
    gap: 5px;
    background: none;
    border: none;
    cursor: pointer;
}

.mobile-menu-btn span {
    width: 25px;
    height: 3px;
    background: #fff;
    transition: 0.3s;
}

/* Hero Section */
.hero {
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 100px 20px 60px;
    background: linear-gradient(135deg, var(--primary), var(--secondary));
    color: #fff;
}

.hero-content h1 {
    font-size: clamp(2.5rem, 5vw, 4rem);
    margin-bottom: 1rem;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
}

.hero-content p {
    font-size: 1.25rem;
    max-width: 600px;
    margin: 0 auto 2rem;
    opacity: 0.9;
}

.hero-buttons {
    display: flex;
    gap: 1rem;
    justify-content: center;
    flex-wrap: wrap;
}

/* Buttons */
.btn {
    display: inline-block;
    padding: 1rem 2rem;
    border-radius: 5px;
    text-decoration: none;
    font-weight: 600;
    transition: transform 0.3s, box-shadow 0.3s;
    cursor: pointer;
    border: none;
    font-size: 1rem;
}

.btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 5px 20px rgba(0,0,0,0.2);
}

.btn-primary {
    background: var(--accent);
    color: var(--primary);
}

.btn-secondary {
    background: transparent;
    color: #fff;
    border: 2px solid #fff;
}

.btn-secondary:hover {
    background: #fff;
    color: var(--primary);
}

/* Services Section */
.services {
    padding: 100px 0;
    background: var(--background);
}

.services h2 {
    text-align: center;
    font-size: 2.5rem;
    margin-bottom: 3rem;
    color: var(--primary);
}

.services-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 2rem;
}

.service-card {
    background: #fff;
    padding: 2rem;
    border-radius: 10px;
    box-shadow: 0 5px 20px rgba(0,0,0,0.1);
    text-align: center;
    transition: transform 0.3s;
}

.service-card:hover {
    transform: translateY(-5px);
}

.service-card h3 {
    color: var(--primary);
    margin-bottom: 1rem;
    font-size: 1.25rem;
}

.service-card p {
    color: var(--text-light);
}

.service-icon {
    font-size: 3rem;
    margin-bottom: 1rem;
}

/* About Section */
.about {
    padding: 100px 0;
    background: var(--primary);
    color: #fff;
}

.about h2 {
    font-size: 2.5rem;
    margin-bottom: 2rem;
}

.about p {
    max-width: 800px;
    margin-bottom: 1.5rem;
    opacity: 0.9;
}

.about-features {
    list-style: none;
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-top: 2rem;
}

.about-features li {
    padding: 1rem;
    background: rgba(255,255,255,0.1);
    border-radius: 5px;
    text-align: center;
}

.about-features li::before {
    content: "✓ ";
    color: var(--accent);
    font-weight: bold;
}

/* Contact Section */
.contact {
    padding: 100px 0;
    background: var(--background);
}

.contact h2 {
    text-align: center;
    font-size: 2.5rem;
    margin-bottom: 3rem;
    color: var(--primary);
}

.contact-wrapper {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4rem;
    align-items: start;
}

.contact-info h3 {
    color: var(--primary);
    margin-bottom: 1.5rem;
}

.contact-info p {
    margin-bottom: 1rem;
}

.contact-info a {
    color: var(--accent);
    text-decoration: none;
}

.contact-form {
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.contact-form input,
.contact-form textarea {
    padding: 1rem;
    border: 2px solid #e5e5e5;
    border-radius: 5px;
    font-size: 1rem;
    font-family: inherit;
    transition: border-color 0.3s;
}

.contact-form input:focus,
.contact-form textarea:focus {
    outline: none;
    border-color: var(--accent);
}

.contact-form textarea {
    min-height: 150px;
    resize: vertical;
}

/* Footer */
.footer {
    background: var(--primary);
    color: #fff;
    padding: 2rem;
    text-align: center;
}

.footer a {
    color: var(--accent);
    text-decoration: none;
}

/* Mobile Responsive */
@media (max-width: 768px) {
    .nav-links {
        display: none;
        position: absolute;
        top: 100%;
        left: 0;
        right: 0;
        background: var(--primary);
        flex-direction: column;
        padding: 2rem;
        gap: 1rem;
    }

    .nav-links.active {
        display: flex;
    }

    .mobile-menu-btn {
        display: flex;
    }

    .contact-wrapper {
        grid-template-columns: 1fr;
        gap: 2rem;
    }

    .hero-content h1 {
        font-size: 2rem;
    }
}
CSSEOF

    # Generate script.js
    cat > "$template_dir/script.js" << JSEOF
// $display_name - Template JavaScript
// Template by 60 Minute Sites

document.addEventListener('DOMContentLoaded', function() {
    // Mobile menu toggle
    const mobileMenuBtn = document.querySelector('.mobile-menu-btn');
    const navLinks = document.querySelector('.nav-links');

    if (mobileMenuBtn) {
        mobileMenuBtn.addEventListener('click', function() {
            navLinks.classList.toggle('active');
            this.classList.toggle('active');
        });
    }

    // Smooth scroll for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
                // Close mobile menu if open
                navLinks.classList.remove('active');
            }
        });
    });

    // Form submission handling
    const form = document.querySelector('.contact-form');
    if (form) {
        form.addEventListener('submit', function(e) {
            const btn = form.querySelector('button[type="submit"]');
            btn.textContent = 'Sending...';
            btn.disabled = true;
        });
    }

    // Header scroll effect
    const header = document.querySelector('.header');
    window.addEventListener('scroll', function() {
        if (window.scrollY > 100) {
            header.style.background = 'rgba(0,0,0,0.95)';
        } else {
            header.style.background = '';
        }
    });
});
JSEOF

    echo "Created: $category/$template_num-$template_name"
}

# Export function for use in category scripts
export -f generate_template
export STYLES
export BASE_DIR

echo "Template generator loaded. Run category-specific scripts to generate templates."
