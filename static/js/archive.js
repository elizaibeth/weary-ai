(() => {
  const search = document.querySelector('#archive-search');
  if (!search) return;
  const items = [...document.querySelectorAll('.archive-item')];
  const buttons = [...document.querySelectorAll('[data-category]')];
  const status = document.querySelector('.search-status');
  const empty = document.querySelector('.no-results');
  let category = 'all';
  const normalise = value => value.toLocaleLowerCase('en-GB').trim();
  const filter = () => {
    const query = normalise(search.value);
    let visible = 0;
    items.forEach(item => {
      const categoryMatches = category === 'all' || item.dataset.category === category;
      const searchMatches = !query || normalise(item.dataset.search).includes(query);
      item.hidden = !(categoryMatches && searchMatches);
      if (!item.hidden) visible += 1;
    });
    status.textContent = `${visible} ${visible === 1 ? 'story' : 'stories'}`;
    empty.hidden = visible !== 0;
  };
  search.addEventListener('input', filter);
  buttons.forEach(button => button.addEventListener('click', () => {
    category = button.dataset.category;
    buttons.forEach(item => item.classList.toggle('active', item === button));
    filter();
  }));
  filter();
})();
