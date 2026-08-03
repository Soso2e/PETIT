window.PETIT_VERSION = "v0.9.0";
window.PETIT_ASSET_VERSION = "0.9.0";

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-petit-version]").forEach((element) => {
    element.textContent = window.PETIT_VERSION;
  });
});
