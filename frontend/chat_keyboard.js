// PETIT chat keyboard behavior.
// Enter inserts a newline. Ctrl+Enter / Cmd+Enter sends the message.
(() => {
  const input = document.getElementById("input");
  const form = document.getElementById("chat-form");
  if (!input || !form) return;

  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    if (event.isComposing || event.keyCode === 229) return;

    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      event.stopImmediatePropagation();
      form.requestSubmit();
      return;
    }

    // Stop the legacy Enter-to-send listener while preserving the textarea's
    // default newline behavior.
    event.stopImmediatePropagation();
  }, true);
})();
