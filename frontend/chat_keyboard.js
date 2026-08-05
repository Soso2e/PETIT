// Chat keyboard behavior: Enter submits after IME conversion; Shift+Enter inserts a newline.
(() => {
  const input = document.getElementById("chat-input");
  const form = document.getElementById("chat-form");
  if (!input || !form) return;

  let composing = false;
  let composeTimer = null;

  input.addEventListener("compositionstart", () => {
    composing = true;
    if (composeTimer) clearTimeout(composeTimer);
  });
  input.addEventListener("compositionend", () => {
    composing = true;
    if (composeTimer) clearTimeout(composeTimer);
    composeTimer = setTimeout(() => {
      composing = false;
    }, 50);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    if (event.shiftKey) return;
    if (composing || event.isComposing || event.keyCode === 229) return;

    event.preventDefault();
    form.requestSubmit();
  }, true);
})();
