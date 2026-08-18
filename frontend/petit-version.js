globalThis.PETIT_VERSION = "v0.18.0";
globalThis.PETIT_ASSET_VERSION = "0.18.0";

if (typeof window !== "undefined") {
  window.PETIT_VERSION = globalThis.PETIT_VERSION;
  window.PETIT_ASSET_VERSION = globalThis.PETIT_ASSET_VERSION;
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  (() => {
    const assetUrl = (href) => {
      const url = new URL(href, window.location.origin);
      url.searchParams.set("v", window.PETIT_ASSET_VERSION);
      return `${url.pathname}${url.search}${url.hash}`;
    };

    const writeStylesheets = (hrefs) => {
      for (const href of hrefs) {
        document.write(`<link rel="stylesheet" href="${assetUrl(href)}" />`);
      }
    };

    const writeScripts = (srcs) => {
      for (const src of srcs) {
        document.write(`<script src="${assetUrl(src)}"></script>`);
      }
    };

    window.PetitAssetVersion = {
      url: assetUrl,
      writeStylesheets,
      writeScripts,
    };

    const forceCssRenderer = new URLSearchParams(window.location.search).get("renderer") === "css";
    let runtimeStarted = false;
    let webglRequested = false;

    const loadStylesheet = (href, key) => {
      const selector = `link[data-petit-bootstrap="${key}"]`;
      const existing = document.querySelector(selector);
      if (existing) return existing;
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = assetUrl(href);
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
      script.src = assetUrl(src);
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

    const ensureWebGLAssets = () => {
      if (forceCssRenderer || webglRequested) return;
      webglRequested = true;
      loadStylesheet("/static/universe-webgl-scene.css", "universe-webgl-scene-style");
      loadScript("/static/universe-webgl-hierarchy.js", "universe-webgl-hierarchy", loadWebGLScene);
    };

    const installDeferredWebGL = () => {
      if (forceCssRenderer) return;
      const universePanel = document.querySelector('[data-view-panel="universe"]');
      if (universePanel && !universePanel.hidden) ensureWebGLAssets();

      document.addEventListener("click", (event) => {
        const target = event.target instanceof Element ? event.target.closest('[data-view="universe"]') : null;
        if (target) ensureWebGLAssets();
      }, true);
    };

    const loadPostShellAssets = () => {
      loadStylesheet("/static/universe-3d-foundation.css", "universe-3d-foundation");
      loadScript("/static/petit-corner-shell.js", "corner-shell");
      installDeferredWebGL();
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

    const startRuntime = () => {
      if (runtimeStarted) return;
      runtimeStarted = true;
      loadStylesheet("/static/petit-ui-preferences.css", "ui-preferences-style");
      loadScript("/static/petit-ui-preferences.js", "ui-preferences");
      loadScript("/static/univ-detail-children.js", "univ-detail-children");
      if (window.PetitUniverseRenderScheduler?.initialized) {
        loadAppShell();
      } else {
        loadScript("/static/universe-render-scheduler.js", "universe-render-scheduler", loadAppShell);
      }
    };

    window.PetitVersionBootstrap = { start: startRuntime };

    const refreshServiceWorker = async () => {
      if (!("serviceWorker" in navigator)) return;
      try {
        const registration = await navigator.serviceWorker.register("/service-worker.js", {
          scope: "/",
          updateViaCache: "none",
        });
        window.__PETIT_SERVICE_WORKER_PROMISE = Promise.resolve(registration);

        let reloading = false;
        navigator.serviceWorker.addEventListener("controllerchange", () => {
          if (reloading) return;
          const key = `petit-sw-refresh-${window.PETIT_ASSET_VERSION}`;
          if (sessionStorage.getItem(key) === "1") return;
          reloading = true;
          sessionStorage.setItem(key, "1");
          window.location.reload();
        });

        await registration.update();
      } catch (error) {
        console.debug("PETIT Service Worker update skipped", error);
      }
    };

    window.addEventListener("load", refreshServiceWorker, { once: true });
  })();

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-petit-version]").forEach((element) => {
      element.textContent = window.PETIT_VERSION;
    });
  });
}
