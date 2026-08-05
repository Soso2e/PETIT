window.PETIT_VERSION = "v0.17.0";
window.PETIT_ASSET_VERSION = "0.17.0";

(() => {
  const forceCssRenderer = new URLSearchParams(window.location.search).get("renderer") === "css";

  const loadStylesheet = (href, key) => {
    const selector = `link[data-petit-bootstrap="${key}"]`;
    const existing = document.querySelector(selector);
    if (existing) return existing;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `${href}?v=${window.PETIT_ASSET_VERSION}`;
    link.dataset.petitBootstrap = key;
    document.head.appendChild(link);
    return link;
  };

  const loadScript = (src, key, onLoad = null, { module = false } = {}) => {
    const selector = `script[data-petit-bootstrap="${key}"]`;
    const existing = document.querySelector(selector);
    if (existing) {
      if (typeof onLoad === "function") {
        if (existing.dataset.loaded === "true") onLoad();
        else existing.addEventListener("load", onLoad, { once: true });
      }
      return existing;
    }

    const script = document.createElement("script");
    script.src = `${src}?v=${window.PETIT_ASSET_VERSION}`;
    script.async = false;
    if (module) script.type = "module";
    script.dataset.petitBootstrap = key;
    script.addEventListener("load", () => {
      script.dataset.loaded = "true";
      onLoad?.();
    }, { once: true });
    document.head.appendChild(script);
    return script;
  };

  const loadWebGLScene = () => {
    loadScript("/static/universe-webgl-scene.js", "universe-webgl-scene", null, { module: true });
    loadScript("/static/universe-webgl-bridge.js", "universe-webgl-bridge");
  };

  const loadPostShellAssets = () => {
    loadStylesheet("/static/universe-3d-foundation.css", "universe-3d-foundation");
    loadScript("/static/petit-corner-shell.js", "corner-shell");
    if (forceCssRenderer) return;
    loadStylesheet("/static/universe-webgl-scene.css", "universe-webgl-scene-style");
    loadScript("/static/universe-webgl-hierarchy.js", "universe-webgl-hierarchy", loadWebGLScene);
  };

  const loadAppShell = () => {
    const existingShell = document.querySelector('script[data-petit-bootstrap="app-shell"]');
    if (existingShell) {
      if (window.PetitAppShell) loadPostShellAssets();
      else existingShell.addEventListener("load", loadPostShellAssets, { once: true });
      return;
    }
    loadScript("/static/app_shell.js", "app-shell", loadPostShellAssets);
  };

  loadScript("/static/univ-detail-children.js", "univ-detail-children");

  if (window.PetitUniverseRenderScheduler?.initialized) {
    loadAppShell();
  } else {
    loadScript("/static/universe-render-scheduler.js", "universe-render-scheduler", loadAppShell);
  }
})();

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-petit-version]").forEach((element) => {
    element.textContent = window.PETIT_VERSION;
  });
});
