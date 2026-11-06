// Collapses the main navigation into a menu button on narrow screens.
// Without this script the links stay visible, so the menu never depends on it.
(() => {
  const header = document.querySelector('.masthead');
  const button = header && header.querySelector('.nav-toggle');
  if (!button) return;
  header.classList.add('nav-ready');
  const setOpen = open => {
    header.classList.toggle('nav-open', open);
    button.setAttribute('aria-expanded', String(open));
  };
  button.addEventListener('click', () => setOpen(!header.classList.contains('nav-open')));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && header.classList.contains('nav-open')) {
      setOpen(false);
      button.focus();
    }
  });
})();
