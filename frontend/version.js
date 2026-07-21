// Display the PETIT release version independently from LM Studio health.
(async function loadVersion() {
  const el = document.getElementById("app-version");
  if (!el) return;

  try {
    const response = await fetch("/static/version.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const version = String(data.version || "unknown");
    const release = String(data.release || "").trim();
    el.textContent = `v${version}`;
    el.title = release ? `PETIT v${version} (${release})` : `PETIT v${version}`;
    el.className = "status status--ok";
  } catch (error) {
    el.textContent = "v不明";
    el.title = "バージョン情報を取得できませんでした";
    el.className = "status status--bad";
  }
})();
