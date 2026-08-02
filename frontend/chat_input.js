// Shared PETIT chat input behavior for legacy and Universe UIs.
(() => {
  const setup = ({ form, input, maxHeight = 160 }) => {
    if (!form || !input || input.dataset.petitChatInputReady === "true") return;
    input.dataset.petitChatInputReady = "true";

    let composing = false;

    const resize = () => {
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, maxHeight)}px`;
    };

    input.addEventListener("compositionstart", () => { composing = true; });
    input.addEventListener("compositionend", () => { composing = false; });
    input.addEventListener("input", resize);
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      if (composing || event.isComposing || event.keyCode === 229) return;
      if (!(event.ctrlKey || event.metaKey)) return;
      event.preventDefault();
      form.requestSubmit();
    }, true);

    form.addEventListener("submit", () => {
      window.requestAnimationFrame(resize);
    });

    resize();
  };

  const loadSharedModule = (src, marker) => {
    if (document.querySelector(`script[data-petit-module="${marker}"]`)) return;
    const script = document.createElement("script");
    script.src = src;
    script.defer = true;
    script.dataset.petitModule = marker;
    document.head.appendChild(script);
  };

  const discover = () => {
    setup({
      form: document.getElementById("chat-form"),
      input: document.getElementById("input") || document.getElementById("chat-input"),
    });
    if (document.querySelector(".universe-shell")) {
      loadSharedModule("/static/app_shell.js?v=0.5.1", "app-shell");
    }
  };

  window.PetitChatInput = { setup, discover };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", discover, { once: true });
  } else {
    discover();
  }
})();
