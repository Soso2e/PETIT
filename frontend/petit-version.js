window.PETIT_VERSION = "v0.14.1";
window.PETIT_ASSET_VERSION = "0.14.1";

(() => {
  const loadCornerShell = () => {
    if (document.querySelector('script[data-petit-bootstrap="corner-shell"]')) return;
    const script = document.createElement("script");
    script.src = `/static/petit-corner-shell.js?v=${window.PETIT_ASSET_VERSION}`;
    script.async = false;
    script.dataset.petitBootstrap = "corner-shell";
    document.head.appendChild(script);
  };

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
