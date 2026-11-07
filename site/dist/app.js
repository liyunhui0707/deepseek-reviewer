document.querySelectorAll('[data-copy], [data-text]').forEach(button => {
  const original = button.textContent;
  let resetTimer;
  let latestClick = 0;
  button.addEventListener('click', async () => {
    const click = ++latestClick;
    clearTimeout(resetTimer);
    const text = button.dataset.text || document.getElementById(button.dataset.copy).textContent;
    try {
      await navigator.clipboard.writeText(text);
      if (click !== latestClick) return;
      button.textContent = '已复制 ✓';
    } catch {
      if (click !== latestClick) return;
      button.textContent = '请手动选择复制';
    }
    resetTimer = setTimeout(() => { button.textContent = original; }, 2200);
  });
});
