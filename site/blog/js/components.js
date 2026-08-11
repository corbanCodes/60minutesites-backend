// Blog Component Loader
// Loads shared header and footer components for all blog pages

(function() {
  'use strict';

  // Determine the base path based on current page depth
  function getBasePath() {
    const path = window.location.pathname;
    const depth = (path.match(/\//g) || []).length - 1;
    if (path.includes('/blog/') && path.split('/').filter(Boolean).length > 2) {
      return '/blog/';
    }
    return '/blog/';
  }

  // Load a component into a target element
  async function loadComponent(componentPath, targetSelector) {
    const target = document.querySelector(targetSelector);
    if (!target) return;

    try {
      const response = await fetch(componentPath);
      if (!response.ok) throw new Error(`Failed to load ${componentPath}`);
      const html = await response.text();
      target.innerHTML = html;
    } catch (error) {
      console.error('Component load error:', error);
    }
  }

  // Initialize mobile menu toggle after header loads
  function initMobileMenu() {
    const toggle = document.querySelector('.mobile-menu-toggle');
    const mobileNav = document.querySelector('.mobile-nav');
    const header = document.querySelector('.header');

    if (toggle && mobileNav) {
      toggle.addEventListener('click', function() {
        this.classList.toggle('active');
        mobileNav.classList.toggle('active');
      });

      // Close menu when clicking a link
      mobileNav.querySelectorAll('a').forEach(link => {
        link.addEventListener('click', () => {
          toggle.classList.remove('active');
          mobileNav.classList.remove('active');
        });
      });
    }

    // Header scroll effect
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

  // Initialize dropdown menus
  function initDropdowns() {
    const dropdowns = document.querySelectorAll('.nav-dropdown');
    
    dropdowns.forEach(dropdown => {
      const toggle = dropdown.querySelector('.nav-dropdown-toggle');
      
      if (toggle) {
        toggle.addEventListener('click', function(e) {
          e.preventDefault();
          dropdown.classList.toggle('active');
        });
      }
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', function(e) {
      if (!e.target.closest('.nav-dropdown')) {
        dropdowns.forEach(dropdown => {
          dropdown.classList.remove('active');
        });
      }
    });
  }

  // Set active nav link based on current page
  function setActiveNavLink() {
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.nav-link, .mobile-nav .nav-link, .nav-dropdown-item');

    navLinks.forEach(link => {
      link.classList.remove('active');
      const href = link.getAttribute('href');
      if (href && currentPath.includes('/blog/')) {
        if (href === '/blog/' || href.includes('/blog/')) {
          link.classList.add('active');
          // Also highlight parent dropdown
          const parentDropdown = link.closest('.nav-dropdown');
          if (parentDropdown) {
            const parentToggle = parentDropdown.querySelector('.nav-dropdown-toggle');
            if (parentToggle) parentToggle.classList.add('active');
          }
        }
      }
    });
  }

  // Main initialization
  async function init() {
    const basePath = getBasePath();

    // Load header
    await loadComponent(basePath + 'components/header.html', '#blog-header');

    // Load footer
    await loadComponent(basePath + 'components/footer.html', '#blog-footer');

    // Initialize interactions
    initMobileMenu();
    initDropdowns();
    setActiveNavLink();
  }

  // Run when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
