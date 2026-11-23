(() => {
  "use strict";

  async function request(path, options = {}) {
    const response = await fetch("/api/setup/core" + path, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", "X-PETIT-Request": "1" },
      ...options,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = typeof data.detail === "string" ? data.detail : "Coreとの接続を確認してください。";
      throw Object.assign(new Error(message), { status: response.status });
    }
    return data;
  }

  const status = () => request("", { signal: AbortSignal.timeout(3000) });

  async function restart(onRequested) {
    const previous = await status();
    if (!previous.managed) throw new Error("再起動対応のランチャーでPETIT Coreを起動してください。");

    onRequested();
    try {
      await request("/restart", {
        method: "POST",
        body: JSON.stringify({ instance: previous.instance }),
        signal: AbortSignal.timeout(5000),
      });
    } catch (error) {
      // A lost response can occur after acceptance, so poll without repeating the POST.
      if (!(error instanceof TypeError) && !["TimeoutError", "AbortError"].includes(error.name)) throw error;
    }
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 1500));
      const current = await status().catch(() => null);
      if (current?.managed && current.instance !== previous.instance && current.mode === "normal" && !current.restarting) return;
    }
    throw new Error("再起動後の接続を確認できませんでした。ホストのCore起動ログを確認してください。");
  }

  window.PetitCoreRestart = { status, restart };
})();
