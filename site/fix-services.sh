#!/bin/bash

# Fix services in all templates
BASE_DIR="/Users/corbandamukaitis/Desktop/Personal Projects/60minutesites.com/templates"

# Function to fix a single template
fix_template() {
    local dir=$1
    local industry=$2
    local s1_icon=$3
    local s1_title=$4
    local s1_desc=$5
    local s2_icon=$6
    local s2_title=$7
    local s2_desc=$8
    local s3_icon=$9
    local s3_title=${10}
    local s3_desc=${11}
    local s4_icon=${12}
    local s4_title=${13}
    local s4_desc=${14}

    local html_file="$dir/index.html"
    if [ ! -f "$html_file" ]; then
        return
    fi

    # Create services HTML
    local services_html="<div class=\"service-card\">
                    <div class=\"service-icon\"><i class=\"fas fa-$s1_icon\"></i></div>
                    <h3>$s1_title</h3>
                    <p>$s1_desc</p>
                    <a href=\"#contact\" class=\"service-link\">Learn More <i class=\"fas fa-arrow-right\"></i></a>
                </div>
                <div class=\"service-card\">
                    <div class=\"service-icon\"><i class=\"fas fa-$s2_icon\"></i></div>
                    <h3>$s2_title</h3>
                    <p>$s2_desc</p>
                    <a href=\"#contact\" class=\"service-link\">Learn More <i class=\"fas fa-arrow-right\"></i></a>
                </div>
                <div class=\"service-card\">
                    <div class=\"service-icon\"><i class=\"fas fa-$s3_icon\"></i></div>
                    <h3>$s3_title</h3>
                    <p>$s3_desc</p>
                    <a href=\"#contact\" class=\"service-link\">Learn More <i class=\"fas fa-arrow-right\"></i></a>
                </div>
                <div class=\"service-card\">
                    <div class=\"service-icon\"><i class=\"fas fa-$s4_icon\"></i></div>
                    <h3>$s4_title</h3>
                    <p>$s4_desc</p>
                    <a href=\"#contact\" class=\"service-link\">Learn More <i class=\"fas fa-arrow-right\"></i></a>
                </div>"

    local footer_services="<li><a href=\"#services\">$s1_title</a></li>
                        <li><a href=\"#services\">$s2_title</a></li>
                        <li><a href=\"#services\">$s3_title</a></li>
                        <li><a href=\"#services\">$s4_title</a></li>"

    # Use perl for multiline replacement (more reliable than sed on macOS)
    perl -i -pe "s|SERVICES_HTML|$services_html|g" "$html_file" 2>/dev/null
    perl -i -pe "s|FOOTER_SERVICES|$footer_services|g" "$html_file" 2>/dev/null
}

echo "Fixing services in all templates..."

# Construction
for dir in "$BASE_DIR/construction"/*; do
    fix_template "$dir" "Construction" \
        "hammer" "New Construction" "Custom homes and commercial buildings built to your exact specifications." \
        "hard-hat" "Renovations" "Complete renovation services to transform your existing space." \
        "ruler-combined" "Additions" "Seamless home additions that expand your living space." \
        "project-diagram" "Project Management" "Full oversight from concept to completion."
done
echo "  Fixed: construction"

# Plumber
for dir in "$BASE_DIR/plumber"/*; do
    fix_template "$dir" "Plumbing" \
        "wrench" "Pipe Repair" "Fast, reliable repairs for leaks, bursts, and damaged pipes." \
        "shower" "Drain Cleaning" "Professional drain clearing and maintenance services." \
        "fire" "Water Heaters" "Expert installation and repair of all water heater types." \
        "phone-alt" "Emergency Service" "24/7 emergency plumbing when you need it most."
done
echo "  Fixed: plumber"

# Electrician
for dir in "$BASE_DIR/electrician"/*; do
    fix_template "$dir" "Electrical" \
        "bolt" "Electrical Repairs" "Fast diagnosis and repair of all electrical issues." \
        "lightbulb" "Lighting" "Indoor and outdoor lighting design and installation." \
        "plug" "Panel Upgrades" "Modernize your electrical panel for safety and capacity." \
        "home" "Wiring Services" "Complete wiring for new construction and renovations."
done
echo "  Fixed: electrician"

# Painter
for dir in "$BASE_DIR/painter"/*; do
    fix_template "$dir" "Painting" \
        "paint-roller" "Interior Painting" "Beautiful interior finishes for every room in your home." \
        "home" "Exterior Painting" "Weather-resistant exterior coatings that protect and beautify." \
        "brush" "Cabinet Refinishing" "Give your kitchen cabinets a stunning new look." \
        "palette" "Specialty Finishes" "Textures, faux finishes, and decorative painting techniques."
done
echo "  Fixed: painter"

# HVAC
for dir in "$BASE_DIR/hvac"/*; do
    fix_template "$dir" "HVAC" \
        "snowflake" "AC Repair" "Fast air conditioning repair and maintenance services." \
        "fire-alt" "Heating" "Furnace repair, installation, and maintenance." \
        "wind" "Air Quality" "Improve your indoor air with advanced filtration systems." \
        "fan" "System Install" "New HVAC system design and professional installation."
done
echo "  Fixed: hvac"

# Cleaning
for dir in "$BASE_DIR/cleaning"/*; do
    fix_template "$dir" "Cleaning" \
        "home" "Residential" "Thorough home cleaning tailored to your specific needs." \
        "building" "Commercial" "Professional office and business cleaning services." \
        "sparkles" "Deep Cleaning" "Intensive cleaning for a fresh, healthy start." \
        "truck-moving" "Move In/Out" "Complete cleaning for smooth property transitions."
done
echo "  Fixed: cleaning"

# Pest Control
for dir in "$BASE_DIR/pest-control"/*; do
    fix_template "$dir" "Pest Control" \
        "bug" "General Pest" "Eliminate common household pests quickly and effectively." \
        "shield-alt" "Rodent Control" "Effective mouse and rat removal and prevention." \
        "spider" "Insect Treatment" "Specialized treatment for all types of insects." \
        "home" "Prevention Plans" "Ongoing protection to keep pests away permanently."
done
echo "  Fixed: pest-control"

# Salon
for dir in "$BASE_DIR/salon"/*; do
    fix_template "$dir" "Salon" \
        "cut" "Haircuts" "Precision cuts and trendy styles for all hair types." \
        "palette" "Color Services" "Highlights, balayage, and full color transformations." \
        "magic" "Treatments" "Keratin, deep conditioning, and repair treatments." \
        "crown" "Special Events" "Bridal, prom, and special occasion styling."
done
echo "  Fixed: salon"

# Spa
for dir in "$BASE_DIR/spa"/*; do
    fix_template "$dir" "Spa" \
        "spa" "Massage" "Swedish, deep tissue, and hot stone massage therapy." \
        "smile" "Facials" "Customized facials for radiant, healthy skin." \
        "bath" "Body Treatments" "Luxurious wraps, scrubs, and detox treatments." \
        "gift" "Spa Packages" "Complete wellness experiences to indulge and relax."
done
echo "  Fixed: spa"

# Barber
for dir in "$BASE_DIR/barber"/*; do
    fix_template "$dir" "Barber" \
        "cut" "Haircuts" "Classic and contemporary cuts for the modern gentleman." \
        "user" "Beard Services" "Expert beard trims, shaping, and hot towel shaves." \
        "hot-tub" "Traditional Shaves" "Straight razor shaves with premium hot lather." \
        "leaf" "Treatments" "Scalp treatments and premium hair care services."
done
echo "  Fixed: barber"

# Massage
for dir in "$BASE_DIR/massage"/*; do
    fix_template "$dir" "Massage Therapy" \
        "hand-holding-heart" "Swedish" "Relaxing full-body massage for stress relief and wellness." \
        "dumbbell" "Deep Tissue" "Targeted therapy for chronic muscle tension and pain." \
        "fire-alt" "Hot Stone" "Heated basalt stones for deep relaxation and healing." \
        "running" "Sports Massage" "Athletic recovery and performance enhancement therapy."
done
echo "  Fixed: massage"

# Health Beauty
for dir in "$BASE_DIR/health-beauty"/*; do
    fix_template "$dir" "Health and Beauty" \
        "hand-sparkles" "Nail Services" "Luxurious manicures, pedicures, and nail artistry." \
        "smile" "Skincare" "Professional facials, peels, and skin treatments." \
        "magic" "Makeup" "Expert makeup application for any occasion." \
        "heart" "Wellness" "Holistic health and beauty treatments."
done
echo "  Fixed: health-beauty"

# Fitness
for dir in "$BASE_DIR/fitness"/*; do
    fix_template "$dir" "Fitness" \
        "user-friends" "Personal Training" "One-on-one coaching customized to your goals." \
        "users" "Group Classes" "Energizing group fitness for all levels." \
        "dumbbell" "Strength Training" "Build muscle, increase power, transform your body." \
        "heartbeat" "Cardio Programs" "Boost endurance and achieve your fitness goals."
done
echo "  Fixed: fitness"

# Business Services
for dir in "$BASE_DIR/business-services"/*; do
    fix_template "$dir" "Business Services" \
        "chart-line" "Consulting" "Expert business strategy and advisory services." \
        "bullhorn" "Marketing" "Digital marketing and brand growth solutions." \
        "cogs" "Operations" "Streamline and optimize your business operations." \
        "tasks" "Planning" "Strategic planning for sustainable long-term success."
done
echo "  Fixed: business-services"

# Real Estate
for dir in "$BASE_DIR/real-estate"/*; do
    fix_template "$dir" "Real Estate" \
        "home" "Home Buying" "Expert guidance through your home buying journey." \
        "dollar-sign" "Home Selling" "Get top dollar for your property with our expertise." \
        "key" "Rentals" "Find the perfect rental property for your needs." \
        "building" "Property Management" "Full-service property management solutions."
done
echo "  Fixed: real-estate"

# Insurance
for dir in "$BASE_DIR/insurance"/*; do
    fix_template "$dir" "Insurance" \
        "home" "Home Insurance" "Comprehensive protection for your home and belongings." \
        "car" "Auto Insurance" "Complete coverage for all your vehicles." \
        "heart" "Life Insurance" "Secure your family financial future." \
        "briefcase" "Business Insurance" "Protect your business with comprehensive coverage."
done
echo "  Fixed: insurance"

# Mortgage
for dir in "$BASE_DIR/mortgage"/*; do
    fix_template "$dir" "Mortgage" \
        "home" "Home Loans" "Competitive rates to make homeownership a reality." \
        "sync" "Refinancing" "Lower your rate or access your home equity." \
        "hard-hat" "Construction Loans" "Finance your custom home build project." \
        "clipboard-check" "Pre-Approval" "Get pre-approved and shop with confidence."
done
echo "  Fixed: mortgage"

# Architect
for dir in "$BASE_DIR/architect"/*; do
    fix_template "$dir" "Architecture" \
        "home" "Residential Design" "Custom homes designed for your unique lifestyle." \
        "building" "Commercial Design" "Functional spaces that drive business success." \
        "pencil-ruler" "Renovations" "Transform existing spaces with expert design." \
        "leaf" "Sustainable Design" "Eco-friendly architecture for a better future."
done
echo "  Fixed: architect"

# Interior Design
for dir in "$BASE_DIR/interior-design"/*; do
    fix_template "$dir" "Interior Design" \
        "couch" "Residential Design" "Create your perfect living space with expert guidance." \
        "building" "Commercial Design" "Inspiring workspaces that boost productivity." \
        "palette" "Color Consultation" "Expert color schemes tailored to your style." \
        "chair" "Furniture Selection" "Curated furnishings that complete your vision."
done
echo "  Fixed: interior-design"

# Restaurant
for dir in "$BASE_DIR/restaurant"/*; do
    fix_template "$dir" "Restaurant" \
        "utensils" "Dine In" "Exceptional dining in our welcoming atmosphere." \
        "box" "Takeout" "Your favorites prepared fresh and ready to go." \
        "truck" "Delivery" "Delicious meals delivered right to your door." \
        "glass-cheers" "Catering" "Perfect food for your special events and gatherings."
done
echo "  Fixed: restaurant"

# Automotive
for dir in "$BASE_DIR/automotive"/*; do
    fix_template "$dir" "Automotive" \
        "tools" "Repairs" "Complete auto repair services you can trust." \
        "oil-can" "Maintenance" "Oil changes, tune-ups, and preventive care." \
        "laptop" "Diagnostics" "Advanced computer diagnostics for accurate solutions." \
        "clipboard-list" "Inspections" "State inspections and comprehensive safety checks."
done
echo "  Fixed: automotive"

# Event
for dir in "$BASE_DIR/event"/*; do
    fix_template "$dir" "Event Planning" \
        "ring" "Weddings" "Your dream wedding, perfectly planned and executed." \
        "birthday-cake" "Parties" "Birthday, anniversary, and celebration planning." \
        "building" "Corporate Events" "Professional events that impress and inspire." \
        "star" "Special Occasions" "Any event, any size, any style you envision."
done
echo "  Fixed: event"

# Photography
for dir in "$BASE_DIR/photography"/*; do
    fix_template "$dir" "Photography" \
        "ring" "Wedding Photography" "Beautiful memories of your special day captured forever." \
        "users" "Family Portraits" "Timeless family photos to treasure for generations." \
        "briefcase" "Commercial" "Professional imagery that elevates your business." \
        "calendar-alt" "Event Coverage" "Document your special occasions with stunning photos."
done
echo "  Fixed: photography"

# Music
for dir in "$BASE_DIR/music"/*; do
    fix_template "$dir" "Music" \
        "guitar" "Music Lessons" "Learn any instrument with patient, expert teachers." \
        "microphone" "Live Performance" "Entertainment that elevates your special events." \
        "headphones" "Recording" "Professional studio recording for your music." \
        "sliders-h" "Production" "Music production, mixing, and mastering services."
done
echo "  Fixed: music"

# Single Page
for dir in "$BASE_DIR/single-page"/*; do
    fix_template "$dir" "Business" \
        "bullseye" "Our Services" "Professional solutions tailored to your specific needs." \
        "star" "Quality Work" "Excellence and attention to detail in everything we do." \
        "handshake" "Customer Focus" "Your satisfaction is always our top priority." \
        "award" "Experience" "Years of expertise working for you."
done
echo "  Fixed: single-page"

# Landing Page
for dir in "$BASE_DIR/landing-page"/*; do
    fix_template "$dir" "Business" \
        "rocket" "Fast Results" "See measurable results quickly with our proven approach." \
        "lightbulb" "Smart Solutions" "Innovative answers to your biggest challenges." \
        "chart-line" "Growth Focused" "Strategies designed to accelerate your growth." \
        "crosshairs" "Targeted" "Precision solutions customized for your needs."
done
echo "  Fixed: landing-page"

# Online Store
for dir in "$BASE_DIR/online-store"/*; do
    fix_template "$dir" "E-Commerce" \
        "shopping-bag" "Shop Products" "Browse our curated collection of quality products." \
        "shipping-fast" "Fast Shipping" "Quick, reliable delivery right to your door." \
        "undo" "Easy Returns" "Hassle-free return policy for your peace of mind." \
        "lock" "Secure Checkout" "Safe, encrypted payment processing you can trust."
done
echo "  Fixed: online-store"

# Full Website
for dir in "$BASE_DIR/full-website"/*; do
    fix_template "$dir" "Business" \
        "home" "Home" "Welcome visitors with a powerful first impression." \
        "list-alt" "Services" "Showcase everything your business offers." \
        "users" "About" "Tell your story and build lasting trust." \
        "envelope" "Contact" "Make it easy for customers to reach you."
done
echo "  Fixed: full-website"

echo ""
echo "All services fixed!"
