// Shared PETIT chat input behavior for legacy and Universe UIs.
(() => {
  const ASSET_VERSION = window.PETIT_ASSET_VERSION || "0.14.1";

  const setup = ({ form, input, maxHeight = 160 }) => {
    if (!form || !input || input.dataset.petitChatInputReady === "true") return;
    input.dataset.petitChatInputReady = "true";

    let composing = false;
    let composeTimer = null;

    const resize = () => {
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, maxHeight)}px`;
    };

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
    input.addEventListener("input", resize);
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      if (event.shiftKey) return;
      if (composing || event.isComposing || event.keyCode === 229) return;
      event.preventDefault();
      form.requestSubmit();
    }, true);

    form.addEventListener("submit", () => {
      window.requestAnimationFrame(resize);
    });

    resize();
  };

  const versioned = (path) => `${path}${path.includes("?") ? "&" : "?"}v=${ASSET_VERSION}`;

  const loadStylesheet = (href, marker) => {
    if (document.querySelector(`link[data-petit-style="${marker}"]`)) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = versioned(href);
    link.dataset.petitStyle = marker;
    document.head.appendChild(link);
  };

  const loadSharedModule = (src, marker) => {
    const pathname = new URL(src, window.location.href).pathname;
    const alreadyLoaded = Array.from(document.scripts).some((script) => {
      if (!script.src) return false;
      return new URL(script.src, window.location.href).pathname === pathname;
    });
    if (alreadyLoaded || document.querySelector(`script[data-petit-module="${marker}"]`)) return;
    const script = document.createElement("script");
    script.src = versioned(src);
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
      loadStylesheet("/static/petit-ui-system.css", "unified-ui-system");
      loadStylesheet("/static/petit-motion.css", "ordinary-motion");
      loadSharedModule("/static/petit-ui-system.js", "unified-ui-system");
      loadSharedModule("/static/petit-motion.js", "ordinary-motion");
    }
  };

  window.PetitChatInput = { setup, discover };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", discover, { once: true });
  } else {
    discover();
  }
})();
