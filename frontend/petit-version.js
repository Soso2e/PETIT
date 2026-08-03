window.PETIT_VERSION = "v0.13.0";
window.PETIT_ASSET_VERSION = "0.13.0";

(() => {
  if (!document.querySelector('script[data-petit-bootstrap="app-shell"]')) {
    const script = document.createElement("script");
    script.src = `/static/app_shell.js?v=${window.PETIT_ASSET_VERSION}`;
    script.async = false;
    script.dataset.petitBootstrap = "app-shell";
    document.head.appendChild(script);
  }
})();

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-petit-version]").forEach((element) => {
    element.textContent = window.PETIT_VERSION;
  });
});
