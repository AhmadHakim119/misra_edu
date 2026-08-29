/* ==========================================================================
   MISRA EDU — Shared front-end behavior
   Vanilla JS, no build step. Keep this file framework-free.
   ========================================================================== */

(function () {
  'use strict';

  document.documentElement.classList.remove('no-js');

  /* ---- Mobile nav drawer ---- */
  const menuBtn = document.querySelector('[data-menu-toggle]');
  const drawer = document.querySelector('[data-mobile-drawer]');

  if (menuBtn && drawer) {
    menuBtn.addEventListener('click', () => {
      const isOpen = drawer.classList.toggle('is-open');
      menuBtn.setAttribute('aria-expanded', String(isOpen));
      document.body.style.overflow = isOpen ? 'hidden' : '';
    });

    drawer.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => {
        drawer.classList.remove('is-open');
        menuBtn.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
      });
    });
  }

  /* ---- Scroll reveal (IntersectionObserver, not scroll listeners) ----
     Safety net: anything already inside the viewport on load, or that for
     any reason never crosses the observer threshold (e.g. very short
     pages, print/automation contexts, observer bugs), is force-shown
     after a short timeout so content is never stuck invisible. */
  const revealEls = document.querySelectorAll('.reveal');
  if (revealEls.length) {
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              entry.target.classList.add('is-visible');
              io.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.1, rootMargin: '0px 0px -10% 0px' }
      );
      revealEls.forEach((el, i) => {
        el.style.transitionDelay = `${Math.min(i % 4, 3) * 70}ms`;
        io.observe(el);
      });
    } else {
      revealEls.forEach((el) => el.classList.add('is-visible'));
    }

    // Safety net regardless of observer support.
    window.setTimeout(() => {
      revealEls.forEach((el) => el.classList.add('is-visible'));
    }, 2500);
  }

  /* ---- Toast notifications ---- */
  function ensureToastHost() {
    let host = document.getElementById('toast-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'toast-host';
      host.setAttribute('aria-live', 'polite');
      host.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:999;display:flex;flex-direction:column;gap:10px;max-width:320px;';
      document.body.appendChild(host);
    }
    return host;
  }

  window.showToast = function showToast(message, kind = 'info') {
    const host = ensureToastHost();
    const el = document.createElement('div');
    const tones = {
      success: { bg: '#2E4436', accent: '#B1D2BB' },
      warning: { bg: '#5D4928', accent: '#E3D5B9' },
      error: { bg: '#4A2E2A', accent: '#E0A99C' },
      info: { bg: '#302D35', accent: '#B1D2BB' },
    };
    const tone = tones[kind] || tones.info;
    el.style.cssText = `background:${tone.bg};color:#fff;padding:13px 16px;border-radius:12px;font-size:13.5px;font-weight:500;box-shadow:0 12px 28px rgba(0,0,0,0.22);border:1px solid rgba(255,255,255,0.12);opacity:0;transform:translateY(8px);transition:opacity 220ms var(--ease-out),transform 220ms var(--ease-out);`;
    el.textContent = message;
    host.appendChild(el);
    requestAnimationFrame(() => {
      el.style.opacity = '1';
      el.style.transform = 'translateY(0)';
    });
    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(8px)';
      setTimeout(() => el.remove(), 240);
    }, 4200);
  };

  /* ---- Active nav link highlighting ---- */
  const currentPage = document.body.getAttribute('data-page');
  if (currentPage) {
    document.querySelectorAll(`[data-nav="${currentPage}"]`).forEach((el) => {
      el.setAttribute('aria-current', 'page');
    });
  }
})();
