// Bridge existing Univ HUD/detail actions to the real WebGL camera without running CSS camera input twice.
(() => {
  if (window.PetitUnivWebGLBridge?.initialized) return;

  let boundCanvas = null;
  let observer = null;
  let detailPlaceholder = null;

  const webgl = () => window.PetitUnivWebGL;
  const active = () => Boolean(webgl()?.active?.());
  const viewport = () => document.querySelector(".univ-viewport");

  const ensureDetailPortal = () => {
    const detail = document.querySelector("#detail-panel");
    if (!detail || detail.parentElement === document.body) return detail;
    if (!detailPlaceholder) {
      detailPlaceholder = document.createComment("PETIT detail panel portal");
      detail.parentNode?.insertBefore(detailPlaceholder, detail);
    }
    detail.classList.add("univ-detail-portal");
    document.body.appendChild(detail);
    return detail;
  };

  const setRecoveryStatus = (message = "") => {
    const frame = viewport();
    if (!frame) return;
    let status = frame.querySelector(":scope > .univ-webgl-status[data-context-status]");
    if (!message) {
      status?.remove();
      return;
    }
    if (!status) {
      status = document.createElement("p");
      status.className = "univ-webgl-status";
      status.dataset.contextStatus = "true";
      frame.appendChild(status);
    }
    status.textContent = message;
  };

  const installContextRecovery = (canvas) => {
    if (!canvas || canvas.dataset.contextRecoveryReady === "true") return;
    canvas.dataset.contextRecoveryReady = "true";
    canvas.addEventListener("webglcontextlost", (event) => {
      event.preventDefault();
      document.body.classList.remove("petit-univ-webgl-ready", "petit-univ-manage-open");
      document.body.classList.add("petit-univ-webgl-fallback");
      setRecoveryStatus("3D描画を復旧しています。現在は従来表示へ切り替えました。");
    });
    canvas.addEventListener("webglcontextrestored", () => {
      document.body.classList.remove("petit-univ-webgl-fallback");
      setRecoveryStatus();
      webgl()?.rebuild?.();
    });
  };

  const stopLegacyCameraInput = (canvas) => {
    if (!canvas || canvas === boundCanvas) return false;
    boundCanvas = canvas;
    const stop = (event) => {
      if (active()) event.stopPropagation();
    };
    ["pointerdown", "pointermove", "pointerup", "pointercancel", "wheel", "keydown"].forEach((type) => {
      canvas.addEventListener(type, stop);
    });
    installContextRecovery(canvas);
    return true;
  };

  const bindCanvas = () => {
    const connected = stopLegacyCameraInput(document.querySelector(".univ-webgl-stage canvas"));
    if (connected) {
      ensureDetailPortal();
      observer?.disconnect();
      observer = null;
    }
  };

  const openDetail = () => {
    const taskId = window.PetitUnivSpace?.state?.().selectedTaskId;
    if (!taskId) return;
    const detail = ensureDetailPortal();
    document.body.classList.add("petit-univ-manage-open");
    detail?.focus?.({ preventScroll: true });
  };

  const handleHudAction = (event) => {
    if (!active()) return;
    const target = event.target instanceof Element ? event.target : null;

    if (target?.closest?.(".univ-webgl-label--core")) {
      window.PetitUnivSpace?.reset?.();
      return;
    }

    const button = target?.closest?.("[data-univ-action]");
    if (!button || !viewport()?.contains(button)) return;

    const action = button.dataset.univAction;
    if (!["overview", "reset", "focus", "manage", "zoom-in", "zoom-out"].includes(action)) return;
    event.preventDefault();
    event.stopImmediatePropagation();

    if (action === "overview" || action === "reset") {
      window.PetitUnivSpace?.reset?.();
      webgl().reset?.();
    }
    if (action === "zoom-in") webgl().zoomIn?.();
    if (action === "zoom-out") webgl().zoomOut?.();
    if (action === "focus") {
      const taskId = window.PetitUnivSpace?.state?.().selectedTaskId;
      if (taskId) webgl().focusTask?.(taskId);
    }
    if (action === "manage") openDetail();
  };

  const initialize = () => {
    document.addEventListener("click", handleHudAction, true);
    bindCanvas();
    if (!boundCanvas) {
      observer = new MutationObserver(bindCanvas);
      observer.observe(document.documentElement, { childList: true, subtree: true });
    }
    window.addEventListener("petit:univ-webgl-rendered", () => {
      document.body.classList.remove("petit-univ-webgl-fallback");
      ensureDetailPortal();
      bindCanvas();
    });
  };

  window.PetitUnivWebGLBridge = {
    initialized: true,
    bindCanvas,
    ensureDetailPortal,
    openDetail,
    disconnect: () => observer?.disconnect(),
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
