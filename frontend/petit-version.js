window.PETIT_VERSION = "v0.3.0";

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-petit-version]").forEach((element) => {
    element.textContent = window.PETIT_VERSION;
  });
});
