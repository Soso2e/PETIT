// Main Chat layout: keep the conversation and composer in front and fold
// secondary controls (thread switching, voice input mode) into one menu.
// The controls themselves are still created by session.js / voice.js /
// chat_attachments.js; this module only re-parents them, so their handlers
// and the Desktop chat surfaces that share those modules are unchanged.
(() => {
  if (window.PetitChatTidy?.initialized) return;

  const ICONS = {
    plus: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>',
    send: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"></path></svg>',
    chevron: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"></path></svg>',
  };

  const panel = () => document.querySelector('[data-view-panel="chat"] .chat-panel');

  const ensureMenu = (actions) => {
    let menu = actions.querySelector(".chat-menu");
    if (menu) return menu;
    menu = document.createElement("details");
    menu.className = "chat-menu";
    menu.innerHTML = `
      <summary aria-label="会話と音声の設定">
        <span class="chat-menu__label">会話</span>
        <span class="chat-menu__chevron">${ICONS.chevron}</span>
      </summary>
      <div class="chat-menu__panel">
        <section class="chat-menu__section" data-chat-menu="thread">
          <h2>会話</h2>
        </section>
        <section class="chat-menu__section" data-chat-menu="voice" hidden>
          <h2>音声入力</h2>
        </section>
      </div>`;
    actions.prepend(menu);
    menu.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && menu.open) {
        menu.open = false;
        menu.querySelector("summary")?.focus();
      }
    });
    document.addEventListener("pointerdown", (event) => {
      if (menu.open && !menu.contains(event.target)) menu.open = false;
    });
    window.addEventListener("petit:panel-change", () => { menu.open = false; });
    return menu;
  };

  const syncAttention = (menu, threadControls) => {
    if (!threadControls) return;
    // A pending turn result or an error must stay visible while folded.
    const restore = Array.from(threadControls.querySelectorAll("button"))
      .some((button) => button.textContent.includes("再取得"));
    const status = threadControls.querySelector('[role="status"]');
    const attention = restore || Boolean(status?.textContent.trim());
    if (menu.dataset.attention !== String(attention)) menu.dataset.attention = String(attention);
  };

  const tidyAttachments = (form) => {
    const attachments = document.querySelector(".chat-panel .chat-attachments");
    if (!attachments) return;
    const choose = Array.from(attachments.querySelectorAll(":scope > button"))
      .find((button) => button.textContent.trim() === "画像を添付");
    if (choose && !choose.dataset.chatTidy) {
      const help = attachments.querySelector(':scope > [role="status"]');
      choose.dataset.chatTidy = "true";
      choose.classList.add("chat-composer__icon", "chat-composer__attach");
      choose.setAttribute("aria-label", "画像を添付");
      choose.title = help?.textContent.trim() || "画像を添付";
      choose.innerHTML = ICONS.plus;
      form.prepend(choose);
      if (help) {
        const initial = help.textContent.trim();
        const syncHelp = () => {
          // The default help text is moved to the button title; only show
          // the line again for real progress or errors.
          const shown = Boolean(help.textContent.trim()) && help.textContent.trim() !== initial;
          if (attachments.dataset.status !== String(shown)) attachments.dataset.status = String(shown);
        };
        new MutationObserver(syncHelp).observe(help, { childList: true, characterData: true, subtree: true });
        syncHelp();
      }
    }
  };

  const tidyComposer = (form) => {
    const submit = form.querySelector('button[type="submit"]');
    if (submit && !submit.dataset.chatTidy) {
      submit.dataset.chatTidy = "true";
      submit.classList.add("chat-composer__icon", "chat-composer__send");
      submit.setAttribute("aria-label", "送信");
      submit.title = "送信";
      submit.innerHTML = ICONS.send;
    }
    const mic = form.querySelector("#mic");
    if (mic) mic.classList.add("chat-composer__icon");
    const input = form.querySelector("#chat-input");
    if (input && input.placeholder === "PETITに話しかける") input.placeholder = "メッセージ";
  };

  let applying = false;
  const apply = () => {
    if (applying) return;
    applying = true;
    try {
      const root = panel();
      const actions = root?.querySelector(".chat-head-actions");
      const form = document.getElementById("chat-form");
      if (!root || !actions || !form) return;

      const menu = ensureMenu(actions);
      const threadSection = menu.querySelector('[data-chat-menu="thread"]');
      const voiceSection = menu.querySelector('[data-chat-menu="voice"]');

      const threadControls = root.querySelector(".petit-thread-controls");
      if (threadControls && threadControls.parentElement !== threadSection) {
        threadControls.removeAttribute("style");
        threadSection.appendChild(threadControls);
      }
      syncAttention(menu, threadControls);

      const voiceOptions = actions.querySelector(":scope > .chat-voice-options");
      const voiceSettings = voiceOptions?.querySelector(".chat-voice-settings");
      if (voiceSettings) {
        voiceSection.appendChild(voiceSettings);
        voiceOptions.remove();
      }
      voiceSection.hidden = !voiceSection.querySelector(".chat-voice-settings");

      tidyAttachments(form);
      tidyComposer(form);
      root.dataset.chatTidy = "ready";
    } finally {
      applying = false;
    }
  };

  const initialize = () => {
    const root = panel();
    if (!root) return;
    apply();
    // session.js and voice.js mount asynchronously; re-parent when they do.
    new MutationObserver(apply).observe(root, { childList: true, subtree: true });
  };

  window.PetitChatTidy = { initialized: true, apply };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
