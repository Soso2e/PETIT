window.PETIT_VERSION = "v0.15.0";
window.PETIT_ASSET_VERSION = "0.15.0";

(() => {
  const loadScript = (src, key) => {
    if (document.querySelector(`script[data-petit-bootstrap="${key}"]`)) return;
    const script = document.createElement("script");
    script.src = `${src}?v=${window.PETIT_ASSET_VERSION}`;
    script.async = false;
    script.dataset.petitBootstrap = key;
    document.head.appendChild(script);
  };

  const loadCornerShell = () => loadScript("/static/petit-corner-shell.js", "corner-shell");
  const loadUnivDetailChildren = () => loadScript("/static/univ-detail-children.js", "univ-detail-children");

  loadUnivDetailChildren();

  const existingShell = document.querySelector('script[data-petit-bootstrap="app-shell"]');
  if (existingShell) {
    if (window.PetitAppShell) loadCornerShell();
    else existingShell.addEventListener("load", loadCornerShell, { once: true });
    return;
  }

  const script = document.createElement("script");
  script.src = `/static/app_shell.js?v=${window.PETIT_ASSET_VERSION}`;
  script.async = false;
  script.dataset.petitBootstrap = "app-shell";
  script.addEventListener("load", loadCornerShell, { once: true });
  document.head.appendChild(script);
})();

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-petit-version]").forEach((element) => {
    element.textContent = window.PETIT_VERSION;
  });
});
