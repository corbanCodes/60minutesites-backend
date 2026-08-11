#!/bin/bash

# 60 Minute Sites - Complete Template Generator
# Generates all 560 templates across 28 categories

BASE_DIR="/Users/corbandamukaitis/Desktop/Personal Projects/60minutesites.com/templates"

# Color palettes for 20 styles (style_name|primary|secondary|accent|background)
declare -a STYLES=(
    "Modern Minimal|#1A1A1A|#FFFFFF|#FF6B35|#F5F5F5"
    "Bold & Dark|#0D0D0D|#1A1A1A|#FF4444|#121212"
    "Classic Professional|#1E3A5F|#2C5282|#C9A227|#FFFFFF"
    "Vibrant & Colorful|#FF6B6B|#4ECDC4|#FFE66D|#FFFFFF"
    "Elegant & Luxurious|#2C2C2C|#B8860B|#D4AF37|#1A1A1A"
    "Rustic & Warm|#8B4513|#D2691E|#F4A460|#FFF8DC"
    "Tech & Futuristic|#0A192F|#64FFDA|#00D9FF|#0A192F"
    "Clean & Corporate|#2563EB|#1E40AF|#3B82F6|#F8FAFC"
    "Playful & Fun|#FF6B9D|#C44DFF|#FFD93D|#FFF5F5"
    "Sophisticated & Sleek|#18181B|#27272A|#A78BFA|#09090B"
    "Natural & Organic|#2D5016|#4A7C23|#84CC16|#F7FEE7"
    "Urban & Industrial|#374151|#4B5563|#F59E0B|#1F2937"
    "Vintage & Retro|#B45309|#92400E|#FCD34D|#FFFBEB"
    "Fresh & Bright|#0EA5E9|#06B6D4|#22D3EE|#F0F9FF"
    "Calm & Serene|#5B8C85|#7FB3AC|#A7D7C5|#F5FFFA"
    "Dynamic & Energetic|#DC2626|#EF4444|#FCA5A5|#FEF2F2"
    "Premium & Exclusive|#1C1917|#292524|#A3A3A3|#0C0A09"
    "Friendly & Approachable|#059669|#10B981|#34D399|#ECFDF5"
    "Sharp & Geometric|#4F46E5|#6366F1|#818CF8|#EEF2FF"
    "Soft & Rounded|#EC4899|#F472B6|#FBCFE8|#FDF2F8"
)

# Function to generate a single template
generate_template() {
    local category=$1
    local num=$2
    local name=$3
    local industry=$4
    local tagline=$5
    local services_html=$6

    local padded_num=$(printf "%02d" $num)
    local template_dir="$BASE_DIR/$category/$padded_num-$name"

    # Get style based on template number (1-20)
    local style_index=$((num - 1))
    IFS='|' read -r style_name primary secondary accent background <<< "${STYLES[$style_index]}"

    # Determine text colors based on background darkness
    local text_color="#333333"
    local text_light="#666666"
    local hero_text="#FFFFFF"
    case "$background" in
        "#0"*|"#1"*|"#2"*) text_color="#FFFFFF"; text_light="#CCCCCC" ;;
    esac

    # Create display name from slug
    local display_name=$(echo "$name" | sed 's/-/ /g' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2));}1')

    mkdir -p "$template_dir/assets"

    # Generate index.html
    cat > "$template_dir/index.html" << HTMLEOF
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="$display_name - Professional $industry services. $tagline">
    <meta name="keywords" content="$industry, $category, professional services, local business">
    <meta name="author" content="60 Minute Sites">
    <meta property="og:title" content="$display_name | Professional $industry">
    <meta property="og:description" content="$tagline">
    <meta property="og:type" content="website">
    <title>$display_name | Professional $industry</title>
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
                <span></span><span></span><span></span>
            </button>
        </nav>
    </header>

    <section class="hero">
        <div class="hero-content">
            <h1>$display_name</h1>
            <p>$tagline</p>
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
$services_html
            </div>
        </div>
    </section>

    <section id="about" class="about">
        <div class="container">
            <div class="about-content">
                <h2>About Us</h2>
                <p>We are dedicated $industry professionals committed to delivering exceptional results. With years of experience and a passion for quality, we ensure every project exceeds expectations.</p>
                <p>Our team brings expertise, reliability, and attention to detail to every job. We pride ourselves on transparent communication, fair pricing, and customer satisfaction.</p>
                <ul class="about-features">
                    <li>Licensed & Insured</li>
                    <li>Free Estimates</li>
                    <li>Quality Guaranteed</li>
                    <li>24/7 Support</li>
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
:root{--primary:$primary;--secondary:$secondary;--accent:$accent;--bg:$background;--text:$text_color;--text-light:$text_light}
*{margin:0;padding:0;box-sizing:border-box}
html{scroll-behavior:smooth}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.6}
.container{max-width:1200px;margin:0 auto;padding:0 20px}
.header{position:fixed;top:0;left:0;right:0;background:var(--primary);padding:1rem 2rem;z-index:1000;box-shadow:0 2px 10px rgba(0,0,0,0.1)}
.nav{display:flex;justify-content:space-between;align-items:center;max-width:1200px;margin:0 auto}
.logo{font-size:1.5rem;font-weight:700;color:var(--accent);text-decoration:none}
.nav-links{display:flex;list-style:none;gap:2rem;align-items:center}
.nav-links a{color:#fff;text-decoration:none;font-weight:500;transition:color .3s}
.nav-links a:hover{color:var(--accent)}
.nav-cta{background:var(--accent);padding:.5rem 1.5rem;border-radius:5px;color:var(--primary)!important}
.mobile-menu-btn{display:none;flex-direction:column;gap:5px;background:none;border:none;cursor:pointer}
.mobile-menu-btn span{width:25px;height:3px;background:#fff;transition:.3s}
.hero{min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center;padding:100px 20px 60px;background:linear-gradient(135deg,var(--primary),var(--secondary));color:#fff}
.hero-content h1{font-size:clamp(2.5rem,5vw,4rem);margin-bottom:1rem;text-shadow:2px 2px 4px rgba(0,0,0,0.2)}
.hero-content p{font-size:1.25rem;max-width:600px;margin:0 auto 2rem;opacity:.9}
.hero-buttons{display:flex;gap:1rem;justify-content:center;flex-wrap:wrap}
.btn{display:inline-block;padding:1rem 2rem;border-radius:5px;text-decoration:none;font-weight:600;transition:transform .3s,box-shadow .3s;cursor:pointer;border:none;font-size:1rem}
.btn:hover{transform:translateY(-2px);box-shadow:0 5px 20px rgba(0,0,0,0.2)}
.btn-primary{background:var(--accent);color:var(--primary)}
.btn-secondary{background:transparent;color:#fff;border:2px solid #fff}
.btn-secondary:hover{background:#fff;color:var(--primary)}
.services{padding:100px 0;background:var(--bg)}
.services h2{text-align:center;font-size:2.5rem;margin-bottom:3rem;color:var(--primary)}
.services-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:2rem}
.service-card{background:#fff;padding:2rem;border-radius:10px;box-shadow:0 5px 20px rgba(0,0,0,0.1);text-align:center;transition:transform .3s}
.service-card:hover{transform:translateY(-5px)}
.service-card h3{color:var(--primary);margin-bottom:1rem;font-size:1.25rem}
.service-card p{color:#666}
.service-icon{font-size:3rem;margin-bottom:1rem}
.about{padding:100px 0;background:var(--primary);color:#fff}
.about h2{font-size:2.5rem;margin-bottom:2rem}
.about p{max-width:800px;margin-bottom:1.5rem;opacity:.9}
.about-features{list-style:none;display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-top:2rem}
.about-features li{padding:1rem;background:rgba(255,255,255,0.1);border-radius:5px;text-align:center}
.about-features li::before{content:"✓ ";color:var(--accent);font-weight:bold}
.contact{padding:100px 0;background:var(--bg)}
.contact h2{text-align:center;font-size:2.5rem;margin-bottom:3rem;color:var(--primary)}
.contact-wrapper{display:grid;grid-template-columns:1fr 1fr;gap:4rem;align-items:start}
.contact-info h3{color:var(--primary);margin-bottom:1.5rem}
.contact-info p{margin-bottom:1rem}
.contact-info a{color:var(--accent);text-decoration:none}
.contact-form{display:flex;flex-direction:column;gap:1rem}
.contact-form input,.contact-form textarea{padding:1rem;border:2px solid #e5e5e5;border-radius:5px;font-size:1rem;font-family:inherit;transition:border-color .3s}
.contact-form input:focus,.contact-form textarea:focus{outline:none;border-color:var(--accent)}
.contact-form textarea{min-height:150px;resize:vertical}
.footer{background:var(--primary);color:#fff;padding:2rem;text-align:center}
.footer a{color:var(--accent);text-decoration:none}
@media(max-width:768px){.nav-links{display:none;position:absolute;top:100%;left:0;right:0;background:var(--primary);flex-direction:column;padding:2rem;gap:1rem}.nav-links.active{display:flex}.mobile-menu-btn{display:flex}.contact-wrapper{grid-template-columns:1fr;gap:2rem}.hero-content h1{font-size:2rem}}
CSSEOF

    # Generate script.js
    cat > "$template_dir/script.js" << 'JSEOF'
document.addEventListener('DOMContentLoaded',function(){const m=document.querySelector('.mobile-menu-btn'),n=document.querySelector('.nav-links');m&&m.addEventListener('click',function(){n.classList.toggle('active');this.classList.toggle('active')});document.querySelectorAll('a[href^="#"]').forEach(a=>{a.addEventListener('click',function(e){e.preventDefault();const t=document.querySelector(this.getAttribute('href'));t&&(t.scrollIntoView({behavior:'smooth',block:'start'}),n.classList.remove('active'))})});const f=document.querySelector('.contact-form');f&&f.addEventListener('submit',function(){const b=f.querySelector('button[type="submit"]');b.textContent='Sending...';b.disabled=true});const h=document.querySelector('.header');window.addEventListener('scroll',function(){h.style.background=window.scrollY>100?'rgba(0,0,0,0.95)':''})});
JSEOF

    echo "  Created: $padded_num-$name"
}

# ============================================
# CONSTRUCTION TEMPLATES
# ============================================
generate_construction() {
    echo "Generating Construction templates..."
    local industry="Construction"
    local tagline="Building dreams, one project at a time. Quality construction services you can trust."
    local services='                <div class="service-card"><div class="service-icon">🏗️</div><h3>New Construction</h3><p>Custom homes and commercial buildings built to your specifications.</p></div>
                <div class="service-card"><div class="service-icon">🔨</div><h3>Renovations</h3><p>Transform your existing space with our expert renovation services.</p></div>
                <div class="service-card"><div class="service-icon">🏠</div><h3>Additions</h3><p>Expand your living space with seamless home additions.</p></div>
                <div class="service-card"><div class="service-icon">📐</div><h3>Project Management</h3><p>Full-service project oversight from concept to completion.</p></div>'

    local names=("builder-pro" "foundation-strong" "steel-frame" "hard-hat-heroes" "concrete-kings" "blueprint-masters" "site-works" "construct-elite" "build-right" "hammer-time" "framework-pro" "solid-ground" "rise-up-builds" "premier-construct" "urban-builders" "quality-craft" "pro-build" "master-construct" "summit-builders" "apex-construction")

    for i in {1..20}; do
        generate_template "construction" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# PLUMBER TEMPLATES
# ============================================
generate_plumber() {
    echo "Generating Plumber templates..."
    local industry="Plumbing"
    local tagline="Expert plumbing solutions for your home and business. Fast, reliable service."
    local services='                <div class="service-card"><div class="service-icon">🔧</div><h3>Pipe Repair</h3><p>Quick fixes for leaks, bursts, and damaged pipes.</p></div>
                <div class="service-card"><div class="service-icon">🚿</div><h3>Drain Cleaning</h3><p>Professional drain clearing and maintenance services.</p></div>
                <div class="service-card"><div class="service-icon">🚰</div><h3>Water Heaters</h3><p>Installation and repair of all water heater types.</p></div>
                <div class="service-card"><div class="service-icon">🏠</div><h3>Emergency Service</h3><p>24/7 emergency plumbing when you need it most.</p></div>'

    local names=("flow-masters" "pipe-dreams" "drain-pro" "water-works" "plumb-perfect" "quick-fix-plumbing" "reliable-pipes" "pro-plumb" "flush-right" "pipe-experts" "clear-drains" "master-plumbers" "flow-tech" "aqua-pro" "pipeline-pros" "drain-experts" "water-wise" "plumb-line" "pipe-masters" "blue-flow")

    for i in {1..20}; do
        generate_template "plumber" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# ELECTRICIAN TEMPLATES
# ============================================
generate_electrician() {
    echo "Generating Electrician templates..."
    local industry="Electrical"
    local tagline="Safe, reliable electrical services for residential and commercial properties."
    local services='                <div class="service-card"><div class="service-icon">⚡</div><h3>Electrical Repairs</h3><p>Fast diagnosis and repair of all electrical issues.</p></div>
                <div class="service-card"><div class="service-icon">💡</div><h3>Lighting Installation</h3><p>Indoor and outdoor lighting design and installation.</p></div>
                <div class="service-card"><div class="service-icon">🔌</div><h3>Panel Upgrades</h3><p>Modernize your electrical panel for safety and capacity.</p></div>
                <div class="service-card"><div class="service-icon">🏠</div><h3>Home Wiring</h3><p>Complete wiring for new construction and renovations.</p></div>'

    local names=("spark-pro" "power-up" "wire-wizards" "volt-masters" "electric-elite" "current-solutions" "bright-spark" "power-pro" "circuit-masters" "wired-right" "amp-up" "electric-edge" "shock-free" "power-flow" "light-up" "pro-electric" "circuit-pro" "voltage-experts" "wire-works" "electric-pros")

    for i in {1..20}; do
        generate_template "electrician" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# PAINTER TEMPLATES
# ============================================
generate_painter() {
    echo "Generating Painter templates..."
    local industry="Painting"
    local tagline="Transform your space with professional painting services. Quality that shows."
    local services='                <div class="service-card"><div class="service-icon">🎨</div><h3>Interior Painting</h3><p>Beautiful interior finishes for every room.</p></div>
                <div class="service-card"><div class="service-icon">🏠</div><h3>Exterior Painting</h3><p>Weather-resistant exterior coatings that last.</p></div>
                <div class="service-card"><div class="service-icon">🖌️</div><h3>Cabinet Refinishing</h3><p>Give your cabinets a fresh new look.</p></div>
                <div class="service-card"><div class="service-icon">✨</div><h3>Specialty Finishes</h3><p>Textures, faux finishes, and decorative painting.</p></div>'

    local names=("color-masters" "fresh-coat" "paint-perfect" "brush-strokes" "prime-painters" "color-pro" "smooth-finish" "paint-pros" "vibrant-walls" "elite-painters" "true-colors" "perfect-paint" "brush-masters" "color-craft" "pro-painters" "painted-right" "quality-coat" "paint-works" "master-painters" "color-edge")

    for i in {1..20}; do
        generate_template "painter" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# HVAC TEMPLATES
# ============================================
generate_hvac() {
    echo "Generating HVAC templates..."
    local industry="HVAC"
    local tagline="Complete heating, cooling, and air quality solutions for your comfort."
    local services='                <div class="service-card"><div class="service-icon">❄️</div><h3>AC Repair</h3><p>Fast air conditioning repair and maintenance.</p></div>
                <div class="service-card"><div class="service-icon">🔥</div><h3>Heating Services</h3><p>Furnace repair, installation, and maintenance.</p></div>
                <div class="service-card"><div class="service-icon">🌬️</div><h3>Air Quality</h3><p>Improve your indoor air with filtration systems.</p></div>
                <div class="service-card"><div class="service-icon">🏠</div><h3>System Installation</h3><p>New HVAC system design and installation.</p></div>'

    local names=("climate-control" "air-masters" "cool-comfort" "heat-pro" "air-flow-experts" "comfort-zone" "climate-pro" "air-quality" "temp-masters" "cool-air" "heat-and-cool" "air-experts" "climate-solutions" "pro-hvac" "comfort-air" "air-pro" "climate-masters" "cool-zone" "air-comfort" "perfect-temp")

    for i in {1..20}; do
        generate_template "hvac" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# CLEANING TEMPLATES
# ============================================
generate_cleaning() {
    echo "Generating Cleaning templates..."
    local industry="Cleaning"
    local tagline="Professional cleaning services that make your space shine."
    local services='                <div class="service-card"><div class="service-icon">🏠</div><h3>Residential Cleaning</h3><p>Thorough home cleaning tailored to your needs.</p></div>
                <div class="service-card"><div class="service-icon">🏢</div><h3>Commercial Cleaning</h3><p>Professional office and business cleaning.</p></div>
                <div class="service-card"><div class="service-icon">✨</div><h3>Deep Cleaning</h3><p>Intensive cleaning for a fresh start.</p></div>
                <div class="service-card"><div class="service-icon">🧹</div><h3>Move In/Out</h3><p>Complete cleaning for property transitions.</p></div>'

    local names=("sparkle-clean" "fresh-start" "clean-pro" "spotless" "pure-clean" "shine-bright" "clean-masters" "fresh-clean" "pro-cleaners" "dust-free" "crystal-clean" "clean-sweep" "pristine-pro" "fresh-space" "clean-solutions" "tidy-pro" "gleam-team" "clean-edge" "pure-shine" "master-clean")

    for i in {1..20}; do
        generate_template "cleaning" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# PEST CONTROL TEMPLATES
# ============================================
generate_pest_control() {
    echo "Generating Pest Control templates..."
    local industry="Pest Control"
    local tagline="Keep your home and business pest-free with our expert solutions."
    local services='                <div class="service-card"><div class="service-icon">🐜</div><h3>General Pest Control</h3><p>Eliminate common household pests for good.</p></div>
                <div class="service-card"><div class="service-icon">🐀</div><h3>Rodent Control</h3><p>Effective mouse and rat removal services.</p></div>
                <div class="service-card"><div class="service-icon">🕷️</div><h3>Insect Treatment</h3><p>Specialized treatment for all insect types.</p></div>
                <div class="service-card"><div class="service-icon">🏠</div><h3>Prevention Plans</h3><p>Ongoing protection to keep pests away.</p></div>'

    local names=("bug-free" "pest-pro" "no-more-pests" "critter-control" "pest-masters" "bug-busters" "pest-solutions" "safe-home" "pest-shield" "bug-out" "pest-free" "critter-pro" "pest-guard" "bug-master" "pest-experts" "control-pro" "pest-away" "bug-control" "safe-guard" "pest-defense")

    for i in {1..20}; do
        generate_template "pest-control" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# SALON TEMPLATES
# ============================================
generate_salon() {
    echo "Generating Salon templates..."
    local industry="Salon"
    local tagline="Your destination for beautiful hair and exceptional service."
    local services='                <div class="service-card"><div class="service-icon">💇</div><h3>Haircuts & Styling</h3><p>Precision cuts and trendy styles for all.</p></div>
                <div class="service-card"><div class="service-icon">🎨</div><h3>Color Services</h3><p>Highlights, balayage, and full color treatments.</p></div>
                <div class="service-card"><div class="service-icon">✨</div><h3>Treatments</h3><p>Keratin, deep conditioning, and repairs.</p></div>
                <div class="service-card"><div class="service-icon">💅</div><h3>Special Occasions</h3><p>Bridal, prom, and event styling.</p></div>'

    local names=("glamour-cuts" "style-studio" "hair-haven" "chic-salon" "beauty-bar" "luxe-locks" "salon-elite" "hair-masters" "style-pro" "glam-studio" "beauty-bliss" "hair-artistry" "salon-luxe" "style-haven" "glamour-studio" "hair-pro" "beauty-elite" "chic-cuts" "salon-style" "hair-luxe")

    for i in {1..20}; do
        generate_template "salon" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# SPA TEMPLATES
# ============================================
generate_spa() {
    echo "Generating Spa templates..."
    local industry="Spa"
    local tagline="Relax, rejuvenate, and restore at our tranquil spa retreat."
    local services='                <div class="service-card"><div class="service-icon">💆</div><h3>Massage Therapy</h3><p>Swedish, deep tissue, and hot stone massage.</p></div>
                <div class="service-card"><div class="service-icon">🧖</div><h3>Facials</h3><p>Customized facials for radiant skin.</p></div>
                <div class="service-card"><div class="service-icon">🛁</div><h3>Body Treatments</h3><p>Wraps, scrubs, and detox treatments.</p></div>
                <div class="service-card"><div class="service-icon">✨</div><h3>Spa Packages</h3><p>Complete wellness experiences to indulge in.</p></div>'

    local names=("serenity-spa" "bliss-retreat" "zen-haven" "pure-relaxation" "tranquil-touch" "spa-luxe" "calm-waters" "peaceful-spa" "harmony-haven" "spa-bliss" "serene-space" "relaxation-station" "zen-spa" "pure-spa" "tranquil-spa" "blissful-spa" "calm-spa" "peaceful-haven" "spa-serenity" "zen-retreat")

    for i in {1..20}; do
        generate_template "spa" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# BARBER TEMPLATES
# ============================================
generate_barber() {
    echo "Generating Barber templates..."
    local industry="Barber"
    local tagline="Classic cuts and modern styles. The barbershop experience redefined."
    local services='                <div class="service-card"><div class="service-icon">✂️</div><h3>Haircuts</h3><p>Classic and contemporary cuts for men.</p></div>
                <div class="service-card"><div class="service-icon">🪒</div><h3>Beard Services</h3><p>Beard trims, shaping, and hot towel shaves.</p></div>
                <div class="service-card"><div class="service-icon">💈</div><h3>Traditional Shaves</h3><p>Straight razor shaves with hot lather.</p></div>
                <div class="service-card"><div class="service-icon">✨</div><h3>Hair Treatments</h3><p>Scalp treatments and hair care services.</p></div>'

    local names=("sharp-cuts" "classic-barber" "the-chop-shop" "gentlemans-cut" "blade-masters" "prime-cuts" "barber-pro" "clean-cuts" "style-barber" "edge-barber" "classic-cuts" "sharp-style" "pro-barber" "blade-pro" "gents-barber" "cut-masters" "style-edge" "barber-elite" "sharp-edge" "classic-style")

    for i in {1..20}; do
        generate_template "barber" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# MASSAGE TEMPLATES
# ============================================
generate_massage() {
    echo "Generating Massage templates..."
    local industry="Massage Therapy"
    local tagline="Therapeutic massage for relaxation, recovery, and wellness."
    local services='                <div class="service-card"><div class="service-icon">💆</div><h3>Swedish Massage</h3><p>Relaxing full-body massage for stress relief.</p></div>
                <div class="service-card"><div class="service-icon">💪</div><h3>Deep Tissue</h3><p>Targeted therapy for muscle tension and pain.</p></div>
                <div class="service-card"><div class="service-icon">🔥</div><h3>Hot Stone</h3><p>Heated stones for deep relaxation.</p></div>
                <div class="service-card"><div class="service-icon">🏃</div><h3>Sports Massage</h3><p>Athletic recovery and performance support.</p></div>'

    local names=("healing-hands" "relax-restore" "touch-therapy" "wellness-massage" "calm-touch" "body-bliss" "massage-pro" "healing-touch" "restore-wellness" "peaceful-touch" "body-wellness" "massage-haven" "healing-therapy" "calm-hands" "touch-wellness" "body-restore" "massage-bliss" "healing-haven" "wellness-touch" "restore-massage")

    for i in {1..20}; do
        generate_template "massage" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# HEALTH & BEAUTY TEMPLATES
# ============================================
generate_health_beauty() {
    echo "Generating Health & Beauty templates..."
    local industry="Health & Beauty"
    local tagline="Your complete destination for health, beauty, and wellness."
    local services='                <div class="service-card"><div class="service-icon">💅</div><h3>Nail Services</h3><p>Manicures, pedicures, and nail art.</p></div>
                <div class="service-card"><div class="service-icon">🧖</div><h3>Skincare</h3><p>Facials, peels, and skin treatments.</p></div>
                <div class="service-card"><div class="service-icon">💄</div><h3>Makeup</h3><p>Professional makeup for any occasion.</p></div>
                <div class="service-card"><div class="service-icon">✨</div><h3>Wellness</h3><p>Holistic health and beauty treatments.</p></div>'

    local names=("glow-up" "beauty-wellness" "radiant-you" "pure-beauty" "health-glow" "beauty-pro" "wellness-beauty" "glow-pro" "radiant-beauty" "pure-glow" "health-radiance" "beauty-bliss" "wellness-glow" "glow-beauty" "radiant-health" "pure-wellness" "beauty-radiance" "health-bliss" "wellness-pro" "glow-wellness")

    for i in {1..20}; do
        generate_template "health-beauty" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# FITNESS TEMPLATES
# ============================================
generate_fitness() {
    echo "Generating Fitness templates..."
    local industry="Fitness"
    local tagline="Transform your body and mind. Your fitness journey starts here."
    local services='                <div class="service-card"><div class="service-icon">🏋️</div><h3>Personal Training</h3><p>One-on-one coaching for your goals.</p></div>
                <div class="service-card"><div class="service-icon">🧘</div><h3>Group Classes</h3><p>Energizing classes for all fitness levels.</p></div>
                <div class="service-card"><div class="service-icon">💪</div><h3>Strength Training</h3><p>Build muscle and increase power.</p></div>
                <div class="service-card"><div class="service-icon">🏃</div><h3>Cardio Programs</h3><p>Boost endurance and burn calories.</p></div>'

    local names=("peak-performance" "fit-life" "power-gym" "strength-zone" "fitness-pro" "active-life" "gym-masters" "fit-zone" "power-pro" "strength-pro" "fitness-elite" "active-fit" "gym-pro" "peak-fitness" "power-zone" "strength-elite" "fitness-zone" "active-pro" "gym-elite" "peak-pro")

    for i in {1..20}; do
        generate_template "fitness" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# BUSINESS SERVICES TEMPLATES
# ============================================
generate_business_services() {
    echo "Generating Business Services templates..."
    local industry="Business Services"
    local tagline="Professional business solutions to help your company thrive."
    local services='                <div class="service-card"><div class="service-icon">📊</div><h3>Consulting</h3><p>Expert business strategy and advice.</p></div>
                <div class="service-card"><div class="service-icon">📈</div><h3>Marketing</h3><p>Digital marketing and brand growth.</p></div>
                <div class="service-card"><div class="service-icon">💼</div><h3>Operations</h3><p>Streamline your business operations.</p></div>
                <div class="service-card"><div class="service-icon">📋</div><h3>Planning</h3><p>Strategic planning for long-term success.</p></div>'

    local names=("pro-solutions" "business-elite" "corporate-pro" "success-partners" "business-masters" "pro-business" "elite-solutions" "corporate-edge" "success-pro" "business-pro" "solutions-elite" "corporate-masters" "success-edge" "pro-corporate" "elite-business" "solutions-pro" "business-edge" "corporate-success" "pro-elite" "business-solutions")

    for i in {1..20}; do
        generate_template "business-services" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# REAL ESTATE TEMPLATES
# ============================================
generate_real_estate() {
    echo "Generating Real Estate templates..."
    local industry="Real Estate"
    local tagline="Find your dream home with our expert real estate services."
    local services='                <div class="service-card"><div class="service-icon">🏠</div><h3>Home Buying</h3><p>Expert guidance through the buying process.</p></div>
                <div class="service-card"><div class="service-icon">💰</div><h3>Home Selling</h3><p>Get top dollar for your property.</p></div>
                <div class="service-card"><div class="service-icon">🔑</div><h3>Rentals</h3><p>Find the perfect rental property.</p></div>
                <div class="service-card"><div class="service-icon">📋</div><h3>Property Management</h3><p>Full-service property management.</p></div>'

    local names=("prime-properties" "dream-homes" "elite-realty" "home-masters" "property-pro" "real-estate-elite" "dream-realty" "prime-realty" "home-pro" "property-elite" "realty-masters" "dream-properties" "elite-properties" "home-realty" "property-masters" "prime-homes" "realty-pro" "dream-elite" "property-homes" "elite-homes")

    for i in {1..20}; do
        generate_template "real-estate" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# INSURANCE TEMPLATES
# ============================================
generate_insurance() {
    echo "Generating Insurance templates..."
    local industry="Insurance"
    local tagline="Protect what matters most with comprehensive insurance coverage."
    local services='                <div class="service-card"><div class="service-icon">🏠</div><h3>Home Insurance</h3><p>Protect your home and belongings.</p></div>
                <div class="service-card"><div class="service-icon">🚗</div><h3>Auto Insurance</h3><p>Coverage for all your vehicles.</p></div>
                <div class="service-card"><div class="service-icon">❤️</div><h3>Life Insurance</h3><p>Secure your family future.</p></div>
                <div class="service-card"><div class="service-icon">💼</div><h3>Business Insurance</h3><p>Comprehensive business protection.</p></div>'

    local names=("secure-insurance" "shield-pro" "coverage-masters" "safe-guard-insurance" "protect-pro" "insurance-elite" "secure-shield" "coverage-pro" "safe-insurance" "shield-masters" "protect-elite" "insurance-pro" "secure-pro" "coverage-elite" "safe-shield" "protect-insurance" "shield-elite" "secure-coverage" "safe-pro" "insurance-masters")

    for i in {1..20}; do
        generate_template "insurance" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# MORTGAGE TEMPLATES
# ============================================
generate_mortgage() {
    echo "Generating Mortgage templates..."
    local industry="Mortgage"
    local tagline="Making homeownership possible with the right mortgage solutions."
    local services='                <div class="service-card"><div class="service-icon">🏠</div><h3>Home Loans</h3><p>Competitive rates for your dream home.</p></div>
                <div class="service-card"><div class="service-icon">🔄</div><h3>Refinancing</h3><p>Lower your rate or access equity.</p></div>
                <div class="service-card"><div class="service-icon">🏗️</div><h3>Construction Loans</h3><p>Finance your new home build.</p></div>
                <div class="service-card"><div class="service-icon">📊</div><h3>Pre-Approval</h3><p>Get pre-approved and shop with confidence.</p></div>'

    local names=("home-loans-pro" "mortgage-masters" "finance-home" "loan-pro" "mortgage-elite" "home-finance" "loan-masters" "mortgage-pro" "finance-pro" "home-mortgage" "loan-elite" "mortgage-solutions" "finance-elite" "home-loans" "loan-solutions" "mortgage-home" "finance-masters" "home-solutions" "loan-finance" "mortgage-finance")

    for i in {1..20}; do
        generate_template "mortgage" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# ARCHITECT TEMPLATES
# ============================================
generate_architect() {
    echo "Generating Architect templates..."
    local industry="Architecture"
    local tagline="Innovative architectural design that brings your vision to life."
    local services='                <div class="service-card"><div class="service-icon">🏛️</div><h3>Residential Design</h3><p>Custom homes designed for your lifestyle.</p></div>
                <div class="service-card"><div class="service-icon">🏢</div><h3>Commercial Design</h3><p>Functional spaces for business success.</p></div>
                <div class="service-card"><div class="service-icon">📐</div><h3>Renovations</h3><p>Transform existing spaces beautifully.</p></div>
                <div class="service-card"><div class="service-icon">🌿</div><h3>Sustainable Design</h3><p>Eco-friendly architecture solutions.</p></div>'

    local names=("design-masters" "blueprint-pro" "arch-studio" "structure-elite" "design-pro" "architect-elite" "blueprint-masters" "studio-arch" "structure-pro" "design-elite" "arch-pro" "blueprint-elite" "studio-design" "structure-masters" "architect-pro" "design-studio" "blueprint-studio" "arch-elite" "structure-design" "studio-elite")

    for i in {1..20}; do
        generate_template "architect" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# INTERIOR DESIGN TEMPLATES
# ============================================
generate_interior_design() {
    echo "Generating Interior Design templates..."
    local industry="Interior Design"
    local tagline="Beautiful interiors that reflect your style and enhance your life."
    local services='                <div class="service-card"><div class="service-icon">🛋️</div><h3>Residential Design</h3><p>Create your perfect living space.</p></div>
                <div class="service-card"><div class="service-icon">🏢</div><h3>Commercial Design</h3><p>Inspiring workspaces that perform.</p></div>
                <div class="service-card"><div class="service-icon">🎨</div><h3>Color Consultation</h3><p>Expert color schemes for any space.</p></div>
                <div class="service-card"><div class="service-icon">🪑</div><h3>Furniture Selection</h3><p>Curated furnishings for your style.</p></div>'

    local names=("design-space" "interior-pro" "style-masters" "space-design" "interior-elite" "design-interiors" "space-pro" "style-elite" "interior-masters" "design-elite" "space-style" "interior-design-pro" "style-pro" "space-elite" "interior-style" "design-style" "space-masters" "style-interiors" "design-pro-int" "interior-space")

    for i in {1..20}; do
        generate_template "interior-design" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# RESTAURANT TEMPLATES
# ============================================
generate_restaurant() {
    echo "Generating Restaurant templates..."
    local industry="Restaurant"
    local tagline="Exceptional dining experiences with flavors you will love."
    local services='                <div class="service-card"><div class="service-icon">🍽️</div><h3>Dine In</h3><p>Enjoy our full menu in our welcoming space.</p></div>
                <div class="service-card"><div class="service-icon">🥡</div><h3>Takeout</h3><p>Your favorites, ready when you are.</p></div>
                <div class="service-card"><div class="service-icon">🚗</div><h3>Delivery</h3><p>Fresh food delivered to your door.</p></div>
                <div class="service-card"><div class="service-icon">🎉</div><h3>Catering</h3><p>Perfect food for your special events.</p></div>'

    local names=("taste-haven" "dine-fine" "food-masters" "culinary-elite" "taste-pro" "restaurant-elite" "fine-dining" "food-pro" "culinary-pro" "taste-elite" "dine-pro" "food-elite" "culinary-masters" "taste-masters" "restaurant-pro" "fine-food" "dining-elite" "food-taste" "culinary-taste" "restaurant-masters")

    for i in {1..20}; do
        generate_template "restaurant" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# AUTOMOTIVE TEMPLATES
# ============================================
generate_automotive() {
    echo "Generating Automotive templates..."
    local industry="Automotive"
    local tagline="Expert auto services to keep you on the road safely."
    local services='                <div class="service-card"><div class="service-icon">🔧</div><h3>Repairs</h3><p>Complete auto repair services.</p></div>
                <div class="service-card"><div class="service-icon">🛢️</div><h3>Maintenance</h3><p>Oil changes, tune-ups, and more.</p></div>
                <div class="service-card"><div class="service-icon">🔩</div><h3>Diagnostics</h3><p>Advanced computer diagnostics.</p></div>
                <div class="service-card"><div class="service-icon">🚗</div><h3>Inspections</h3><p>State inspections and safety checks.</p></div>'

    local names=("auto-pro" "drive-masters" "car-elite" "motor-pro" "auto-elite" "drive-pro" "car-masters" "motor-elite" "auto-masters" "drive-elite" "car-pro" "motor-masters" "auto-drive" "car-drive" "motor-drive" "pro-motors" "elite-auto" "masters-auto" "pro-drive" "elite-motors")

    for i in {1..20}; do
        generate_template "automotive" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# EVENT TEMPLATES
# ============================================
generate_event() {
    echo "Generating Event templates..."
    local industry="Event Planning"
    local tagline="Creating unforgettable events tailored to your vision."
    local services='                <div class="service-card"><div class="service-icon">💒</div><h3>Weddings</h3><p>Your dream wedding, perfectly planned.</p></div>
                <div class="service-card"><div class="service-icon">🎂</div><h3>Parties</h3><p>Birthday, anniversary, and celebration planning.</p></div>
                <div class="service-card"><div class="service-icon">🏢</div><h3>Corporate Events</h3><p>Professional events that impress.</p></div>
                <div class="service-card"><div class="service-icon">🎪</div><h3>Special Occasions</h3><p>Any event, any size, any style.</p></div>'

    local names=("event-pro" "celebrate-elite" "party-masters" "event-elite" "celebrate-pro" "party-pro" "event-masters" "celebrate-masters" "party-elite" "pro-events" "elite-celebrations" "masters-party" "pro-celebrate" "elite-events" "masters-events" "pro-party" "elite-party" "masters-celebrate" "events-elite" "celebrations-pro")

    for i in {1..20}; do
        generate_template "event" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# PHOTOGRAPHY TEMPLATES
# ============================================
generate_photography() {
    echo "Generating Photography templates..."
    local industry="Photography"
    local tagline="Capturing your precious moments with artistic excellence."
    local services='                <div class="service-card"><div class="service-icon">💒</div><h3>Wedding Photography</h3><p>Beautiful memories of your special day.</p></div>
                <div class="service-card"><div class="service-icon">👨‍👩‍👧</div><h3>Family Portraits</h3><p>Timeless family photos to treasure.</p></div>
                <div class="service-card"><div class="service-icon">💼</div><h3>Commercial</h3><p>Professional imagery for your business.</p></div>
                <div class="service-card"><div class="service-icon">🎉</div><h3>Events</h3><p>Document your special occasions.</p></div>'

    local names=("capture-pro" "photo-masters" "lens-elite" "image-pro" "capture-elite" "photo-pro" "lens-masters" "image-elite" "capture-masters" "photo-elite" "lens-pro" "image-masters" "pro-capture" "elite-photo" "masters-lens" "pro-image" "elite-capture" "masters-photo" "pro-lens" "elite-image")

    for i in {1..20}; do
        generate_template "photography" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# MUSIC TEMPLATES
# ============================================
generate_music() {
    echo "Generating Music templates..."
    local industry="Music"
    local tagline="Professional music services for lessons, events, and productions."
    local services='                <div class="service-card"><div class="service-icon">🎸</div><h3>Music Lessons</h3><p>Learn any instrument with expert teachers.</p></div>
                <div class="service-card"><div class="service-icon">🎤</div><h3>Live Performance</h3><p>Entertainment for your special events.</p></div>
                <div class="service-card"><div class="service-icon">🎧</div><h3>Recording</h3><p>Professional studio recording services.</p></div>
                <div class="service-card"><div class="service-icon">🎼</div><h3>Production</h3><p>Music production and mixing services.</p></div>'

    local names=("sound-pro" "music-masters" "beat-elite" "audio-pro" "sound-elite" "music-pro" "beat-masters" "audio-elite" "sound-masters" "music-elite" "beat-pro" "audio-masters" "pro-sound" "elite-music" "masters-beat" "pro-audio" "elite-sound" "masters-music" "pro-beat" "elite-audio")

    for i in {1..20}; do
        generate_template "music" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# SINGLE PAGE TEMPLATES
# ============================================
generate_single_page() {
    echo "Generating Single Page templates..."
    local industry="Business"
    local tagline="Everything you need on one beautiful, effective page."
    local services='                <div class="service-card"><div class="service-icon">🎯</div><h3>Our Services</h3><p>Professional solutions tailored to your needs.</p></div>
                <div class="service-card"><div class="service-icon">⭐</div><h3>Quality Work</h3><p>Excellence in everything we do.</p></div>
                <div class="service-card"><div class="service-icon">🤝</div><h3>Customer Focus</h3><p>Your satisfaction is our priority.</p></div>
                <div class="service-card"><div class="service-icon">💼</div><h3>Experience</h3><p>Years of expertise at your service.</p></div>'

    local names=("one-page-pro" "single-pro" "simple-site" "one-page-elite" "single-elite" "simple-pro" "one-page-masters" "single-masters" "simple-elite" "pro-single" "elite-one-page" "masters-simple" "pro-one-page" "elite-single" "masters-one-page" "pro-simple" "elite-simple" "masters-single" "single-simple" "one-simple")

    for i in {1..20}; do
        generate_template "single-page" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# LANDING PAGE TEMPLATES
# ============================================
generate_landing_page() {
    echo "Generating Landing Page templates..."
    local industry="Business"
    local tagline="Convert visitors into customers with our proven approach."
    local services='                <div class="service-card"><div class="service-icon">🚀</div><h3>Fast Results</h3><p>See results quickly with our approach.</p></div>
                <div class="service-card"><div class="service-icon">💡</div><h3>Smart Solutions</h3><p>Innovative answers to your challenges.</p></div>
                <div class="service-card"><div class="service-icon">📈</div><h3>Growth Focused</h3><p>Strategies designed for growth.</p></div>
                <div class="service-card"><div class="service-icon">🎯</div><h3>Targeted</h3><p>Precision solutions for your needs.</p></div>'

    local names=("convert-pro" "landing-elite" "lead-masters" "convert-elite" "landing-pro" "lead-pro" "convert-masters" "landing-masters" "lead-elite" "pro-convert" "elite-landing" "masters-lead" "pro-landing" "elite-convert" "masters-landing" "pro-lead" "elite-lead" "masters-convert" "convert-lead" "landing-lead")

    for i in {1..20}; do
        generate_template "landing-page" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# ONLINE STORE TEMPLATES
# ============================================
generate_online_store() {
    echo "Generating Online Store templates..."
    local industry="E-Commerce"
    local tagline="Shop our curated collection of quality products."
    local services='                <div class="service-card"><div class="service-icon">🛍️</div><h3>Shop Products</h3><p>Browse our full product catalog.</p></div>
                <div class="service-card"><div class="service-icon">🚚</div><h3>Fast Shipping</h3><p>Quick delivery to your door.</p></div>
                <div class="service-card"><div class="service-icon">↩️</div><h3>Easy Returns</h3><p>Hassle-free return policy.</p></div>
                <div class="service-card"><div class="service-icon">💳</div><h3>Secure Checkout</h3><p>Safe and secure payment options.</p></div>'

    local names=("shop-pro" "store-elite" "ecommerce-masters" "shop-elite" "store-pro" "ecommerce-pro" "shop-masters" "store-masters" "ecommerce-elite" "pro-shop" "elite-store" "masters-ecommerce" "pro-store" "elite-shop" "masters-store" "pro-ecommerce" "elite-ecommerce" "masters-shop" "shop-store" "store-shop")

    for i in {1..20}; do
        generate_template "online-store" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# FULL WEBSITE TEMPLATES
# ============================================
generate_full_website() {
    echo "Generating Full Website templates..."
    local industry="Business"
    local tagline="Complete professional web presence for your business."
    local services='                <div class="service-card"><div class="service-icon">🏠</div><h3>Home</h3><p>Welcome visitors with a great first impression.</p></div>
                <div class="service-card"><div class="service-icon">📋</div><h3>Services</h3><p>Showcase everything you offer.</p></div>
                <div class="service-card"><div class="service-icon">👥</div><h3>About</h3><p>Tell your story and build trust.</p></div>
                <div class="service-card"><div class="service-icon">📞</div><h3>Contact</h3><p>Make it easy to get in touch.</p></div>'

    local names=("complete-pro" "full-site-elite" "website-masters" "complete-elite" "full-site-pro" "website-pro" "complete-masters" "full-site-masters" "website-elite" "pro-complete" "elite-full-site" "masters-website" "pro-full-site" "elite-complete" "masters-full-site" "pro-website" "elite-website" "masters-complete" "complete-website" "full-complete")

    for i in {1..20}; do
        generate_template "full-website" $i "${names[$i-1]}" "$industry" "$tagline" "$services"
    done
}

# ============================================
# MAIN EXECUTION
# ============================================

echo "=========================================="
echo "60 Minute Sites Template Generator"
echo "Generating 560 templates across 28 categories"
echo "=========================================="
echo ""

# Batch 1 - Service Industries (140 templates)
echo "BATCH 1: Service Industries"
generate_construction
generate_plumber
generate_electrician
generate_painter
generate_hvac
generate_cleaning
generate_pest_control
echo ""

# Batch 2 - Beauty & Wellness (120 templates)
echo "BATCH 2: Beauty & Wellness"
generate_salon
generate_spa
generate_barber
generate_massage
generate_health_beauty
generate_fitness
echo ""

# Batch 3 - Professional Services (120 templates)
echo "BATCH 3: Professional Services"
generate_business_services
generate_real_estate
generate_insurance
generate_mortgage
generate_architect
generate_interior_design
echo ""

# Batch 4 - Specialty (100 templates)
echo "BATCH 4: Specialty"
generate_restaurant
generate_automotive
generate_event
generate_photography
generate_music
echo ""

# Batch 5 - Page Types (80 templates)
echo "BATCH 5: Page Types"
generate_single_page
generate_landing_page
generate_online_store
generate_full_website
echo ""

echo "=========================================="
echo "COMPLETE! Generated 560 templates."
echo "=========================================="
