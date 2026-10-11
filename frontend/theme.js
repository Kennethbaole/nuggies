/* Shared, local-only appearance preference; runs before the first paint. */
(() => {
  const key = 'nuggies-theme';
  let theme = 'light';
  try { if (localStorage.getItem(key) === 'dark') theme = 'dark'; } catch {}
  function apply(value) {
    theme = value === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0c171e' : '#f6fafb');
    const button = document.getElementById('theme-toggle');
    if (button) {
      button.setAttribute('aria-pressed', String(theme === 'dark'));
      button.setAttribute('aria-label', `Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`);
      button.querySelector('[data-theme-label]').textContent = theme === 'dark' ? 'Light mode' : 'Dark mode';
    }
  }
  apply(theme);
  document.addEventListener('DOMContentLoaded', () => {
    apply(theme);
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
      apply(theme === 'dark' ? 'light' : 'dark');
      try { localStorage.setItem(key, theme); } catch {}
    });
  });
  addEventListener('storage', event => { if (event.key === key) apply(event.newValue); });
})();
