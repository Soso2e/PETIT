window.PETIT_VERSION = "v0.12.0";
window.PETIT_ASSET_VERSION = "0.12.0";

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-petit-version]").forEach((element) => {
    element.textContent = window.PETIT_VERSION;
  });
});
