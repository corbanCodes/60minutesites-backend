#!/bin/bash

# 60 Minute Sites - Enhanced Template Generator v2
# Creates professional marketing templates with 10+ sections, no emojis, real images

BASE_DIR="/Users/corbandamukaitis/Desktop/Personal Projects/60minutesites.com/templates"

# Color palettes for 20 styles
declare -a STYLES=(
    "Modern Minimal|#1A1A1A|#FFFFFF|#FF6B35|#F5F5F5|#333333|#666666"
    "Bold & Dark|#0D0D0D|#1A1A1A|#FF4444|#121212|#FFFFFF|#CCCCCC"
    "Classic Professional|#1E3A5F|#2C5282|#C9A227|#FFFFFF|#333333|#666666"
    "Vibrant & Colorful|#FF6B6B|#4ECDC4|#FFE66D|#FFFFFF|#333333|#666666"
    "Elegant & Luxurious|#2C2C2C|#B8860B|#D4AF37|#1A1A1A|#FFFFFF|#CCCCCC"
    "Rustic & Warm|#8B4513|#D2691E|#F4A460|#FFF8DC|#333333|#666666"
    "Tech & Futuristic|#0A192F|#64FFDA|#00D9FF|#0A192F|#FFFFFF|#CCCCCC"
    "Clean & Corporate|#2563EB|#1E40AF|#3B82F6|#F8FAFC|#333333|#666666"
    "Playful & Fun|#FF6B9D|#C44DFF|#FFD93D|#FFF5F5|#333333|#666666"
    "Sophisticated & Sleek|#18181B|#27272A|#A78BFA|#09090B|#FFFFFF|#CCCCCC"
    "Natural & Organic|#2D5016|#4A7C23|#84CC16|#F7FEE7|#333333|#666666"
    "Urban & Industrial|#374151|#4B5563|#F59E0B|#1F2937|#FFFFFF|#CCCCCC"
    "Vintage & Retro|#B45309|#92400E|#FCD34D|#FFFBEB|#333333|#666666"
    "Fresh & Bright|#0EA5E9|#06B6D4|#22D3EE|#F0F9FF|#333333|#666666"
    "Calm & Serene|#5B8C85|#7FB3AC|#A7D7C5|#F5FFFA|#333333|#666666"
    "Dynamic & Energetic|#DC2626|#EF4444|#FCA5A5|#FEF2F2|#333333|#666666"
    "Premium & Exclusive|#1C1917|#292524|#A3A3A3|#0C0A09|#FFFFFF|#CCCCCC"
    "Friendly & Approachable|#059669|#10B981|#34D399|#ECFDF5|#333333|#666666"
    "Sharp & Geometric|#4F46E5|#6366F1|#818CF8|#EEF2FF|#333333|#666666"
    "Soft & Rounded|#EC4899|#F472B6|#FBCFE8|#FDF2F8|#333333|#666666"
)

generate_enhanced_template() {
    local category=$1
    local num=$2
    local name=$3
    local industry=$4
    local tagline=$5
    local services_data=$6  # Format: "icon1|title1|desc1||icon2|title2|desc2||..."
    local image_keyword=$7

    local padded_num=$(printf "%02d" $num)
    local template_dir="$BASE_DIR/$category/$padded_num-$name"

    # Get style based on template number
    local style_index=$((num - 1))
    IFS='|' read -r style_name primary secondary accent background text_dark text_light <<< "${STYLES[$style_index]}"

    # Create display name
    local display_name=$(echo "$name" | sed 's/-/ /g' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2));}1')

    # Unique seed for consistent images
    local img_seed="${category}-${name}"

    mkdir -p "$template_dir/assets"

    # Generate enhanced index.html
    cat > "$template_dir/index.html" << 'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="DISPLAY_NAME - Professional INDUSTRY services. TAGLINE">
    <meta name="keywords" content="INDUSTRY, CATEGORY, professional services, local business, quality service">
    <meta name="author" content="60 Minute Sites">
    <meta property="og:title" content="DISPLAY_NAME | Professional INDUSTRY">
    <meta property="og:description" content="TAGLINE">
    <meta property="og:type" content="website">
    <title>DISPLAY_NAME | Professional INDUSTRY</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <!-- Navigation -->
    <header class="header" id="header">
        <nav class="nav container">
            <a href="#" class="logo">DISPLAY_NAME</a>
            <ul class="nav-links" id="nav-links">
                <li><a href="#services">Services</a></li>
                <li><a href="#about">About</a></li>
                <li><a href="#portfolio">Portfolio</a></li>
                <li><a href="#testimonials">Reviews</a></li>
                <li><a href="#contact">Contact</a></li>
            </ul>
            <div class="nav-actions">
                <a href="tel:817-403-2179" class="btn btn-outline btn-sm"><i class="fas fa-phone"></i> Call Now</a>
                <a href="https://calendly.com/corban-leadsprinter/new-meeting" target="_blank" class="btn btn-primary btn-sm">Book Online</a>
            </div>
            <button class="mobile-toggle" id="mobile-toggle" aria-label="Toggle menu">
                <span></span><span></span><span></span>
            </button>
        </nav>
    </header>

    <!-- Hero Section -->
    <section class="hero" id="hero">
        <div class="hero-bg" style="background-image: url('https://picsum.photos/seed/IMG_SEED-hero/1920/1080')"></div>
        <div class="hero-overlay"></div>
        <div class="hero-content container">
            <span class="hero-badge">Trusted INDUSTRY Professionals</span>
            <h1>DISPLAY_NAME</h1>
            <p class="hero-subtitle">TAGLINE</p>
            <div class="hero-buttons">
                <a href="#contact" class="btn btn-primary btn-lg"><i class="fas fa-paper-plane"></i> Get Free Quote</a>
                <a href="https://calendly.com/corban-leadsprinter/new-meeting" target="_blank" class="btn btn-outline-light btn-lg"><i class="fas fa-calendar-check"></i> Schedule Consultation</a>
            </div>
            <div class="hero-features">
                <div class="hero-feature"><i class="fas fa-check-circle"></i> Licensed & Insured</div>
                <div class="hero-feature"><i class="fas fa-check-circle"></i> Free Estimates</div>
                <div class="hero-feature"><i class="fas fa-check-circle"></i> Satisfaction Guaranteed</div>
            </div>
        </div>
        <a href="#services" class="scroll-indicator"><i class="fas fa-chevron-down"></i></a>
    </section>

    <!-- Services Section -->
    <section class="services section" id="services">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">What We Offer</span>
                <h2>Our Services</h2>
                <p>Comprehensive INDUSTRY solutions tailored to your needs</p>
            </div>
            <div class="services-grid">
                SERVICES_HTML
            </div>
            <div class="services-cta">
                <p>Need something specific? We customize our services to fit your project.</p>
                <a href="#contact" class="btn btn-primary">Discuss Your Project</a>
            </div>
        </div>
    </section>

    <!-- Stats Section -->
    <section class="stats section-dark">
        <div class="container">
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-number" data-count="500">0</div>
                    <div class="stat-label">Projects Completed</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number" data-count="15">0</div>
                    <div class="stat-label">Years Experience</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number" data-count="98">0</div>
                    <div class="stat-label">% Satisfaction Rate</div>
                </div>
                <div class="stat-item">
                    <div class="stat-number" data-count="24">0</div>
                    <div class="stat-label">Hour Support</div>
                </div>
            </div>
        </div>
    </section>

    <!-- About Section -->
    <section class="about section" id="about">
        <div class="container">
            <div class="about-grid">
                <div class="about-image">
                    <img src="https://picsum.photos/seed/IMG_SEED-about/600/700" alt="About DISPLAY_NAME">
                    <div class="about-badge">
                        <span class="badge-number">15+</span>
                        <span class="badge-text">Years of Excellence</span>
                    </div>
                </div>
                <div class="about-content">
                    <span class="section-badge">Who We Are</span>
                    <h2>Your Trusted INDUSTRY Partner</h2>
                    <p class="lead">We are dedicated INDUSTRY professionals committed to delivering exceptional results that exceed expectations.</p>
                    <p>With over 15 years of experience serving our community, we've built our reputation on quality workmanship, honest communication, and customer satisfaction. Our team of skilled professionals brings expertise and attention to detail to every project.</p>
                    <ul class="about-list">
                        <li><i class="fas fa-check"></i> Fully licensed, bonded, and insured</li>
                        <li><i class="fas fa-check"></i> Background-checked professionals</li>
                        <li><i class="fas fa-check"></i> Transparent pricing with no hidden fees</li>
                        <li><i class="fas fa-check"></i> Satisfaction guarantee on all work</li>
                    </ul>
                    <a href="https://calendly.com/corban-leadsprinter/new-meeting" target="_blank" class="btn btn-primary"><i class="fas fa-calendar"></i> Schedule a Consultation</a>
                </div>
            </div>
        </div>
    </section>

    <!-- Process Section -->
    <section class="process section section-alt">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">How It Works</span>
                <h2>Our Simple Process</h2>
                <p>Getting started is easy. Here's what to expect.</p>
            </div>
            <div class="process-grid">
                <div class="process-step">
                    <div class="process-number">1</div>
                    <div class="process-icon"><i class="fas fa-phone-alt"></i></div>
                    <h3>Contact Us</h3>
                    <p>Reach out by phone or schedule a free consultation online.</p>
                </div>
                <div class="process-connector"></div>
                <div class="process-step">
                    <div class="process-number">2</div>
                    <div class="process-icon"><i class="fas fa-clipboard-list"></i></div>
                    <h3>Free Assessment</h3>
                    <p>We evaluate your needs and provide a detailed, no-obligation quote.</p>
                </div>
                <div class="process-connector"></div>
                <div class="process-step">
                    <div class="process-number">3</div>
                    <div class="process-icon"><i class="fas fa-tools"></i></div>
                    <h3>Expert Service</h3>
                    <p>Our skilled team delivers quality work on your schedule.</p>
                </div>
                <div class="process-connector"></div>
                <div class="process-step">
                    <div class="process-number">4</div>
                    <div class="process-icon"><i class="fas fa-smile"></i></div>
                    <h3>Your Satisfaction</h3>
                    <p>We ensure you're completely happy with the results.</p>
                </div>
            </div>
        </div>
    </section>

    <!-- Portfolio Section -->
    <section class="portfolio section" id="portfolio">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">Our Work</span>
                <h2>Recent Projects</h2>
                <p>Browse our portfolio of completed INDUSTRY projects</p>
            </div>
            <div class="portfolio-grid">
                <div class="portfolio-item" data-category="all">
                    <img src="https://picsum.photos/seed/IMG_SEED-work1/600/400" alt="Project 1">
                    <div class="portfolio-overlay">
                        <h4>Project Title</h4>
                        <p>Quality INDUSTRY work</p>
                        <button class="btn btn-sm btn-light" onclick="openLightbox(this)"><i class="fas fa-expand"></i></button>
                    </div>
                </div>
                <div class="portfolio-item" data-category="all">
                    <img src="https://picsum.photos/seed/IMG_SEED-work2/600/400" alt="Project 2">
                    <div class="portfolio-overlay">
                        <h4>Project Title</h4>
                        <p>Quality INDUSTRY work</p>
                        <button class="btn btn-sm btn-light" onclick="openLightbox(this)"><i class="fas fa-expand"></i></button>
                    </div>
                </div>
                <div class="portfolio-item" data-category="all">
                    <img src="https://picsum.photos/seed/IMG_SEED-work3/600/400" alt="Project 3">
                    <div class="portfolio-overlay">
                        <h4>Project Title</h4>
                        <p>Quality INDUSTRY work</p>
                        <button class="btn btn-sm btn-light" onclick="openLightbox(this)"><i class="fas fa-expand"></i></button>
                    </div>
                </div>
                <div class="portfolio-item" data-category="all">
                    <img src="https://picsum.photos/seed/IMG_SEED-work4/600/400" alt="Project 4">
                    <div class="portfolio-overlay">
                        <h4>Project Title</h4>
                        <p>Quality INDUSTRY work</p>
                        <button class="btn btn-sm btn-light" onclick="openLightbox(this)"><i class="fas fa-expand"></i></button>
                    </div>
                </div>
                <div class="portfolio-item" data-category="all">
                    <img src="https://picsum.photos/seed/IMG_SEED-work5/600/400" alt="Project 5">
                    <div class="portfolio-overlay">
                        <h4>Project Title</h4>
                        <p>Quality INDUSTRY work</p>
                        <button class="btn btn-sm btn-light" onclick="openLightbox(this)"><i class="fas fa-expand"></i></button>
                    </div>
                </div>
                <div class="portfolio-item" data-category="all">
                    <img src="https://picsum.photos/seed/IMG_SEED-work6/600/400" alt="Project 6">
                    <div class="portfolio-overlay">
                        <h4>Project Title</h4>
                        <p>Quality INDUSTRY work</p>
                        <button class="btn btn-sm btn-light" onclick="openLightbox(this)"><i class="fas fa-expand"></i></button>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <!-- Lightbox -->
    <div class="lightbox" id="lightbox">
        <button class="lightbox-close" onclick="closeLightbox()"><i class="fas fa-times"></i></button>
        <img src="" alt="Lightbox Image" id="lightbox-img">
    </div>

    <!-- Testimonials Section -->
    <section class="testimonials section section-dark" id="testimonials">
        <div class="container">
            <div class="section-header light">
                <span class="section-badge">Testimonials</span>
                <h2>What Our Clients Say</h2>
                <p>Don't just take our word for it</p>
            </div>
            <div class="testimonials-grid">
                <div class="testimonial-card">
                    <div class="testimonial-rating">
                        <i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i>
                    </div>
                    <p class="testimonial-text">"Absolutely outstanding service! The team was professional, punctual, and the quality of work exceeded our expectations. Highly recommend!"</p>
                    <div class="testimonial-author">
                        <img src="https://picsum.photos/seed/IMG_SEED-review1/100/100" alt="Client">
                        <div>
                            <strong>Sarah Johnson</strong>
                            <span>Homeowner</span>
                        </div>
                    </div>
                </div>
                <div class="testimonial-card">
                    <div class="testimonial-rating">
                        <i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i>
                    </div>
                    <p class="testimonial-text">"From start to finish, the experience was seamless. Fair pricing, excellent communication, and beautiful results. Will definitely use again!"</p>
                    <div class="testimonial-author">
                        <img src="https://picsum.photos/seed/IMG_SEED-review2/100/100" alt="Client">
                        <div>
                            <strong>Michael Chen</strong>
                            <span>Business Owner</span>
                        </div>
                    </div>
                </div>
                <div class="testimonial-card">
                    <div class="testimonial-rating">
                        <i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i><i class="fas fa-star"></i>
                    </div>
                    <p class="testimonial-text">"These folks are true professionals. They took the time to understand exactly what we needed and delivered beyond what we imagined."</p>
                    <div class="testimonial-author">
                        <img src="https://picsum.photos/seed/IMG_SEED-review3/100/100" alt="Client">
                        <div>
                            <strong>Emily Rodriguez</strong>
                            <span>Property Manager</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <!-- CTA Section -->
    <section class="cta-section">
        <div class="cta-bg" style="background-image: url('https://picsum.photos/seed/IMG_SEED-cta/1920/600')"></div>
        <div class="cta-overlay"></div>
        <div class="container">
            <div class="cta-content">
                <h2>Ready to Get Started?</h2>
                <p>Schedule your free consultation today and let's discuss your project.</p>
                <div class="cta-buttons">
                    <a href="https://calendly.com/corban-leadsprinter/new-meeting" target="_blank" class="btn btn-primary btn-lg"><i class="fas fa-calendar-check"></i> Book Free Consultation</a>
                    <a href="tel:817-403-2179" class="btn btn-outline-light btn-lg"><i class="fas fa-phone"></i> 817-403-2179</a>
                </div>
            </div>
        </div>
    </section>

    <!-- FAQ Section -->
    <section class="faq section" id="faq">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">FAQ</span>
                <h2>Frequently Asked Questions</h2>
                <p>Quick answers to common questions</p>
            </div>
            <div class="faq-grid">
                <div class="faq-item">
                    <button class="faq-question">
                        <span>How do I get a quote?</span>
                        <i class="fas fa-chevron-down"></i>
                    </button>
                    <div class="faq-answer">
                        <p>Getting a quote is easy! Simply call us at 817-403-2179 or schedule a free consultation through our online booking system. We'll assess your needs and provide a detailed, no-obligation estimate.</p>
                    </div>
                </div>
                <div class="faq-item">
                    <button class="faq-question">
                        <span>Are you licensed and insured?</span>
                        <i class="fas fa-chevron-down"></i>
                    </button>
                    <div class="faq-answer">
                        <p>Yes! We are fully licensed, bonded, and insured. We carry comprehensive liability insurance and workers' compensation coverage for your complete peace of mind.</p>
                    </div>
                </div>
                <div class="faq-item">
                    <button class="faq-question">
                        <span>What areas do you serve?</span>
                        <i class="fas fa-chevron-down"></i>
                    </button>
                    <div class="faq-answer">
                        <p>We proudly serve the greater metropolitan area and surrounding communities. Contact us to confirm service availability in your specific location.</p>
                    </div>
                </div>
                <div class="faq-item">
                    <button class="faq-question">
                        <span>Do you offer warranties?</span>
                        <i class="fas fa-chevron-down"></i>
                    </button>
                    <div class="faq-answer">
                        <p>Absolutely! We stand behind our work with comprehensive warranties. Specific warranty terms vary by service type and will be clearly outlined in your service agreement.</p>
                    </div>
                </div>
                <div class="faq-item">
                    <button class="faq-question">
                        <span>What payment methods do you accept?</span>
                        <i class="fas fa-chevron-down"></i>
                    </button>
                    <div class="faq-answer">
                        <p>We accept all major credit cards, checks, and bank transfers. Financing options may be available for larger projects. We'll discuss payment terms during your consultation.</p>
                    </div>
                </div>
                <div class="faq-item">
                    <button class="faq-question">
                        <span>How quickly can you start?</span>
                        <i class="fas fa-chevron-down"></i>
                    </button>
                    <div class="faq-answer">
                        <p>Our scheduling depends on current workload, but we typically can begin within 1-2 weeks for most projects. Emergency services are available for urgent situations.</p>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <!-- Contact Section -->
    <section class="contact section section-alt" id="contact">
        <div class="container">
            <div class="section-header">
                <span class="section-badge">Contact Us</span>
                <h2>Get In Touch</h2>
                <p>Ready to start your project? Reach out today!</p>
            </div>
            <div class="contact-grid">
                <div class="contact-info-card">
                    <h3>Contact Information</h3>
                    <div class="contact-info-item">
                        <i class="fas fa-phone"></i>
                        <div>
                            <strong>Phone</strong>
                            <a href="tel:817-403-2179">817-403-2179</a>
                        </div>
                    </div>
                    <div class="contact-info-item">
                        <i class="fas fa-envelope"></i>
                        <div>
                            <strong>Email</strong>
                            <a href="mailto:info@example.com">info@example.com</a>
                        </div>
                    </div>
                    <div class="contact-info-item">
                        <i class="fas fa-clock"></i>
                        <div>
                            <strong>Hours</strong>
                            <span>Mon-Fri: 8am - 6pm<br>Sat: 9am - 2pm</span>
                        </div>
                    </div>
                    <div class="contact-info-item">
                        <i class="fas fa-map-marker-alt"></i>
                        <div>
                            <strong>Service Area</strong>
                            <span>Greater Metro Area</span>
                        </div>
                    </div>
                    <div class="contact-social">
                        <a href="#" aria-label="Facebook"><i class="fab fa-facebook-f"></i></a>
                        <a href="#" aria-label="Instagram"><i class="fab fa-instagram"></i></a>
                        <a href="#" aria-label="LinkedIn"><i class="fab fa-linkedin-in"></i></a>
                        <a href="#" aria-label="Yelp"><i class="fab fa-yelp"></i></a>
                    </div>
                    <a href="https://calendly.com/corban-leadsprinter/new-meeting" target="_blank" class="btn btn-primary btn-block"><i class="fas fa-calendar-check"></i> Book Online</a>
                </div>
                <div class="contact-form-card">
                    <h3>Send Us a Message</h3>
                    <form action="https://formspree.io/f/xojeqvng" method="POST" class="contact-form">
                        <div class="form-row">
                            <div class="form-group">
                                <label for="name">Full Name *</label>
                                <input type="text" id="name" name="name" required placeholder="John Smith">
                            </div>
                            <div class="form-group">
                                <label for="phone">Phone Number</label>
                                <input type="tel" id="phone" name="phone" placeholder="(555) 123-4567">
                            </div>
                        </div>
                        <div class="form-group">
                            <label for="email">Email Address *</label>
                            <input type="email" id="email" name="email" required placeholder="john@example.com">
                        </div>
                        <div class="form-group">
                            <label for="service">Service Needed</label>
                            <select id="service" name="service">
                                <option value="">Select a service...</option>
                                <option value="consultation">Free Consultation</option>
                                <option value="quote">Request Quote</option>
                                <option value="service">Schedule Service</option>
                                <option value="other">Other</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label for="message">Message *</label>
                            <textarea id="message" name="message" rows="4" required placeholder="Tell us about your project..."></textarea>
                        </div>
                        <button type="submit" class="btn btn-primary btn-block"><i class="fas fa-paper-plane"></i> Send Message</button>
                    </form>
                </div>
            </div>
        </div>
    </section>

    <!-- Footer -->
    <footer class="footer">
        <div class="container">
            <div class="footer-grid">
                <div class="footer-brand">
                    <a href="#" class="footer-logo">DISPLAY_NAME</a>
                    <p>Professional INDUSTRY services you can trust. Quality workmanship, fair pricing, and customer satisfaction guaranteed.</p>
                    <div class="footer-social">
                        <a href="#" aria-label="Facebook"><i class="fab fa-facebook-f"></i></a>
                        <a href="#" aria-label="Instagram"><i class="fab fa-instagram"></i></a>
                        <a href="#" aria-label="LinkedIn"><i class="fab fa-linkedin-in"></i></a>
                    </div>
                </div>
                <div class="footer-links">
                    <h4>Quick Links</h4>
                    <ul>
                        <li><a href="#services">Services</a></li>
                        <li><a href="#about">About Us</a></li>
                        <li><a href="#portfolio">Portfolio</a></li>
                        <li><a href="#testimonials">Reviews</a></li>
                        <li><a href="#contact">Contact</a></li>
                    </ul>
                </div>
                <div class="footer-links">
                    <h4>Services</h4>
                    <ul>
                        FOOTER_SERVICES
                    </ul>
                </div>
                <div class="footer-contact">
                    <h4>Contact Us</h4>
                    <p><i class="fas fa-phone"></i> <a href="tel:817-403-2179">817-403-2179</a></p>
                    <p><i class="fas fa-envelope"></i> <a href="mailto:info@example.com">info@example.com</a></p>
                    <p><i class="fas fa-clock"></i> Mon-Fri: 8am - 6pm</p>
                    <a href="https://calendly.com/corban-leadsprinter/new-meeting" target="_blank" class="btn btn-primary btn-sm">Book Now</a>
                </div>
            </div>
            <div class="footer-bottom">
                <p>&copy; 2024 DISPLAY_NAME. All rights reserved.</p>
                <p>Website by <a href="https://60minutesites.com" target="_blank">60 Minute Sites</a></p>
            </div>
        </div>
    </footer>

    <script src="script.js"></script>
</body>
</html>
HTMLEOF

    # Replace placeholders in HTML
    sed -i '' "s/DISPLAY_NAME/$display_name/g" "$template_dir/index.html"
    sed -i '' "s/INDUSTRY/$industry/g" "$template_dir/index.html"
    sed -i '' "s/CATEGORY/$category/g" "$template_dir/index.html"
    sed -i '' "s/TAGLINE/$tagline/g" "$template_dir/index.html"
    sed -i '' "s/IMG_SEED/$img_seed/g" "$template_dir/index.html"

    # Generate services HTML
    local services_html=""
    local footer_services=""
    IFS='||' read -ra SERVICE_ARRAY <<< "$services_data"
    for service in "${SERVICE_ARRAY[@]}"; do
        IFS='|' read -r icon title desc <<< "$service"
        services_html+="                <div class=\"service-card\">
                    <div class=\"service-icon\"><i class=\"fas fa-$icon\"></i></div>
                    <h3>$title</h3>
                    <p>$desc</p>
                    <a href=\"#contact\" class=\"service-link\">Learn More <i class=\"fas fa-arrow-right\"></i></a>
                </div>
"
        footer_services+="                        <li><a href=\"#services\">$title</a></li>
"
    done

    # Insert services into HTML
    sed -i '' "s|SERVICES_HTML|$services_html|g" "$template_dir/index.html"
    sed -i '' "s|FOOTER_SERVICES|$footer_services|g" "$template_dir/index.html"

    # Generate styles.css
    cat > "$template_dir/styles.css" << CSSEOF
/* $display_name - $style_name Theme */
/* Professional Marketing Template by 60 Minute Sites */

:root {
    --primary: $primary;
    --secondary: $secondary;
    --accent: $accent;
    --bg: $background;
    --bg-alt: ${background}ee;
    --text: $text_dark;
    --text-light: $text_light;
    --white: #ffffff;
    --black: #000000;
    --shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06);
    --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05);
    --radius: 8px;
    --radius-lg: 16px;
    --transition: all 0.3s ease;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
.container { max-width: 1200px; margin: 0 auto; padding: 0 24px; }
img { max-width: 100%; height: auto; }
a { color: var(--primary); text-decoration: none; transition: var(--transition); }

/* Buttons */
.btn { display: inline-flex; align-items: center; gap: 8px; padding: 12px 24px; border-radius: var(--radius); font-weight: 600; font-size: 0.95rem; border: 2px solid transparent; cursor: pointer; transition: var(--transition); text-decoration: none; }
.btn i { font-size: 0.9em; }
.btn-sm { padding: 8px 16px; font-size: 0.875rem; }
.btn-lg { padding: 16px 32px; font-size: 1.1rem; }
.btn-block { width: 100%; justify-content: center; }
.btn-primary { background: var(--accent); color: var(--primary); border-color: var(--accent); }
.btn-primary:hover { background: transparent; color: var(--accent); transform: translateY(-2px); }
.btn-outline { background: transparent; color: var(--primary); border-color: var(--primary); }
.btn-outline:hover { background: var(--primary); color: var(--white); }
.btn-outline-light { background: transparent; color: var(--white); border-color: var(--white); }
.btn-outline-light:hover { background: var(--white); color: var(--primary); }
.btn-light { background: var(--white); color: var(--primary); }

/* Header */
.header { position: fixed; top: 0; left: 0; right: 0; z-index: 1000; padding: 16px 0; transition: var(--transition); }
.header.scrolled { background: var(--primary); box-shadow: var(--shadow); padding: 12px 0; }
.nav { display: flex; align-items: center; justify-content: space-between; }
.logo { font-size: 1.5rem; font-weight: 700; color: var(--white); }
.nav-links { display: flex; list-style: none; gap: 32px; }
.nav-links a { color: var(--white); font-weight: 500; opacity: 0.9; }
.nav-links a:hover { opacity: 1; color: var(--accent); }
.nav-actions { display: flex; gap: 12px; }
.mobile-toggle { display: none; background: none; border: none; cursor: pointer; padding: 8px; }
.mobile-toggle span { display: block; width: 24px; height: 2px; background: var(--white); margin: 5px 0; transition: var(--transition); }

/* Hero */
.hero { position: relative; min-height: 100vh; display: flex; align-items: center; padding: 120px 0 80px; overflow: hidden; }
.hero-bg { position: absolute; inset: 0; background-size: cover; background-position: center; }
.hero-overlay { position: absolute; inset: 0; background: linear-gradient(135deg, rgba(0,0,0,0.8) 0%, rgba(0,0,0,0.5) 100%); }
.hero-content { position: relative; z-index: 1; text-align: center; color: var(--white); max-width: 800px; margin: 0 auto; }
.hero-badge { display: inline-block; background: var(--accent); color: var(--primary); padding: 8px 20px; border-radius: 50px; font-size: 0.875rem; font-weight: 600; margin-bottom: 24px; }
.hero h1 { font-size: clamp(2.5rem, 6vw, 4rem); font-weight: 800; margin-bottom: 16px; line-height: 1.1; }
.hero-subtitle { font-size: 1.25rem; opacity: 0.9; max-width: 600px; margin: 0 auto 32px; }
.hero-buttons { display: flex; gap: 16px; justify-content: center; flex-wrap: wrap; margin-bottom: 40px; }
.hero-features { display: flex; gap: 32px; justify-content: center; flex-wrap: wrap; }
.hero-feature { display: flex; align-items: center; gap: 8px; font-size: 0.95rem; }
.hero-feature i { color: var(--accent); }
.scroll-indicator { position: absolute; bottom: 32px; left: 50%; transform: translateX(-50%); color: var(--white); font-size: 1.5rem; animation: bounce 2s infinite; }
@keyframes bounce { 0%, 20%, 50%, 80%, 100% { transform: translateX(-50%) translateY(0); } 40% { transform: translateX(-50%) translateY(-10px); } 60% { transform: translateX(-50%) translateY(-5px); } }

/* Sections */
.section { padding: 100px 0; }
.section-alt { background: var(--bg-alt); }
.section-dark { background: var(--primary); color: var(--white); padding: 80px 0; }
.section-header { text-align: center; max-width: 600px; margin: 0 auto 60px; }
.section-header.light { color: var(--white); }
.section-header.light .section-badge { background: var(--accent); color: var(--primary); }
.section-badge { display: inline-block; background: var(--primary); color: var(--white); padding: 6px 16px; border-radius: 50px; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; }
.section-header h2 { font-size: 2.5rem; font-weight: 700; margin-bottom: 16px; color: inherit; }
.section-header p { color: var(--text-light); font-size: 1.1rem; }
.section-header.light p { color: rgba(255,255,255,0.8); }

/* Services */
.services-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 24px; }
.service-card { background: var(--white); padding: 32px; border-radius: var(--radius-lg); box-shadow: var(--shadow); transition: var(--transition); }
.service-card:hover { transform: translateY(-8px); box-shadow: var(--shadow-lg); }
.service-icon { width: 64px; height: 64px; background: linear-gradient(135deg, var(--primary), var(--secondary)); color: var(--white); border-radius: var(--radius); display: flex; align-items: center; justify-content: center; font-size: 1.5rem; margin-bottom: 20px; }
.service-card h3 { font-size: 1.25rem; margin-bottom: 12px; color: var(--primary); }
.service-card p { color: var(--text-light); margin-bottom: 16px; }
.service-link { color: var(--accent); font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }
.service-link:hover { gap: 12px; }
.services-cta { text-align: center; margin-top: 48px; padding-top: 48px; border-top: 1px solid rgba(0,0,0,0.1); }
.services-cta p { margin-bottom: 16px; color: var(--text-light); }

/* Stats */
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 32px; text-align: center; }
.stat-item { padding: 24px; }
.stat-number { font-size: 3rem; font-weight: 800; color: var(--accent); line-height: 1; }
.stat-number::after { content: '+'; }
.stat-label { font-size: 0.95rem; opacity: 0.9; margin-top: 8px; }

/* About */
.about-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 60px; align-items: center; }
.about-image { position: relative; }
.about-image img { border-radius: var(--radius-lg); box-shadow: var(--shadow-lg); }
.about-badge { position: absolute; bottom: -20px; right: -20px; background: var(--accent); color: var(--primary); padding: 24px; border-radius: var(--radius); text-align: center; box-shadow: var(--shadow-lg); }
.badge-number { display: block; font-size: 2.5rem; font-weight: 800; line-height: 1; }
.badge-text { font-size: 0.875rem; font-weight: 600; }
.about-content .lead { font-size: 1.1rem; color: var(--primary); font-weight: 500; margin-bottom: 16px; }
.about-list { list-style: none; margin: 24px 0; }
.about-list li { display: flex; align-items: center; gap: 12px; padding: 8px 0; }
.about-list i { color: var(--accent); }

/* Process */
.process-grid { display: flex; align-items: flex-start; justify-content: center; gap: 0; flex-wrap: wrap; }
.process-step { text-align: center; padding: 24px; flex: 1; min-width: 200px; max-width: 250px; position: relative; }
.process-number { position: absolute; top: 0; right: 20px; font-size: 4rem; font-weight: 800; color: var(--primary); opacity: 0.1; line-height: 1; }
.process-icon { width: 80px; height: 80px; background: var(--primary); color: var(--white); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.5rem; margin: 0 auto 20px; }
.process-step h3 { font-size: 1.1rem; margin-bottom: 8px; }
.process-step p { font-size: 0.95rem; color: var(--text-light); }
.process-connector { width: 60px; height: 2px; background: var(--primary); opacity: 0.2; margin-top: 64px; }

/* Portfolio */
.portfolio-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }
.portfolio-item { position: relative; border-radius: var(--radius-lg); overflow: hidden; aspect-ratio: 3/2; }
.portfolio-item img { width: 100%; height: 100%; object-fit: cover; transition: var(--transition); }
.portfolio-overlay { position: absolute; inset: 0; background: linear-gradient(to top, rgba(0,0,0,0.8), transparent); display: flex; flex-direction: column; justify-content: flex-end; padding: 24px; opacity: 0; transition: var(--transition); }
.portfolio-item:hover .portfolio-overlay { opacity: 1; }
.portfolio-item:hover img { transform: scale(1.05); }
.portfolio-overlay h4 { color: var(--white); font-size: 1.1rem; margin-bottom: 4px; }
.portfolio-overlay p { color: rgba(255,255,255,0.8); font-size: 0.875rem; margin-bottom: 12px; }

/* Lightbox */
.lightbox { position: fixed; inset: 0; background: rgba(0,0,0,0.95); z-index: 2000; display: none; align-items: center; justify-content: center; padding: 40px; }
.lightbox.active { display: flex; }
.lightbox-close { position: absolute; top: 20px; right: 20px; background: none; border: none; color: var(--white); font-size: 2rem; cursor: pointer; }
.lightbox img { max-width: 90%; max-height: 90%; border-radius: var(--radius); }

/* Testimonials */
.testimonials-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }
.testimonial-card { background: var(--white); padding: 32px; border-radius: var(--radius-lg); box-shadow: var(--shadow); }
.testimonial-rating { color: #fbbf24; margin-bottom: 16px; }
.testimonial-text { font-size: 1rem; color: var(--text); margin-bottom: 20px; font-style: italic; }
.testimonial-author { display: flex; align-items: center; gap: 12px; }
.testimonial-author img { width: 48px; height: 48px; border-radius: 50%; object-fit: cover; }
.testimonial-author strong { display: block; color: var(--primary); }
.testimonial-author span { font-size: 0.875rem; color: var(--text-light); }

/* CTA Section */
.cta-section { position: relative; padding: 100px 0; overflow: hidden; }
.cta-bg { position: absolute; inset: 0; background-size: cover; background-position: center; }
.cta-overlay { position: absolute; inset: 0; background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%); opacity: 0.95; }
.cta-content { position: relative; z-index: 1; text-align: center; color: var(--white); max-width: 600px; margin: 0 auto; }
.cta-content h2 { font-size: 2.5rem; margin-bottom: 16px; }
.cta-content p { font-size: 1.1rem; opacity: 0.9; margin-bottom: 32px; }
.cta-buttons { display: flex; gap: 16px; justify-content: center; flex-wrap: wrap; }

/* FAQ */
.faq-grid { max-width: 800px; margin: 0 auto; }
.faq-item { border-bottom: 1px solid rgba(0,0,0,0.1); }
.faq-question { width: 100%; display: flex; justify-content: space-between; align-items: center; padding: 20px 0; background: none; border: none; cursor: pointer; text-align: left; font-size: 1.1rem; font-weight: 600; color: var(--primary); }
.faq-question i { transition: var(--transition); color: var(--accent); }
.faq-item.active .faq-question i { transform: rotate(180deg); }
.faq-answer { max-height: 0; overflow: hidden; transition: max-height 0.3s ease; }
.faq-item.active .faq-answer { max-height: 200px; }
.faq-answer p { padding-bottom: 20px; color: var(--text-light); }

/* Contact */
.contact-grid { display: grid; grid-template-columns: 1fr 2fr; gap: 40px; }
.contact-info-card, .contact-form-card { background: var(--white); padding: 40px; border-radius: var(--radius-lg); box-shadow: var(--shadow); }
.contact-info-card h3, .contact-form-card h3 { font-size: 1.5rem; margin-bottom: 24px; color: var(--primary); }
.contact-info-item { display: flex; gap: 16px; margin-bottom: 24px; }
.contact-info-item i { width: 48px; height: 48px; background: var(--primary); color: var(--white); border-radius: var(--radius); display: flex; align-items: center; justify-content: center; font-size: 1.1rem; }
.contact-info-item strong { display: block; color: var(--primary); margin-bottom: 4px; }
.contact-info-item a, .contact-info-item span { color: var(--text-light); }
.contact-social { display: flex; gap: 12px; margin: 24px 0; }
.contact-social a { width: 40px; height: 40px; background: var(--bg); border-radius: 50%; display: flex; align-items: center; justify-content: center; color: var(--primary); transition: var(--transition); }
.contact-social a:hover { background: var(--primary); color: var(--white); }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.form-group { margin-bottom: 20px; }
.form-group label { display: block; margin-bottom: 8px; font-weight: 500; color: var(--primary); }
.form-group input, .form-group select, .form-group textarea { width: 100%; padding: 14px 16px; border: 2px solid #e5e7eb; border-radius: var(--radius); font-size: 1rem; font-family: inherit; transition: var(--transition); }
.form-group input:focus, .form-group select:focus, .form-group textarea:focus { outline: none; border-color: var(--accent); }

/* Footer */
.footer { background: var(--primary); color: var(--white); padding: 80px 0 24px; }
.footer-grid { display: grid; grid-template-columns: 2fr 1fr 1fr 1.5fr; gap: 40px; margin-bottom: 60px; }
.footer-logo { font-size: 1.5rem; font-weight: 700; color: var(--white); margin-bottom: 16px; display: inline-block; }
.footer-brand p { opacity: 0.8; margin-bottom: 20px; }
.footer-social { display: flex; gap: 12px; }
.footer-social a { width: 40px; height: 40px; background: rgba(255,255,255,0.1); border-radius: 50%; display: flex; align-items: center; justify-content: center; color: var(--white); transition: var(--transition); }
.footer-social a:hover { background: var(--accent); color: var(--primary); }
.footer-links h4, .footer-contact h4 { font-size: 1.1rem; margin-bottom: 20px; }
.footer-links ul { list-style: none; }
.footer-links a { color: rgba(255,255,255,0.8); display: block; padding: 6px 0; }
.footer-links a:hover { color: var(--accent); }
.footer-contact p { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; opacity: 0.9; }
.footer-contact a { color: var(--white); }
.footer-bottom { border-top: 1px solid rgba(255,255,255,0.1); padding-top: 24px; display: flex; justify-content: space-between; opacity: 0.7; font-size: 0.875rem; }
.footer-bottom a { color: var(--accent); }

/* Responsive */
@media (max-width: 1024px) {
    .about-grid, .contact-grid { grid-template-columns: 1fr; }
    .footer-grid { grid-template-columns: 1fr 1fr; }
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
    .portfolio-grid { grid-template-columns: repeat(2, 1fr); }
    .testimonials-grid { grid-template-columns: 1fr; }
}

@media (max-width: 768px) {
    .nav-links, .nav-actions { display: none; }
    .nav-links.active { display: flex; flex-direction: column; position: absolute; top: 100%; left: 0; right: 0; background: var(--primary); padding: 24px; gap: 16px; }
    .mobile-toggle { display: block; }
    .mobile-toggle.active span:nth-child(1) { transform: rotate(45deg) translate(5px, 5px); }
    .mobile-toggle.active span:nth-child(2) { opacity: 0; }
    .mobile-toggle.active span:nth-child(3) { transform: rotate(-45deg) translate(5px, -5px); }
    .hero-buttons { flex-direction: column; align-items: center; }
    .hero-features { flex-direction: column; gap: 12px; }
    .process-connector { display: none; }
    .process-grid { flex-direction: column; align-items: center; }
    .portfolio-grid { grid-template-columns: 1fr; }
    .form-row { grid-template-columns: 1fr; }
    .footer-grid { grid-template-columns: 1fr; text-align: center; }
    .footer-social, .contact-social { justify-content: center; }
    .footer-bottom { flex-direction: column; text-align: center; gap: 8px; }
    .cta-buttons { flex-direction: column; align-items: center; }
    .section-header h2 { font-size: 2rem; }
}
CSSEOF

    # Generate script.js
    cat > "$template_dir/script.js" << 'JSEOF'
// Enhanced Template JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Mobile menu
    const toggle = document.getElementById('mobile-toggle');
    const navLinks = document.getElementById('nav-links');
    if (toggle) {
        toggle.addEventListener('click', () => {
            toggle.classList.toggle('active');
            navLinks.classList.toggle('active');
        });
    }

    // Header scroll effect
    const header = document.getElementById('header');
    window.addEventListener('scroll', () => {
        header.classList.toggle('scrolled', window.scrollY > 50);
    });

    // Smooth scroll
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            const target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                navLinks.classList.remove('active');
                toggle.classList.remove('active');
            }
        });
    });

    // Animated counters
    const counters = document.querySelectorAll('.stat-number');
    const animateCounter = (counter) => {
        const target = parseInt(counter.dataset.count);
        const duration = 2000;
        const step = target / (duration / 16);
        let current = 0;
        const update = () => {
            current += step;
            if (current < target) {
                counter.textContent = Math.floor(current);
                requestAnimationFrame(update);
            } else {
                counter.textContent = target;
            }
        };
        update();
    };

    const statsObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                counters.forEach(animateCounter);
                statsObserver.disconnect();
            }
        });
    }, { threshold: 0.5 });

    const statsSection = document.querySelector('.stats');
    if (statsSection) statsObserver.observe(statsSection);

    // FAQ accordion
    document.querySelectorAll('.faq-question').forEach(btn => {
        btn.addEventListener('click', () => {
            const item = btn.parentElement;
            const wasActive = item.classList.contains('active');
            document.querySelectorAll('.faq-item').forEach(i => i.classList.remove('active'));
            if (!wasActive) item.classList.add('active');
        });
    });

    // Form handling
    const form = document.querySelector('.contact-form');
    if (form) {
        form.addEventListener('submit', function() {
            const btn = form.querySelector('button[type="submit"]');
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...';
            btn.disabled = true;
        });
    }
});

// Lightbox
function openLightbox(btn) {
    const img = btn.closest('.portfolio-item').querySelector('img');
    const lightbox = document.getElementById('lightbox');
    const lightboxImg = document.getElementById('lightbox-img');
    lightboxImg.src = img.src;
    lightbox.classList.add('active');
}

function closeLightbox() {
    document.getElementById('lightbox').classList.remove('active');
}

document.getElementById('lightbox').addEventListener('click', function(e) {
    if (e.target === this) closeLightbox();
});

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeLightbox();
});
JSEOF

    echo "  Created: $padded_num-$name"
}

# ============================================
# CATEGORY DEFINITIONS WITH SERVICES
# ============================================

generate_construction() {
    echo "Generating Construction templates..."
    local services="hammer|New Construction|Custom homes and commercial buildings built to your exact specifications.||hard-hat|Renovations|Complete renovation services to transform your existing space.||ruler-combined|Additions|Seamless home additions that expand your living space.||project-diagram|Project Management|Full oversight from concept to completion."
    local names=("builder-pro" "foundation-strong" "steel-frame" "hard-hat-heroes" "concrete-kings" "blueprint-masters" "site-works" "construct-elite" "build-right" "hammer-time" "framework-pro" "solid-ground" "rise-up-builds" "premier-construct" "urban-builders" "quality-craft" "pro-build" "master-construct" "summit-builders" "apex-construction")
    for i in {1..20}; do
        generate_enhanced_template "construction" $i "${names[$i-1]}" "Construction" "Building dreams into reality with quality craftsmanship and attention to detail" "$services" "construction"
    done
}

generate_plumber() {
    echo "Generating Plumber templates..."
    local services="wrench|Pipe Repair|Fast, reliable repairs for leaks, bursts, and damaged pipes.||shower|Drain Cleaning|Professional drain clearing and maintenance services.||fire|Water Heaters|Expert installation and repair of all water heater types.||phone-alt|Emergency Service|24/7 emergency plumbing when you need it most."
    local names=("flow-masters" "pipe-dreams" "drain-pro" "water-works" "plumb-perfect" "quick-fix-plumbing" "reliable-pipes" "pro-plumb" "flush-right" "pipe-experts" "clear-drains" "master-plumbers" "flow-tech" "aqua-pro" "pipeline-pros" "drain-experts" "water-wise" "plumb-line" "pipe-masters" "blue-flow")
    for i in {1..20}; do
        generate_enhanced_template "plumber" $i "${names[$i-1]}" "Plumbing" "Expert plumbing solutions for your home and business" "$services" "plumbing"
    done
}

generate_electrician() {
    echo "Generating Electrician templates..."
    local services="bolt|Electrical Repairs|Fast diagnosis and repair of all electrical issues.||lightbulb|Lighting|Indoor and outdoor lighting design and installation.||plug|Panel Upgrades|Modernize your electrical panel for safety and capacity.||home|Wiring Services|Complete wiring for new construction and renovations."
    local names=("spark-pro" "power-up" "wire-wizards" "volt-masters" "electric-elite" "current-solutions" "bright-spark" "power-pro" "circuit-masters" "wired-right" "amp-up" "electric-edge" "shock-free" "power-flow" "light-up" "pro-electric" "circuit-pro" "voltage-experts" "wire-works" "electric-pros")
    for i in {1..20}; do
        generate_enhanced_template "electrician" $i "${names[$i-1]}" "Electrical" "Safe, reliable electrical services for residential and commercial properties" "$services" "electrical"
    done
}

generate_painter() {
    echo "Generating Painter templates..."
    local services="paint-roller|Interior Painting|Beautiful interior finishes for every room in your home.||home|Exterior Painting|Weather-resistant exterior coatings that protect and beautify.||brush|Cabinet Refinishing|Give your kitchen cabinets a stunning new look.||palette|Specialty Finishes|Textures, faux finishes, and decorative painting techniques."
    local names=("color-masters" "fresh-coat" "paint-perfect" "brush-strokes" "prime-painters" "color-pro" "smooth-finish" "paint-pros" "vibrant-walls" "elite-painters" "true-colors" "perfect-paint" "brush-masters" "color-craft" "pro-painters" "painted-right" "quality-coat" "paint-works" "master-painters" "color-edge")
    for i in {1..20}; do
        generate_enhanced_template "painter" $i "${names[$i-1]}" "Painting" "Transform your space with professional painting services" "$services" "painting"
    done
}

generate_hvac() {
    echo "Generating HVAC templates..."
    local services="snowflake|AC Repair|Fast air conditioning repair and maintenance services.||fire-alt|Heating|Furnace repair, installation, and maintenance.||wind|Air Quality|Improve your indoor air with advanced filtration systems.||fan|System Install|New HVAC system design and professional installation."
    local names=("climate-control" "air-masters" "cool-comfort" "heat-pro" "air-flow-experts" "comfort-zone" "climate-pro" "air-quality" "temp-masters" "cool-air" "heat-and-cool" "air-experts" "climate-solutions" "pro-hvac" "comfort-air" "air-pro" "climate-masters" "cool-zone" "air-comfort" "perfect-temp")
    for i in {1..20}; do
        generate_enhanced_template "hvac" $i "${names[$i-1]}" "HVAC" "Complete heating, cooling, and air quality solutions" "$services" "hvac"
    done
}

generate_cleaning() {
    echo "Generating Cleaning templates..."
    local services="home|Residential|Thorough home cleaning tailored to your specific needs.||building|Commercial|Professional office and business cleaning services.||sparkles|Deep Cleaning|Intensive cleaning for a fresh, healthy start.||truck-moving|Move In/Out|Complete cleaning for smooth property transitions."
    local names=("sparkle-clean" "fresh-start" "clean-pro" "spotless" "pure-clean" "shine-bright" "clean-masters" "fresh-clean" "pro-cleaners" "dust-free" "crystal-clean" "clean-sweep" "pristine-pro" "fresh-space" "clean-solutions" "tidy-pro" "gleam-team" "clean-edge" "pure-shine" "master-clean")
    for i in {1..20}; do
        generate_enhanced_template "cleaning" $i "${names[$i-1]}" "Cleaning" "Professional cleaning services that make your space shine" "$services" "cleaning"
    done
}

generate_pest_control() {
    echo "Generating Pest Control templates..."
    local services="bug|General Pest|Eliminate common household pests quickly and effectively.||shield-alt|Rodent Control|Effective mouse and rat removal and prevention.||spider|Insect Treatment|Specialized treatment for all types of insects.||home|Prevention Plans|Ongoing protection to keep pests away permanently."
    local names=("bug-free" "pest-pro" "no-more-pests" "critter-control" "pest-masters" "bug-busters" "pest-solutions" "safe-home" "pest-shield" "bug-out" "pest-free" "critter-pro" "pest-guard" "bug-master" "pest-experts" "control-pro" "pest-away" "bug-control" "safe-guard" "pest-defense")
    for i in {1..20}; do
        generate_enhanced_template "pest-control" $i "${names[$i-1]}" "Pest Control" "Keep your home and business pest-free with expert solutions" "$services" "pest-control"
    done
}

generate_salon() {
    echo "Generating Salon templates..."
    local services="cut|Haircuts|Precision cuts and trendy styles for all hair types.||palette|Color Services|Highlights, balayage, and full color transformations.||magic|Treatments|Keratin, deep conditioning, and repair treatments.||crown|Special Events|Bridal, prom, and special occasion styling."
    local names=("glamour-cuts" "style-studio" "hair-haven" "chic-salon" "beauty-bar" "luxe-locks" "salon-elite" "hair-masters" "style-pro" "glam-studio" "beauty-bliss" "hair-artistry" "salon-luxe" "style-haven" "glamour-studio" "hair-pro" "beauty-elite" "chic-cuts" "salon-style" "hair-luxe")
    for i in {1..20}; do
        generate_enhanced_template "salon" $i "${names[$i-1]}" "Salon" "Your destination for beautiful hair and exceptional service" "$services" "salon"
    done
}

generate_spa() {
    echo "Generating Spa templates..."
    local services="spa|Massage|Swedish, deep tissue, and hot stone massage therapy.||smile|Facials|Customized facials for radiant, healthy skin.||bath|Body Treatments|Luxurious wraps, scrubs, and detox treatments.||gift|Spa Packages|Complete wellness experiences to indulge and relax."
    local names=("serenity-spa" "bliss-retreat" "zen-haven" "pure-relaxation" "tranquil-touch" "spa-luxe" "calm-waters" "peaceful-spa" "harmony-haven" "spa-bliss" "serene-space" "relaxation-station" "zen-spa" "pure-spa" "tranquil-spa" "blissful-spa" "calm-spa" "peaceful-haven" "spa-serenity" "zen-retreat")
    for i in {1..20}; do
        generate_enhanced_template "spa" $i "${names[$i-1]}" "Spa" "Relax, rejuvenate, and restore at our tranquil retreat" "$services" "spa"
    done
}

generate_barber() {
    echo "Generating Barber templates..."
    local services="cut|Haircuts|Classic and contemporary cuts for the modern gentleman.||user|Beard Services|Expert beard trims, shaping, and hot towel shaves.||hot-tub|Traditional Shaves|Straight razor shaves with premium hot lather.||leaf|Treatments|Scalp treatments and premium hair care services."
    local names=("sharp-cuts" "classic-barber" "the-chop-shop" "gentlemans-cut" "blade-masters" "prime-cuts" "barber-pro" "clean-cuts" "style-barber" "edge-barber" "classic-cuts" "sharp-style" "pro-barber" "blade-pro" "gents-barber" "cut-masters" "style-edge" "barber-elite" "sharp-edge" "classic-style")
    for i in {1..20}; do
        generate_enhanced_template "barber" $i "${names[$i-1]}" "Barber" "Classic cuts and modern styles in a welcoming atmosphere" "$services" "barber"
    done
}

generate_massage() {
    echo "Generating Massage templates..."
    local services="hand-holding-heart|Swedish|Relaxing full-body massage for stress relief and wellness.||dumbbell|Deep Tissue|Targeted therapy for chronic muscle tension and pain.||fire-alt|Hot Stone|Heated basalt stones for deep relaxation and healing.||running|Sports Massage|Athletic recovery and performance enhancement therapy."
    local names=("healing-hands" "relax-restore" "touch-therapy" "wellness-massage" "calm-touch" "body-bliss" "massage-pro" "healing-touch" "restore-wellness" "peaceful-touch" "body-wellness" "massage-haven" "healing-therapy" "calm-hands" "touch-wellness" "body-restore" "massage-bliss" "healing-haven" "wellness-touch" "restore-massage")
    for i in {1..20}; do
        generate_enhanced_template "massage" $i "${names[$i-1]}" "Massage Therapy" "Therapeutic massage for relaxation, recovery, and wellness" "$services" "massage"
    done
}

generate_health_beauty() {
    echo "Generating Health & Beauty templates..."
    local services="hand-sparkles|Nail Services|Luxurious manicures, pedicures, and nail artistry.||smile|Skincare|Professional facials, peels, and skin treatments.||magic|Makeup|Expert makeup application for any occasion.||heart|Wellness|Holistic health and beauty treatments."
    local names=("glow-up" "beauty-wellness" "radiant-you" "pure-beauty" "health-glow" "beauty-pro" "wellness-beauty" "glow-pro" "radiant-beauty" "pure-glow" "health-radiance" "beauty-bliss" "wellness-glow" "glow-beauty" "radiant-health" "pure-wellness" "beauty-radiance" "health-bliss" "wellness-pro" "glow-wellness")
    for i in {1..20}; do
        generate_enhanced_template "health-beauty" $i "${names[$i-1]}" "Health and Beauty" "Your complete destination for health, beauty, and wellness" "$services" "beauty"
    done
}

generate_fitness() {
    echo "Generating Fitness templates..."
    local services="user-friends|Personal Training|One-on-one coaching customized to your goals.||users|Group Classes|Energizing group fitness for all levels.||dumbbell|Strength Training|Build muscle, increase power, transform your body.||heartbeat|Cardio Programs|Boost endurance and achieve your fitness goals."
    local names=("peak-performance" "fit-life" "power-gym" "strength-zone" "fitness-pro" "active-life" "gym-masters" "fit-zone" "power-pro" "strength-pro" "fitness-elite" "active-fit" "gym-pro" "peak-fitness" "power-zone" "strength-elite" "fitness-zone" "active-pro" "gym-elite" "peak-pro")
    for i in {1..20}; do
        generate_enhanced_template "fitness" $i "${names[$i-1]}" "Fitness" "Transform your body and mind with expert fitness coaching" "$services" "fitness"
    done
}

generate_business_services() {
    echo "Generating Business Services templates..."
    local services="chart-line|Consulting|Expert business strategy and advisory services.||bullhorn|Marketing|Digital marketing and brand growth solutions.||cogs|Operations|Streamline and optimize your business operations.||tasks|Planning|Strategic planning for sustainable long-term success."
    local names=("pro-solutions" "business-elite" "corporate-pro" "success-partners" "business-masters" "pro-business" "elite-solutions" "corporate-edge" "success-pro" "business-pro" "solutions-elite" "corporate-masters" "success-edge" "pro-corporate" "elite-business" "solutions-pro" "business-edge" "corporate-success" "pro-elite" "business-solutions")
    for i in {1..20}; do
        generate_enhanced_template "business-services" $i "${names[$i-1]}" "Business Services" "Professional solutions to help your company thrive" "$services" "business"
    done
}

generate_real_estate() {
    echo "Generating Real Estate templates..."
    local services="home|Home Buying|Expert guidance through your home buying journey.||dollar-sign|Home Selling|Get top dollar for your property with our expertise.||key|Rentals|Find the perfect rental property for your needs.||building|Property Management|Full-service property management solutions."
    local names=("prime-properties" "dream-homes" "elite-realty" "home-masters" "property-pro" "real-estate-elite" "dream-realty" "prime-realty" "home-pro" "property-elite" "realty-masters" "dream-properties" "elite-properties" "home-realty" "property-masters" "prime-homes" "realty-pro" "dream-elite" "property-homes" "elite-homes")
    for i in {1..20}; do
        generate_enhanced_template "real-estate" $i "${names[$i-1]}" "Real Estate" "Find your dream home with our expert guidance" "$services" "real-estate"
    done
}

generate_insurance() {
    echo "Generating Insurance templates..."
    local services="home|Home Insurance|Comprehensive protection for your home and belongings.||car|Auto Insurance|Complete coverage for all your vehicles.||heart|Life Insurance|Secure your family's financial future.||briefcase|Business Insurance|Protect your business with comprehensive coverage."
    local names=("secure-insurance" "shield-pro" "coverage-masters" "safe-guard-insurance" "protect-pro" "insurance-elite" "secure-shield" "coverage-pro" "safe-insurance" "shield-masters" "protect-elite" "insurance-pro" "secure-pro" "coverage-elite" "safe-shield" "protect-insurance" "shield-elite" "secure-coverage" "safe-pro" "insurance-masters")
    for i in {1..20}; do
        generate_enhanced_template "insurance" $i "${names[$i-1]}" "Insurance" "Protect what matters most with comprehensive coverage" "$services" "insurance"
    done
}

generate_mortgage() {
    echo "Generating Mortgage templates..."
    local services="home|Home Loans|Competitive rates to make homeownership a reality.||sync|Refinancing|Lower your rate or access your home equity.||hard-hat|Construction Loans|Finance your custom home build project.||clipboard-check|Pre-Approval|Get pre-approved and shop with confidence."
    local names=("home-loans-pro" "mortgage-masters" "finance-home" "loan-pro" "mortgage-elite" "home-finance" "loan-masters" "mortgage-pro" "finance-pro" "home-mortgage" "loan-elite" "mortgage-solutions" "finance-elite" "home-loans" "loan-solutions" "mortgage-home" "finance-masters" "home-solutions" "loan-finance" "mortgage-finance")
    for i in {1..20}; do
        generate_enhanced_template "mortgage" $i "${names[$i-1]}" "Mortgage" "Making homeownership possible with the right solutions" "$services" "mortgage"
    done
}

generate_architect() {
    echo "Generating Architect templates..."
    local services="home|Residential Design|Custom homes designed for your unique lifestyle.||building|Commercial Design|Functional spaces that drive business success.||pencil-ruler|Renovations|Transform existing spaces with expert design.||leaf|Sustainable Design|Eco-friendly architecture for a better future."
    local names=("design-masters" "blueprint-pro" "arch-studio" "structure-elite" "design-pro" "architect-elite" "blueprint-masters" "studio-arch" "structure-pro" "design-elite" "arch-pro" "blueprint-elite" "studio-design" "structure-masters" "architect-pro" "design-studio" "blueprint-studio" "arch-elite" "structure-design" "studio-elite")
    for i in {1..20}; do
        generate_enhanced_template "architect" $i "${names[$i-1]}" "Architecture" "Innovative design that brings your vision to life" "$services" "architecture"
    done
}

generate_interior_design() {
    echo "Generating Interior Design templates..."
    local services="couch|Residential Design|Create your perfect living space with expert guidance.||building|Commercial Design|Inspiring workspaces that boost productivity.||palette|Color Consultation|Expert color schemes tailored to your style.||chair|Furniture Selection|Curated furnishings that complete your vision."
    local names=("design-space" "interior-pro" "style-masters" "space-design" "interior-elite" "design-interiors" "space-pro" "style-elite" "interior-masters" "design-elite" "space-style" "interior-design-pro" "style-pro" "space-elite" "interior-style" "design-style" "space-masters" "style-interiors" "design-pro-int" "interior-space")
    for i in {1..20}; do
        generate_enhanced_template "interior-design" $i "${names[$i-1]}" "Interior Design" "Beautiful interiors that reflect your unique style" "$services" "interior"
    done
}

generate_restaurant() {
    echo "Generating Restaurant templates..."
    local services="utensils|Dine In|Exceptional dining in our welcoming atmosphere.||box|Takeout|Your favorites prepared fresh and ready to go.||truck|Delivery|Delicious meals delivered right to your door.||glass-cheers|Catering|Perfect food for your special events and gatherings."
    local names=("taste-haven" "dine-fine" "food-masters" "culinary-elite" "taste-pro" "restaurant-elite" "fine-dining" "food-pro" "culinary-pro" "taste-elite" "dine-pro" "food-elite" "culinary-masters" "taste-masters" "restaurant-pro" "fine-food" "dining-elite" "food-taste" "culinary-taste" "restaurant-masters")
    for i in {1..20}; do
        generate_enhanced_template "restaurant" $i "${names[$i-1]}" "Restaurant" "Exceptional dining experiences with flavors you'll love" "$services" "restaurant"
    done
}

generate_automotive() {
    echo "Generating Automotive templates..."
    local services="tools|Repairs|Complete auto repair services you can trust.||oil-can|Maintenance|Oil changes, tune-ups, and preventive care.||laptop|Diagnostics|Advanced computer diagnostics for accurate solutions.||clipboard-list|Inspections|State inspections and comprehensive safety checks."
    local names=("auto-pro" "drive-masters" "car-elite" "motor-pro" "auto-elite" "drive-pro" "car-masters" "motor-elite" "auto-masters" "drive-elite" "car-pro" "motor-masters" "auto-drive" "car-drive" "motor-drive" "pro-motors" "elite-auto" "masters-auto" "pro-drive" "elite-motors")
    for i in {1..20}; do
        generate_enhanced_template "automotive" $i "${names[$i-1]}" "Automotive" "Expert auto services to keep you on the road safely" "$services" "automotive"
    done
}

generate_event() {
    echo "Generating Event templates..."
    local services="ring|Weddings|Your dream wedding, perfectly planned and executed.||birthday-cake|Parties|Birthday, anniversary, and celebration planning.||building|Corporate Events|Professional events that impress and inspire.||star|Special Occasions|Any event, any size, any style you envision."
    local names=("event-pro" "celebrate-elite" "party-masters" "event-elite" "celebrate-pro" "party-pro" "event-masters" "celebrate-masters" "party-elite" "pro-events" "elite-celebrations" "masters-party" "pro-celebrate" "elite-events" "masters-events" "pro-party" "elite-party" "masters-celebrate" "events-elite" "celebrations-pro")
    for i in {1..20}; do
        generate_enhanced_template "event" $i "${names[$i-1]}" "Event Planning" "Creating unforgettable events tailored to your vision" "$services" "event"
    done
}

generate_photography() {
    echo "Generating Photography templates..."
    local services="ring|Wedding Photography|Beautiful memories of your special day captured forever.||users|Family Portraits|Timeless family photos to treasure for generations.||briefcase|Commercial|Professional imagery that elevates your business.||calendar-alt|Event Coverage|Document your special occasions with stunning photos."
    local names=("capture-pro" "photo-masters" "lens-elite" "image-pro" "capture-elite" "photo-pro" "lens-masters" "image-elite" "capture-masters" "photo-elite" "lens-pro" "image-masters" "pro-capture" "elite-photo" "masters-lens" "pro-image" "elite-capture" "masters-photo" "pro-lens" "elite-image")
    for i in {1..20}; do
        generate_enhanced_template "photography" $i "${names[$i-1]}" "Photography" "Capturing your precious moments with artistic excellence" "$services" "photography"
    done
}

generate_music() {
    echo "Generating Music templates..."
    local services="guitar|Music Lessons|Learn any instrument with patient, expert teachers.||microphone|Live Performance|Entertainment that elevates your special events.||headphones|Recording|Professional studio recording for your music.||sliders-h|Production|Music production, mixing, and mastering services."
    local names=("sound-pro" "music-masters" "beat-elite" "audio-pro" "sound-elite" "music-pro" "beat-masters" "audio-elite" "sound-masters" "music-elite" "beat-pro" "audio-masters" "pro-sound" "elite-music" "masters-beat" "pro-audio" "elite-sound" "masters-music" "pro-beat" "elite-audio")
    for i in {1..20}; do
        generate_enhanced_template "music" $i "${names[$i-1]}" "Music" "Professional music services for lessons, events, and productions" "$services" "music"
    done
}

generate_single_page() {
    echo "Generating Single Page templates..."
    local services="bullseye|Our Services|Professional solutions tailored to your specific needs.||star|Quality Work|Excellence and attention to detail in everything we do.||handshake|Customer Focus|Your satisfaction is always our top priority.||award|Experience|Years of expertise working for you."
    local names=("one-page-pro" "single-pro" "simple-site" "one-page-elite" "single-elite" "simple-pro" "one-page-masters" "single-masters" "simple-elite" "pro-single" "elite-one-page" "masters-simple" "pro-one-page" "elite-single" "masters-one-page" "pro-simple" "elite-simple" "masters-single" "single-simple" "one-simple")
    for i in {1..20}; do
        generate_enhanced_template "single-page" $i "${names[$i-1]}" "Business" "Everything you need on one beautiful, effective page" "$services" "business"
    done
}

generate_landing_page() {
    echo "Generating Landing Page templates..."
    local services="rocket|Fast Results|See measurable results quickly with our proven approach.||lightbulb|Smart Solutions|Innovative answers to your biggest challenges.||chart-line|Growth Focused|Strategies designed to accelerate your growth.||crosshairs|Targeted|Precision solutions customized for your needs."
    local names=("convert-pro" "landing-elite" "lead-masters" "convert-elite" "landing-pro" "lead-pro" "convert-masters" "landing-masters" "lead-elite" "pro-convert" "elite-landing" "masters-lead" "pro-landing" "elite-convert" "masters-landing" "pro-lead" "elite-lead" "masters-convert" "convert-lead" "landing-lead")
    for i in {1..20}; do
        generate_enhanced_template "landing-page" $i "${names[$i-1]}" "Business" "Convert visitors into customers with proven strategies" "$services" "marketing"
    done
}

generate_online_store() {
    echo "Generating Online Store templates..."
    local services="shopping-bag|Shop Products|Browse our curated collection of quality products.||shipping-fast|Fast Shipping|Quick, reliable delivery right to your door.||undo|Easy Returns|Hassle-free return policy for your peace of mind.||lock|Secure Checkout|Safe, encrypted payment processing you can trust."
    local names=("shop-pro" "store-elite" "ecommerce-masters" "shop-elite" "store-pro" "ecommerce-pro" "shop-masters" "store-masters" "ecommerce-elite" "pro-shop" "elite-store" "masters-ecommerce" "pro-store" "elite-shop" "masters-store" "pro-ecommerce" "elite-ecommerce" "masters-shop" "shop-store" "store-shop")
    for i in {1..20}; do
        generate_enhanced_template "online-store" $i "${names[$i-1]}" "E-Commerce" "Shop our curated collection of quality products" "$services" "ecommerce"
    done
}

generate_full_website() {
    echo "Generating Full Website templates..."
    local services="home|Home|Welcome visitors with a powerful first impression.||list-alt|Services|Showcase everything your business offers.||users|About|Tell your story and build lasting trust.||envelope|Contact|Make it easy for customers to reach you."
    local names=("complete-pro" "full-site-elite" "website-masters" "complete-elite" "full-site-pro" "website-pro" "complete-masters" "full-site-masters" "website-elite" "pro-complete" "elite-full-site" "masters-website" "pro-full-site" "elite-complete" "masters-full-site" "pro-website" "elite-website" "masters-complete" "complete-website" "full-complete")
    for i in {1..20}; do
        generate_enhanced_template "full-website" $i "${names[$i-1]}" "Business" "Complete professional web presence for your business" "$services" "website"
    done
}

# ============================================
# MAIN EXECUTION
# ============================================

echo "=========================================="
echo "60 Minute Sites Enhanced Template Generator"
echo "Building 560 professional marketing templates"
echo "=========================================="
echo ""

# Run all generators
generate_construction
generate_plumber
generate_electrician
generate_painter
generate_hvac
generate_cleaning
generate_pest_control
generate_salon
generate_spa
generate_barber
generate_massage
generate_health_beauty
generate_fitness
generate_business_services
generate_real_estate
generate_insurance
generate_mortgage
generate_architect
generate_interior_design
generate_restaurant
generate_automotive
generate_event
generate_photography
generate_music
generate_single_page
generate_landing_page
generate_online_store
generate_full_website

echo ""
echo "=========================================="
echo "COMPLETE! Generated 560 enhanced templates."
echo "=========================================="
