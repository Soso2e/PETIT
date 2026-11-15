// PETIT Chat & Develop Motion Components
// Rebuilt from DesignBookmark "Prompt box" and "Streaming reply" with identical spring constants.
(() => {
  if (window.PetitChatMotion) return;

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  const S = (x, k = 400, c = 30) => ({
    x,
    v: 0,
    t: x,
    k,
    c: reducedMotion.matches ? 2 * Math.sqrt(k) : c,
    baseC: c,
  });

  const step = (s, dt) => {
    const c = reducedMotion.matches ? 2 * Math.sqrt(s.k) : s.baseC;
    const a = -s.k * (s.x - s.t) - c * s.v;
    s.v += a * dt;
    s.x += s.v * dt;
  };

  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  const isSettled = (s, eps = 0.01) =>
    Math.abs(s.x - s.t) < eps && Math.abs(s.v) < eps;

  const animators = new Set();
  let rafId = 0;
  let lastNow = 0;

  const wake = () => {
    if (rafId || animators.size === 0) return;
    lastNow = performance.now();
    rafId = requestAnimationFrame(loop);
  };

  const loop = (now) => {
    rafId = 0;
    const dt = Math.min(Math.max((now - lastNow) / 1000, 0), 1 / 30);
    lastNow = now;

    const sub = 4;
    const subDt = dt / sub;
    for (const anim of Array.from(animators)) {
      if (reducedMotion.matches) {
        if (typeof anim.snap === "function") anim.snap();
      } else {
        for (let i = 0; i < sub; i++) anim.frame(subDt);
      }
      const keepGoing = anim.render();
      if (!keepGoing || reducedMotion.matches) {
        animators.delete(anim);
      }
    }

    if (animators.size > 0) {
      rafId = requestAnimationFrame(loop);
    }
  };

  const register = (anim) => {
    animators.add(anim);
    wake();
    return () => animators.delete(anim);
  };

  /**
   * Split text into readable chunks for word/phrase streaming reveal.
   * English words stay intact; Japanese text splits into short natural runs.
   */
  const splitChunks = (str) => {
    if (!str) return [];
    const tokens = [];
    let buf = "";
    const flushBuf = () => {
      if (buf) {
        tokens.push(buf);
        buf = "";
      }
    };
    for (const ch of str) {
      if (/\s/.test(ch)) {
        flushBuf();
        tokens.push(ch);
      } else if (/[\u3000-\u9fff\uff00-\uffef]/.test(ch)) {
        buf += ch;
        if (buf.length >= 2 || /[、。！？\n]/.test(ch)) flushBuf();
      } else {
        buf += ch;
        if (buf.length >= 12) flushBuf();
      }
    }
    flushBuf();
    return tokens;
  };

  /**
   * Prompt Box controller:
   * - Spring textarea height (420, 34)
   * - Spring status bar (380, 30)
   * - Spring Send <-> Stop morph button (520, 30)
   */
  const createPromptBox = ({
    form,
    textarea,
    submitBtn,
    maxHeight = 180,
    minHeight = 44,
    enableMorph = true,
    onStop = null,
  }) => {
    if (!form || !textarea) return null;
    if (form._petitPromptBox) return form._petitPromptBox;

    form.classList.add("has-petit-prompt-box");

    let statusEl = form.querySelector(".petit-prompt-status");
    if (!statusEl) {
      statusEl = document.createElement("div");
      statusEl.className = "petit-prompt-status";
      statusEl.setAttribute("aria-live", "polite");
      statusEl.innerHTML =
        '<span class="petit-prompt-status__mark" aria-hidden="true"></span>' +
        '<span class="petit-prompt-status__label"></span>';
      form.prepend(statusEl);
    }
    const statusLabel = statusEl.querySelector(".petit-prompt-status__label");

    let arrowEl = null;
    let stopEl = null;
    if (enableMorph && submitBtn) {
      submitBtn.classList.add("petit-send-morph");
      if (!submitBtn.querySelector(".petit-send-arrow")) {
        const existingSvg = submitBtn.querySelector("svg");
        arrowEl = document.createElement("span");
        arrowEl.className = "petit-send-arrow";
        arrowEl.setAttribute("aria-hidden", "true");
        if (existingSvg) {
          arrowEl.appendChild(existingSvg);
        } else {
          arrowEl.innerHTML =
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"></path></svg>';
        }
        stopEl = document.createElement("span");
        stopEl.className = "petit-send-stop";
        stopEl.setAttribute("aria-hidden", "true");
        submitBtn.prepend(arrowEl, stopEl);
      } else {
        arrowEl = submitBtn.querySelector(".petit-send-arrow");
        stopEl = submitBtn.querySelector(".petit-send-stop");
      }
    }

    const measureTargetHeight = () => {
      const prev = textarea.style.height;
      textarea.style.height = "auto";
      const cssMax = parseFloat(getComputedStyle(textarea).maxHeight);
      const limit = Number.isFinite(cssMax) ? Math.min(cssMax, maxHeight) : maxHeight;
      const raw = Math.max(minHeight, textarea.scrollHeight);
      const target = Math.min(raw, limit);
      textarea.style.overflowY = textarea.scrollHeight > limit ? "auto" : "hidden";
      textarea.style.height = prev;
      return target;
    };

    const initialH = measureTargetHeight();
    const H = S(initialH, 420, 34); // field height
    const SH = S(0, 380, 30);       // status bar: 0 closed, 1 open
    const M = S(0, 520, 30);        // button: 0 arrow, 1 stop

    let busy = false;
    let hideTimer = null;

    const anim = {
      frame(dt) {
        step(H, dt);
        step(SH, dt);
        step(M, dt);
      },
      snap() {
        H.x = H.t; H.v = 0;
        SH.x = SH.t; SH.v = 0;
        M.x = M.t; M.v = 0;
      },
      render() {
        textarea.style.height = `${H.x.toFixed(2)}px`;
        const shOpen = clamp(SH.x, 0, 1);
        statusEl.style.height = `${(Math.max(0, SH.x) * 28).toFixed(2)}px`;
        statusEl.style.opacity = shOpen.toFixed(3);
        statusEl.classList.toggle("is-open", shOpen > 0.05);

        if (arrowEl && stopEl) {
          const m = clamp(M.x, 0, 1.2);
          arrowEl.style.transform = `scale(${Math.max(0, 1 - m).toFixed(4)}) rotate(${(m * 90).toFixed(2)}deg)`;
          stopEl.style.transform = `scale(${Math.max(0, m).toFixed(4)})`;
        }

        const done =
          isSettled(H, 0.25) &&
          isSettled(SH, 0.005) &&
          isSettled(M, 0.005);
        if (done) {
          H.x = H.t; H.v = 0;
          SH.x = SH.t; SH.v = 0;
          M.x = M.t; M.v = 0;
          textarea.style.height = `${H.t.toFixed(2)}px`;
        }
        return !done;
      },
    };

    const syncReady = () => {
      if (!submitBtn) return;
      const hasText = Boolean(String(textarea.value || "").trim());
      submitBtn.classList.toggle("is-ready", busy || hasText);
    };

    const fit = () => {
      H.t = measureTargetHeight();
      syncReady();
      register(anim);
    };

    const setStatus = (kind, text, autoHideSec = 0) => {
      if (hideTimer) {
        clearTimeout(hideTimer);
        hideTimer = null;
      }
      statusEl.className = "petit-prompt-status" + (kind ? ` is-${kind}` : "");
      statusLabel.textContent = text || "";
      SH.t = text ? 1 : 0;
      register(anim);
      if (autoHideSec > 0) {
        hideTimer = setTimeout(() => {
          SH.t = 0;
          register(anim);
        }, autoHideSec * 1000);
      }
    };

    const hideStatus = () => {
      if (hideTimer) {
        clearTimeout(hideTimer);
        hideTimer = null;
      }
      SH.t = 0;
      register(anim);
    };

    const setBusy = (nextBusy) => {
      busy = Boolean(nextBusy);
      M.t = busy ? 1 : 0;
      if (submitBtn) {
        submitBtn.setAttribute("aria-label", busy ? "待機を停止" : "送信");
        submitBtn.setAttribute("title", busy ? "待機を停止" : "送信");
      }
      syncReady();
      register(anim);
    };

    if (enableMorph && submitBtn && typeof onStop === "function") {
      submitBtn.addEventListener(
        "click",
        (event) => {
          if (!busy) return;
          event.preventDefault();
          event.stopImmediatePropagation();
          onStop();
        },
        true
      );
    }

    textarea.addEventListener("input", fit);
    syncReady();

    const api = {
      fit,
      setStatus,
      hideStatus,
      setBusy,
      isBusy: () => busy,
    };
    form._petitPromptBox = api;
    return api;
  };

  /**
   * Message entrance spring (300, 22).
   */
  const animateMessageIn = (el, isUser = false) => {
    if (!el || reducedMotion.matches) return;
    el.classList.add("petit-msg-entering");
    const s = S(0, 300, 22);
    s.t = 1;
    el.style.opacity = "0";
    el.style.transform = isUser ? "translateY(14px) scale(0.92)" : "translateY(14px)";

    register({
      frame(dt) {
        step(s, dt);
      },
      snap() {
        s.x = 1; s.v = 0;
      },
      render() {
        const v = clamp(s.x, 0, 1.15);
        el.style.opacity = clamp(v, 0, 1).toFixed(3);
        const y = ((1 - s.x) * 14).toFixed(2);
        if (isUser) {
          const sc = (0.92 + 0.08 * s.x).toFixed(4);
          el.style.transform = `translateY(${y}px) scale(${sc})`;
        } else {
          el.style.transform = `translateY(${y}px)`;
        }
        const done = isSettled(s, 0.004);
        if (done) {
          el.style.opacity = "";
          el.style.transform = "";
          el.classList.remove("petit-msg-entering");
        }
        return !done;
      },
    });
  };

  /**
   * Streaming Reply controller for an assistant pending message.
   * - Bubble W/H springs (260, 26)
   * - "Thinking" opacity spring (300, 30)
   * - Word/chunk reveal springs (340, 26)
   */
  const createStreamingController = (messageEl, initialLabel = "考え中…") => {
    if (!messageEl) return null;
    const bodyEl = messageEl.querySelector(".message-body") || messageEl;
    const container = messageEl.parentElement;

    messageEl.classList.add("petit-stream-bubble", "is-thinking");
    bodyEl.textContent = "";

    const thinkEl = document.createElement("span");
    thinkEl.className = "petit-stream-think";
    thinkEl.textContent = initialLabel;
    messageEl.prepend(thinkEl);

    const PAD_X = 28;
    const PAD_Y = 20;

    const getMaxWidth = () => {
      if (!container) return 560;
      const style = getComputedStyle(container);
      const pad = parseFloat(style.paddingLeft || 0) + parseFloat(style.paddingRight || 0);
      return Math.max(200, container.clientWidth - pad);
    };

    const measureThinkWidth = () => Math.max(96, Math.ceil(thinkEl.offsetWidth + PAD_X));

    const W = S(measureThinkWidth(), 260, 26);
    const Hh = S(42, 260, 26);
    const T = S(1, 300, 30);

    let lastText = "";
    let hasStreamText = false;
    let activeWords = [];
    let finished = false;
    let unregister = null;

    const anim = {
      frame(dt) {
        step(W, dt);
        step(Hh, dt);
        step(T, dt);
        for (const w of activeWords) step(w.s, dt);
      },
      snap() {
        W.x = W.t; W.v = 0;
        Hh.x = Hh.t; Hh.v = 0;
        T.x = T.t; T.v = 0;
        for (const w of activeWords) {
          w.s.x = 1; w.s.v = 0;
        }
      },
      render() {
        if (finished) return false;
        messageEl.style.width = `${Math.max(80, W.x).toFixed(2)}px`;
        messageEl.style.height = `${Math.max(42, Hh.x).toFixed(2)}px`;
        thinkEl.style.opacity = clamp(T.x, 0, 1).toFixed(3);

        const nextActive = [];
        for (const w of activeWords) {
          const v = clamp(w.s.x, 0, 1.2);
          w.el.style.opacity = clamp(v, 0, 1).toFixed(3);
          w.el.style.transform = `translateY(${((1 - w.s.x) * 6).toFixed(2)}px)`;
          w.el.style.filter =
            v < 0.98 ? `blur(${((1 - clamp(v, 0, 1)) * 4).toFixed(2)}px)` : "none";
          if (isSettled(w.s, 0.01)) {
            w.el.style.opacity = "";
            w.el.style.transform = "";
            w.el.style.filter = "none";
          } else {
            nextActive.push(w);
          }
        }
        activeWords = nextActive;

        const done =
          activeWords.length === 0 &&
          isSettled(W, 0.3) &&
          isSettled(Hh, 0.3) &&
          isSettled(T, 0.01);
        return !done;
      },
    };

    const ensureLoop = () => {
      if (finished) return;
      if (!unregister) {
        unregister = register(anim);
      } else {
        animators.add(anim);
        wake();
      }
    };

    // Initial render
    messageEl.style.width = `${W.x.toFixed(2)}px`;
    messageEl.style.height = `${Hh.x.toFixed(2)}px`;

    const setPhase = (label) => {
      if (finished || hasStreamText) return;
      const next = label || "考え中…";
      if (thinkEl.textContent !== next) {
        thinkEl.textContent = next;
        W.t = Math.min(getMaxWidth(), measureThinkWidth());
        ensureLoop();
      }
    };

    const updateDraft = (fullText) => {
      if (finished) return;
      if (!fullText) {
        setPhase(initialLabel);
        return;
      }

      if (!hasStreamText) {
        hasStreamText = true;
        T.t = 0;
        messageEl.classList.remove("is-thinking");
        messageEl.classList.add("is-streaming-text");
        W.t = getMaxWidth();
      }

      let delta = "";
      if (fullText.startsWith(lastText)) {
        delta = fullText.slice(lastText.length);
      } else {
        bodyEl.textContent = "";
        activeWords = [];
        delta = fullText;
      }
      lastText = fullText;

      if (delta) {
        const chunks = splitChunks(delta);
        for (const chunk of chunks) {
          if (/^\s+$/.test(chunk)) {
            bodyEl.append(chunk);
          } else {
            const span = document.createElement("span");
            span.className = "petit-stream-chunk";
            span.textContent = chunk;
            if (!reducedMotion.matches) {
              span.style.opacity = "0";
              span.style.transform = "translateY(6px)";
              span.style.filter = "blur(4px)";
            }
            bodyEl.appendChild(span);
            activeWords.push({ el: span, s: S(0, 340, 26) });
            activeWords[activeWords.length - 1].s.t = 1;
          }
        }
      }

      // Measure target height at target width
      const savedWidth = messageEl.style.width;
      const savedHeight = messageEl.style.height;
      messageEl.style.width = `${W.t}px`;
      messageEl.style.height = "auto";
      Hh.t = Math.max(42, Math.ceil(bodyEl.offsetHeight + PAD_Y));
      messageEl.style.width = savedWidth;
      messageEl.style.height = savedHeight;

      ensureLoop();
    };

    const finish = () => {
      if (finished) return;
      finished = true;
      if (unregister) unregister();
      activeWords = [];
      thinkEl.remove();
      messageEl.classList.remove("petit-stream-bubble", "is-thinking", "is-streaming-text");
      messageEl.style.width = "";
      messageEl.style.height = "";
    };

    return {
      setPhase,
      updateDraft,
      finish,
    };
  };

  window.PetitChatMotion = {
    S,
    step,
    clamp,
    createPromptBox,
    animateMessageIn,
    createStreamingController,
  };
})();
