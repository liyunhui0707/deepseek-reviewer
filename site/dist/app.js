document.querySelectorAll('[data-copy], [data-text]').forEach(button => {
  button.addEventListener('click', async () => {
    const text = button.dataset.text || document.getElementById(button.dataset.copy).textContent;
    const original = button.textContent;
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = '已复制 ✓';
    } catch {
      button.textContent = '请手动选择复制';
    }
    setTimeout(() => { button.textContent = original; }, 2200);
  });
});
