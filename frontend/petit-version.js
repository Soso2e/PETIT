window.PETIT_VERSION = "v0.4.0";

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-petit-version]").forEach((element) => {
    element.textContent = window.PETIT_VERSION;
  });
});
