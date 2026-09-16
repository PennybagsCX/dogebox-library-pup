// Dogebox Library pup — interactive layer
(() => {
  'use strict';

  // ===== Inject styles =====
  (function injectStyles() {
    const css = `
      /* Autocomplete dropdown */
      .suggestions {
        position: absolute;
        z-index: 100;
        background: #1e1e2a;
        border: 1px solid #2a2a3a;
        border-radius: 0.5rem;
        box-shadow: 0 8px 24px rgba(0,0,0,0.6);
        max-height: 400px;
        overflow-y: auto;
      }
      .suggestion {
        display: flex;
        align-items: center;
        gap: 0.75rem;
        padding: 0.5rem 0.75rem;
        cursor: pointer;
      }
      .suggestion:hover,
      .suggestion[aria-selected="true"] {
        background: #252535;
      }
      .suggestion .poster {
        width: 32px;
        aspect-ratio: 2/3;
        border-radius: 0.25rem;
        object-fit: cover;
        flex-shrink: 0;
      }
      .suggestion .kind {
        background: #4c1d95;
        color: #f0f0f5;
        padding: 0.1rem 0.4rem;
        border-radius: 9999px;
        font-size: 0.7rem;
        flex-shrink: 0;
      }
      .suggestion .year {
        color: #5a5a70;
        font-size: 0.8rem;
        margin-left: auto;
        flex-shrink: 0;
      }
      .suggestion span:not(.kind):not(.year) {
        color: #f0f0f5;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      /* Toast notifications */
      .toast {
        position: fixed;
        top: 1rem;
        left: 50%;
        transform: translateX(-50%);
        background: #1e1e2a;
        border: 1px solid #2a2a3a;
        border-radius: 0.5rem;
        padding: 0.75rem 1rem;
        box-shadow: 0 8px 24px rgba(0,0,0,0.6);
        z-index: 1000;
        min-width: 280px;
        max-width: 420px;
        animation: toast-in 350ms ease-out;
      }
      .toast.toast-success { border-left: 2px solid #22c55e; }
      .toast.toast-error   { border-left: 2px solid #ef4444; }
      .toast.toast-info    { border-left: 2px solid #a855f7; }
      .toast.toast-fadeout { animation: toast-out 300ms ease-in forwards; }
      @keyframes toast-in  { from { opacity: 0; transform: translateX(-50%) translateY(-10px); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }
      @keyframes toast-out { from { opacity: 1; } to { opacity: 0; } }

      /* Random pick button spinner */
      @keyframes spin { to { transform: rotate(360deg); } }
      .random-pick-btn.loading .glyph::after {
        content: '';
        display: inline-block;
        width: 14px;
        height: 14px;
        border: 2px solid rgba(255,255,255,0.3);
        border-top-color: #fff;
        border-radius: 50%;
        animation: spin 0.7s linear infinite;
        margin-left: 6px;
        vertical-align: middle;
      }
    `;
    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
  })();

  // ===== Helpers =====
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));
  const debounce = (fn, ms = 200) => {
    let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  };
  const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  // ===== Toast system (global) =====
  function showToast(message, type = 'info') {
    const region = $('#toast-region');
    if (!region) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    region.appendChild(toast);
    setTimeout(() => {
      toast.classList.add('toast-fadeout');
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }
  // Expose globally for inline handlers
  window.showToast = showToast;

  // ===== Live search dropdown =====
  const searchInput = $('#q');
  const suggBox = $('#suggest');

  if (searchInput && suggBox) {
    let aborter = null;
    let activeIdx = -1;
    let lastResults = [];

    const closeSuggestions = () => { suggBox.classList.remove('open'); suggBox.innerHTML = ''; activeIdx = -1; lastResults = []; };
    const openSuggestions = () => { if (lastResults.length) suggBox.classList.add('open'); };
    const renderSuggestions = (movies, series) => {
      suggBox.innerHTML = '';
      lastResults = [];
      const make = (kind, item, key) => {
        const poster = item.remotePoster ? `<img class="poster" src="${escapeHtml(item.remotePoster)}" alt="">` : '';
        const title = escapeHtml(item.title || '?');
        const year = item.year ? `(${item.year})` : '';
        const div = document.createElement('div');
        div.className = 'suggestion';
        div.setAttribute('role', 'option');
        div.setAttribute('aria-label', title + (item.year ? ' ' + item.year : ''));
        div.dataset.kind = kind;
        div.dataset.key = item[key];
        div.innerHTML = `${poster}<span class="kind">${kind === 'movie' ? 'Movie' : 'Show'}</span><span>${title}</span><span class="year">${year}</span>`;
        div.addEventListener('mouseenter', () => {
          lastResults.forEach((r, i) => r.el.setAttribute('aria-selected', i === activeIdx ? 'true' : 'false'));
          const idx = lastResults.findIndex(r => r.el === div);
          if (idx !== -1 && idx !== activeIdx) {
            activeIdx = idx;
            lastResults.forEach((r, i) => r.el.setAttribute('aria-selected', i === activeIdx ? 'true' : 'false'));
            const active = lastResults[activeIdx];
            if (active) suggBox.scrollTop = active.el.offsetTop - suggBox.offsetTop;
          }
        });
        div.addEventListener('mousedown', (e) => {
          e.preventDefault();
          searchInput.value = item.title;
          // Submit parent form if exists
          const form = searchInput.form;
          if (form) form.submit();
        });
        return div;
      };
      (movies || []).slice(0, 5).forEach((m) => { const el = make('movie', m, 'tmdbId'); suggBox.appendChild(el); lastResults.push({el, kind: 'movie', id: m.tmdbId}); });
      (series || []).slice(0, 5).forEach((s) => { const el = make('series', s, 'tvdbId'); suggBox.appendChild(el); lastResults.push({el, kind: 'series', id: s.tvdbId}); });
      activeIdx = -1;
      openSuggestions();
    };
    const updateActive = () => {
      lastResults.forEach((r, i) => r.el.setAttribute('aria-selected', i === activeIdx ? 'true' : 'false'));
      const active = lastResults[activeIdx];
      if (active) suggBox.scrollTop = active.el.offsetTop - suggBox.offsetTop;
    };

    const doFetch = debounce(async () => {
      const term = searchInput.value.trim();
      if (term.length < 2) { closeSuggestions(); return; }
      if (aborter) aborter.abort();
      aborter = new AbortController();
      try {
        const url = `/api/search?q=${encodeURIComponent(term)}`;
        const r = await fetch(url, { signal: aborter.signal, credentials: 'same-origin' });
        if (!r.ok) { closeSuggestions(); return; }
        const data = await r.json();
        renderSuggestions(data.movies || [], data.series || []);
      } catch (e) { /* ignore aborted */ }
    }, 180);

    searchInput.addEventListener('input', doFetch);
    searchInput.addEventListener('focus', () => { doFetch(); openSuggestions(); });
    searchInput.addEventListener('blur', () => { setTimeout(closeSuggestions, 150); });
    searchInput.addEventListener('keydown', (e) => {
      if (!suggBox.classList.contains('open') || !lastResults.length) return;
      if (e.key === 'ArrowDown') { activeIdx = (activeIdx + 1) % lastResults.length; updateActive(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { activeIdx = (activeIdx - 1 + lastResults.length) % lastResults.length; updateActive(); e.preventDefault(); }
      else if (e.key === 'Enter' && activeIdx >= 0) { /* let form submit with current value */ }
      else if (e.key === 'Escape') { closeSuggestions(); }
    });
  }

  // ===== Random Pick button: prevent default form submit on Enter, add loading =====
  const randBtn = $('#random-pick-btn');
  if (randBtn) {
    randBtn.addEventListener('click', () => {
      randBtn.classList.add('loading');
      randBtn.setAttribute('aria-busy', 'true');
    });
  }

  // ===== Keyboard shortcuts =====
  // / focuses search · r triggers random · t focuses tonight · Esc clears/blurs
  document.addEventListener('keydown', (e) => {
    if (e.target && /^(input|textarea|select)$/i.test(e.target.tagName)) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const key = e.key.toLowerCase();
    if (key === '/') {
      const q = $('#q');
      if (q) { q.focus(); q.select(); e.preventDefault(); }
    } else if (key === 'r') {
      const btn = $('#random-pick-btn');
      if (btn) { btn.click(); e.preventDefault(); }
    } else if (key === 't') {
      const tq = $('#tonight-q');
      if (tq) { tq.focus(); tq.select(); e.preventDefault(); }
    } else if (key === 'escape') {
      const q = $('#q');
      if (q) { q.blur(); }
    }
  });
})();
