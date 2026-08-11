// Blog Search Functionality
// Client-side search for blog posts

(function() {
  'use strict';

  // Post data will be loaded from posts.json or embedded
  let posts = [];

  // DOM Elements
  const searchInputs = document.querySelectorAll('#blog-search, .sidebar-search input');
  const postsGrid = document.getElementById('posts-grid');

  // Initialize search
  async function init() {
    // Try to load posts data
    try {
      const response = await fetch('/blog/js/posts.json');
      if (response.ok) {
        posts = await response.json();
      }
    } catch (error) {
      console.log('Posts data not available, search will use DOM');
      // Fallback: extract posts from current DOM
      extractPostsFromDOM();
    }

    // Attach event listeners
    searchInputs.forEach(input => {
      input.addEventListener('input', handleSearch);
    });
  }

  // Extract posts from current page DOM as fallback
  function extractPostsFromDOM() {
    if (!postsGrid) return;

    const postCards = postsGrid.querySelectorAll('.post-card');
    posts = Array.from(postCards).map(card => ({
      title: card.querySelector('h3')?.textContent || '',
      excerpt: card.querySelector('p')?.textContent || '',
      category: card.querySelector('.category-badge')?.textContent || '',
      url: card.href || '',
      element: card
    }));
  }

  // Handle search input
  function handleSearch(e) {
    const query = e.target.value.toLowerCase().trim();

    // Sync search inputs
    searchInputs.forEach(input => {
      if (input !== e.target) {
        input.value = e.target.value;
      }
    });

    if (!query) {
      // Show all posts
      showAllPosts();
      return;
    }

    // Filter posts
    const filtered = posts.filter(post => {
      const title = (post.title || '').toLowerCase();
      const excerpt = (post.excerpt || '').toLowerCase();
      const category = (post.category || '').toLowerCase();
      const tags = (post.tags || []).join(' ').toLowerCase();

      return title.includes(query) ||
             excerpt.includes(query) ||
             category.includes(query) ||
             tags.includes(query);
    });

    renderFilteredPosts(filtered);
  }

  // Show all posts
  function showAllPosts() {
    if (!postsGrid) return;

    const postCards = postsGrid.querySelectorAll('.post-card');
    postCards.forEach(card => {
      card.style.display = '';
    });

    // Remove no results message if exists
    const noResults = postsGrid.querySelector('.no-results');
    if (noResults) {
      noResults.remove();
    }
  }

  // Render filtered posts
  function renderFilteredPosts(filtered) {
    if (!postsGrid) return;

    // If using DOM elements
    if (posts[0]?.element) {
      posts.forEach(post => {
        if (post.element) {
          const isMatch = filtered.includes(post);
          post.element.style.display = isMatch ? '' : 'none';
        }
      });

      // Show/hide no results
      const noResults = postsGrid.querySelector('.no-results');
      if (filtered.length === 0) {
        if (!noResults) {
          const msg = document.createElement('div');
          msg.className = 'no-results';
          msg.innerHTML = '<i class="fas fa-search"></i><p>No articles found matching your search.</p>';
          postsGrid.appendChild(msg);
        }
      } else if (noResults) {
        noResults.remove();
      }
    }
  }

  // Debounce function
  function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
