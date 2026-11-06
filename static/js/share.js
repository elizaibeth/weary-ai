document.querySelectorAll('.share').forEach((share) => {
  const url = share.dataset.shareUrl;
  const title = share.dataset.shareTitle;
  const status = share.querySelector('.share-status');
  const copy = share.querySelector('[data-copy-link]');
  const native = share.querySelector('[data-native-share]');

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(url);
      status.textContent = 'Link copied.';
    } catch (_) {
      const input = document.createElement('textarea');
      input.value = url;
      input.setAttribute('readonly', '');
      input.className = 'copy-fallback';
      document.body.appendChild(input);
      input.select();
      const copied = document.execCommand('copy');
      input.remove();
      status.textContent = copied ? 'Link copied.' : 'Copy this address: ' + url;
    }
  };

  copy.addEventListener('click', copyLink);

  if (navigator.share) {
    native.hidden = false;
    native.addEventListener('click', async () => {
      try {
        await navigator.share({ title, url });
      } catch (error) {
        if (error.name !== 'AbortError') await copyLink();
      }
    });
  }
});
