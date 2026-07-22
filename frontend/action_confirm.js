// Treat a short conversational reply as the decision for the latest pending action.
(() => {
  const approvePhrases = new Set([
    "はい", "うん", "お願い", "お願いします", "してほしい", "やって", "やってください",
    "実行", "実行して", "実行してください", "それで", "それでお願い",
    "ok", "okay", "オーケー",
  ]);
  const cancelPhrases = new Set([
    "いいえ", "いや", "やめて", "やめる", "キャンセル", "取り消し",
    "実行しない", "しないで", "中止",
  ]);

  function normalizeDecision(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/[\s、。,.!！?？]/g, "")
      .trim();
  }

  function latestPendingControls() {
    const candidates = Array.from(messagesEl.querySelectorAll(".action-confirm")).reverse();
    for (const controls of candidates) {
      const buttons = controls.querySelectorAll("button");
      if (buttons.length >= 2 && !buttons[0].disabled && !buttons[1].disabled) {
        return { approve: buttons[0], cancel: buttons[1] };
      }
    }
    return null;
  }

  formEl.addEventListener("submit", (event) => {
    const text = inputEl.value.trim();
    const pending = latestPendingControls();
    if (!text || !pending) return;

    const decision = normalizeDecision(text);
    const target = approvePhrases.has(decision)
      ? pending.approve
      : (cancelPhrases.has(decision) ? pending.cancel : null);
    if (!target) return;

    event.preventDefault();
    event.stopImmediatePropagation();
    inputEl.value = "";
    inputEl.style.height = "auto";
    addMessage("user", text);
    history.push({ role: "user", content: text });
    target.click();
  }, true);
})();
