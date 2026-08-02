// PC chat keyboard behavior: Enter inserts a newline; Ctrl/Cmd+Enter submits.
(() => {
  const input = document.getElementById("chat-input");
  const form = document.getElementById("chat-form");
  if (!input || !form) return;

  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    if (event.isComposing) return;
    if (!(event.ctrlKey || event.metaKey)) return;

    event.preventDefault();
    form.requestSubmit();
  }, true);
})();
