/* 60 Minute Sites - Main JavaScript */

document.addEventListener('DOMContentLoaded', function() {
  // Mobile Menu Toggle
  initMobileMenu();

  // Header Scroll Effect
  initHeaderScroll();

  // FAQ Accordion
  initFAQ();

  // Gallery Filters
  initGalleryFilters();

  // Smooth Scroll
  initSmoothScroll();

  // Animation on Scroll
  initScrollAnimation();
});

// Mobile Menu
function initMobileMenu() {
  const toggle = document.querySelector('.mobile-menu-toggle');
  const mobileNav = document.querySelector('.mobile-nav');

  if (toggle && mobileNav) {
    toggle.addEventListener('click', function() {
      mobileNav.classList.toggle('active');
      toggle.classList.toggle('active');
    });

    // Close menu when clicking a link
    const mobileLinks = mobileNav.querySelectorAll('.nav-link');
    mobileLinks.forEach(link => {
      link.addEventListener('click', function() {
        mobileNav.classList.remove('active');
        toggle.classList.remove('active');
      });
    });
  }
}

// Header Scroll Effect
function initHeaderScroll() {
  const header = document.querySelector('.header');

  if (header) {
    window.addEventListener('scroll', function() {
      if (window.scrollY > 50) {
        header.classList.add('scrolled');
      } else {
        header.classList.remove('scrolled');
      }
    });
  }
}

// FAQ Accordion
function initFAQ() {
  const faqItems = document.querySelectorAll('.faq-item');

  faqItems.forEach(item => {
    const question = item.querySelector('.faq-question');

    if (question) {
      question.addEventListener('click', function() {
        // Close other open items
        faqItems.forEach(otherItem => {
          if (otherItem !== item) {
            otherItem.classList.remove('active');
          }
        });

        // Toggle current item
        item.classList.toggle('active');
      });
    }
  });
}

// Gallery Filters
function initGalleryFilters() {
  const filterBtns = document.querySelectorAll('.filter-btn');
  const templateCards = document.querySelectorAll('.template-card');

  if (filterBtns.length && templateCards.length) {
    filterBtns.forEach(btn => {
      btn.addEventListener('click', function() {
        const filter = this.dataset.filter;

        // Update active button
        filterBtns.forEach(b => b.classList.remove('active'));
        this.classList.add('active');

        // Filter templates
        templateCards.forEach(card => {
          const category = card.dataset.category;

          if (filter === 'all' || category === filter) {
            card.style.display = 'block';
            setTimeout(() => {
              card.style.opacity = '1';
              card.style.transform = 'translateY(0)';
            }, 10);
          } else {
            card.style.opacity = '0';
            card.style.transform = 'translateY(20px)';
            setTimeout(() => {
              card.style.display = 'none';
            }, 300);
          }
        });
      });
    });
  }
}

// Smooth Scroll for anchor links
function initSmoothScroll() {
  const links = document.querySelectorAll('a[href^="#"]');

  links.forEach(link => {
    link.addEventListener('click', function(e) {
      const href = this.getAttribute('href');

      if (href !== '#') {
        const target = document.querySelector(href);

        if (target) {
          e.preventDefault();
          const headerOffset = 80;
          const elementPosition = target.getBoundingClientRect().top;
          const offsetPosition = elementPosition + window.pageYOffset - headerOffset;

          window.scrollTo({
            top: offsetPosition,
            behavior: 'smooth'
          });
        }
      }
    });
  });
}

// Animation on Scroll
function initScrollAnimation() {
  const animatedElements = document.querySelectorAll('[data-animate]');

  if (animatedElements.length) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('animate-fade-in');
          observer.unobserve(entry.target);
        }
      });
    }, {
      threshold: 0.1,
      rootMargin: '0px 0px -50px 0px'
    });

    animatedElements.forEach(el => {
      el.style.opacity = '0';
      observer.observe(el);
    });
  }
}

// Template data for gallery (will be populated dynamically)
const templateCategories = [
  { id: 'construction', name: 'Construction', count: 20 },
  { id: 'salon', name: 'Salon', count: 20 },
  { id: 'spa', name: 'Spa', count: 20 },
  { id: 'restaurant', name: 'Restaurant & Food', count: 20 },
  { id: 'business-services', name: 'Business Services', count: 20 },
  { id: 'real-estate', name: 'Real Estate', count: 20 },
  { id: 'automotive', name: 'Automotive', count: 20 },
  { id: 'cleaning', name: 'Cleaning', count: 20 },
  { id: 'fitness', name: 'Fitness', count: 20 },
  { id: 'health-beauty', name: 'Health & Beauty', count: 20 },
  { id: 'insurance', name: 'Insurance', count: 20 },
  { id: 'event', name: 'Event', count: 20 },
  { id: 'photography', name: 'Photography', count: 20 },
  { id: 'mortgage', name: 'Mortgage', count: 20 },
  { id: 'interior-design', name: 'Interior Design', count: 20 },
  { id: 'pest-control', name: 'Pest Control', count: 20 },
  { id: 'music', name: 'Music', count: 20 },
  { id: 'architect', name: 'Architect', count: 20 },
  { id: 'single-page', name: 'Single Page', count: 20 },
  { id: 'landing-page', name: 'Landing Page', count: 20 },
  { id: 'online-store', name: 'Online Store', count: 20 },
  { id: 'plumber', name: 'Plumber', count: 20 },
  { id: 'electrician', name: 'Electrician', count: 20 },
  { id: 'painter', name: 'Painter', count: 20 },
  { id: 'hvac', name: 'HVAC', count: 20 },
  { id: 'massage', name: 'Massage', count: 20 },
  { id: 'barber', name: 'Barber', count: 20 },
  { id: 'full-website', name: 'Full Website', count: 20 }
];

// Template style variations
const styleVariations = [
  'Modern Minimal',
  'Bold & Dark',
  'Classic Professional',
  'Vibrant & Colorful',
  'Elegant & Luxurious',
  'Rustic & Warm',
  'Tech & Futuristic',
  'Clean & Corporate',
  'Playful & Fun',
  'Sophisticated & Sleek',
  'Natural & Organic',
  'Urban & Industrial',
  'Vintage & Retro',
  'Fresh & Bright',
  'Calm & Serene',
  'Dynamic & Energetic',
  'Premium & Exclusive',
  'Friendly & Approachable',
  'Sharp & Geometric',
  'Soft & Rounded'
];

// Utility function to format phone number
function formatPhone(phone) {
  return phone.replace(/(\d{3})(\d{3})(\d{4})/, '($1) $2-$3');
}

// Export for use in other modules
window.SixtyMinuteSites = {
  templateCategories,
  styleVariations,
  formatPhone
};
