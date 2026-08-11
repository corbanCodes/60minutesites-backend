/**
 * Blog Filter - Dynamic article filtering by industry and category
 * Works with articles-data.js to show articles inline
 */

(function() {
  'use strict';

  const ARTICLES_PER_PAGE = 12;
  const FEATURED_PER_PAGE = 6;
  
  let currentIndustry = 'all';
  let currentCategory = 'featured';
  let currentPage = 1;
  let featuredPage = 1;
  let filteredArticles = [];
  let categoryArticles = [];

  // Category folder mappings
  const CATEGORY_FOLDERS = {
    'featured': null, // Special - shows curated picks
    'industries': null, // Special - scrolls to industry section
    'web-design': 'web-design',
    'local-seo': 'local-seo',
    'comparisons': 'comparisons',
    'getting-started': 'getting-started',
    'website-cost': 'website-cost',
    'llm-optimization': 'llm-optimization',
    'lead-generation': 'lead-generation'
  };

  const CATEGORY_NAMES = {
    'featured': 'Featured Guides',
    'web-design': 'Web Design',
    'local-seo': 'Local SEO',
    'comparisons': 'Comparisons',
    'getting-started': 'Getting Started',
    'website-cost': 'Website Cost',
    'llm-optimization': 'AI & LLM Optimization',
    'lead-generation': 'Lead Generation'
  };

  // Initialize on DOM ready
  document.addEventListener('DOMContentLoaded', init);

  function init() {
    // Check if we have article data
    if (typeof BLOG_ARTICLES === 'undefined' || !BLOG_ARTICLES.length) {
      console.warn('No article data found');
      return;
    }

    // Build industry filter buttons
    buildIndustryFilters();
    
    // Set up category pills
    setupCategoryPills();
    
    // Set up featured pagination
    setupFeaturedPagination();
    
    // Load initial content
    loadFeaturedGuides();
    filterArticles('all');
    
    // Set up search
    setupSearch();
  }

  function setupCategoryPills() {
    const pills = document.querySelectorAll('.category-pill[data-category]');
    
    pills.forEach(pill => {
      pill.addEventListener('click', function(e) {
        const category = this.dataset.category;
        
        // By Industry just scrolls
        if (category === 'industries') {
          return; // Let default anchor behavior work
        }
        
        e.preventDefault();
        
        // Update active state
        pills.forEach(p => p.classList.remove('active'));
        this.classList.add('active');
        
        // Load category content
        currentCategory = category;
        featuredPage = 1;
        loadCategoryContent(category);
      });
    });
  }

  function loadCategoryContent(category) {
    const heading = document.getElementById('featured-heading');
    const grid = document.getElementById('featured-grid');
    const pagination = document.getElementById('featured-pagination');
    
    if (category === 'featured') {
      loadFeaturedGuides();
      return;
    }
    
    // Get articles from this category folder
    const folder = CATEGORY_FOLDERS[category];
    if (!folder) return;
    
    categoryArticles = BLOG_ARTICLES.filter(a => a.url.includes('/' + folder + '/'));
    
    // Update heading
    heading.textContent = CATEGORY_NAMES[category] + ' (' + categoryArticles.length + ')';
    
    // Show pagination if needed
    const totalPages = Math.ceil(categoryArticles.length / FEATURED_PER_PAGE);
    if (totalPages > 1) {
      pagination.style.display = 'flex';
      updateFeaturedPagination(totalPages);
    } else {
      pagination.style.display = 'none';
    }
    
    // Render articles
    renderFeaturedGrid(categoryArticles);
  }

  function loadFeaturedGuides() {
    const heading = document.getElementById('featured-heading');
    const pagination = document.getElementById('featured-pagination');
    
    heading.textContent = 'Featured Guides';
    pagination.style.display = 'none';
    
    // Show curated featured articles (first 6 from different industries)
    const featured = [];
    const seenIndustries = new Set();
    
    for (const article of BLOG_ARTICLES) {
      if (!seenIndustries.has(article.industry) && featured.length < 6) {
        featured.push(article);
        seenIndustries.add(article.industry);
      }
    }
    
    categoryArticles = featured;
    renderFeaturedGrid(featured);
  }

  function renderFeaturedGrid(articles) {
    const grid = document.getElementById('featured-grid');
    if (!grid) return;
    
    const start = (featuredPage - 1) * FEATURED_PER_PAGE;
    const end = start + FEATURED_PER_PAGE;
    const pageArticles = articles.slice(start, end);
    
    grid.innerHTML = '';
    pageArticles.forEach(article => {
      grid.appendChild(createArticleCard(article));
    });
  }

  function setupFeaturedPagination() {
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    
    if (prevBtn) {
      prevBtn.addEventListener('click', () => {
        if (featuredPage > 1) {
          featuredPage--;
          renderFeaturedGrid(categoryArticles);
          updateFeaturedPagination(Math.ceil(categoryArticles.length / FEATURED_PER_PAGE));
        }
      });
    }
    
    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        const totalPages = Math.ceil(categoryArticles.length / FEATURED_PER_PAGE);
        if (featuredPage < totalPages) {
          featuredPage++;
          renderFeaturedGrid(categoryArticles);
          updateFeaturedPagination(totalPages);
        }
      });
    }
  }

  function updateFeaturedPagination(totalPages) {
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    const pageInfo = document.getElementById('page-info');
    
    if (prevBtn) prevBtn.disabled = featuredPage <= 1;
    if (nextBtn) nextBtn.disabled = featuredPage >= totalPages;
    if (pageInfo) pageInfo.textContent = featuredPage + ' / ' + totalPages;
  }

  function buildIndustryFilters() {
    const container = document.getElementById('industry-filters');
    if (!container) return;

    // Get industries with counts
    const counts = getIndustryCounts();
    const industries = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);

    // Clear existing (except "All")
    container.innerHTML = '<a href="#" class="industry-filter active" data-industry="all">All (' + BLOG_ARTICLES.length + ')</a>';

    // Add industry buttons
    industries.forEach(industry => {
      const name = getIndustryName(industry);
      const count = counts[industry];
      const btn = document.createElement('a');
      btn.href = '#';
      btn.className = 'industry-filter';
      btn.dataset.industry = industry;
      btn.textContent = name + ' (' + count + ')';
      container.appendChild(btn);
    });

    // Add click handlers
    container.querySelectorAll('.industry-filter').forEach(btn => {
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        
        // Update active state
        container.querySelectorAll('.industry-filter').forEach(b => b.classList.remove('active'));
        this.classList.add('active');
        
        // Filter articles
        filterArticles(this.dataset.industry);
        
        // Scroll to articles section
        document.getElementById('posts-grid').scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  function filterArticles(industry) {
    currentIndustry = industry;
    currentPage = 1;

    // Get filtered articles
    if (industry === 'all') {
      filteredArticles = [...BLOG_ARTICLES];
    } else {
      filteredArticles = BLOG_ARTICLES.filter(a => a.industry === industry);
    }

    // Update heading
    const heading = document.getElementById('articles-heading');
    if (heading) {
      if (industry === 'all') {
        heading.textContent = 'All Articles (' + filteredArticles.length + ')';
      } else {
        heading.textContent = getIndustryName(industry) + ' Articles (' + filteredArticles.length + ')';
      }
    }

    // Render articles with pagination
    renderArticles();
    renderPagination();
  }

  function renderArticles() {
    const container = document.getElementById('posts-grid');
    if (!container) return;

    container.innerHTML = '';

    const start = (currentPage - 1) * ARTICLES_PER_PAGE;
    const end = start + ARTICLES_PER_PAGE;
    const pageArticles = filteredArticles.slice(start, end);

    pageArticles.forEach(article => {
      container.appendChild(createArticleCard(article));
    });
  }

  function renderPagination() {
    const container = document.getElementById('articles-pagination');
    if (!container) return;

    const totalPages = Math.ceil(filteredArticles.length / ARTICLES_PER_PAGE);
    
    if (totalPages <= 1) {
      container.innerHTML = '';
      return;
    }

    let html = '';
    
    // Previous button
    if (currentPage > 1) {
      html += '<a href="#" class="page-btn" data-page="' + (currentPage - 1) + '">« Prev</a>';
    }
    
    // Page numbers (show max 7 pages)
    const startPage = Math.max(1, currentPage - 3);
    const endPage = Math.min(totalPages, startPage + 6);
    
    for (let i = startPage; i <= endPage; i++) {
      if (i === currentPage) {
        html += '<span class="active">' + i + '</span>';
      } else {
        html += '<a href="#" class="page-btn" data-page="' + i + '">' + i + '</a>';
      }
    }
    
    // Next button
    if (currentPage < totalPages) {
      html += '<a href="#" class="page-btn" data-page="' + (currentPage + 1) + '">Next »</a>';
    }
    
    container.innerHTML = html;
    
    // Add click handlers
    container.querySelectorAll('.page-btn').forEach(btn => {
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        currentPage = parseInt(this.dataset.page);
        renderArticles();
        renderPagination();
        document.getElementById('posts-grid').scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  function createArticleCard(article) {
    const card = document.createElement('a');
    card.href = article.url;
    card.className = 'post-card';
    
    const industryName = getIndustryName(article.industry);
    
    card.innerHTML = `
      <div class="post-card-content">
        <span class="category-badge">${industryName}</span>
        <h3>${article.title}</h3>
        <p>${article.description}</p>
        <div class="post-card-meta">
          <span><i class="fas fa-clock"></i> ${article.readTime} min read</span>
        </div>
      </div>
    `;
    
    return card;
  }

  function setupSearch() {
    const searchInputs = document.querySelectorAll('.blog-search-input, .sidebar-search input');
    
    searchInputs.forEach(input => {
      input.addEventListener('input', debounce(function() {
        const query = this.value.toLowerCase().trim();
        
        if (query.length < 2) {
          filterArticles(currentIndustry);
          return;
        }
        
        // Search all articles
        filteredArticles = BLOG_ARTICLES.filter(article => {
          return article.title.toLowerCase().includes(query) ||
                 article.description.toLowerCase().includes(query) ||
                 article.industry.toLowerCase().includes(query);
        });
        
        currentPage = 1;
        
        // Update heading
        const heading = document.getElementById('articles-heading');
        if (heading) {
          heading.textContent = 'Search Results (' + filteredArticles.length + ')';
        }
        
        renderArticles();
        renderPagination();
      }, 300));
    });
  }

  function debounce(func, wait) {
    let timeout;
    return function(...args) {
      clearTimeout(timeout);
      timeout = setTimeout(() => func.apply(this, args), wait);
    };
  }

})();
