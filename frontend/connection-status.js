// Saved connection/sync diagnostics. No automatic probes or synchronization.
(() => {
  const labels = { unconfigured: "未設定", unverified: "未確認", syncing: "同期中", healthy: "正常",
    connected: "接続済み", error: "エラー", conflict: "同期競合", stale: "古いキャッシュ",
    failed: "同期失敗", pending: "同期待ち", processing: "同期中" };
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const time = (value) => {
    if (!value) return "未記録";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "未記録" : date.toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" });
  };
  const request = async (url, method = "GET") => {
    const response = await fetch(url, { method, cache: "no-store", signal: AbortSignal.timeout(30000) });
    if (!response.ok) throw new Error(`状態を取得できませんでした（HTTP ${response.status}）。サーバー接続を確認してください。`);
    return response.json();
  };
  let activeDialog = null;
  const open = () => {
    if (activeDialog?.open) return;
    const previousFocus = document.activeElement;
    const dialog = element("dialog", null, "connection-dialog");
    activeDialog = dialog;
    dialog.setAttribute("aria-labelledby", "connection-title");
    const title = element("h2", "接続ステータス"); title.id = "connection-title";
    const close = element("button", "閉じる"); close.type = "button"; close.onclick = () => dialog.close();
    const header = element("div", null, "connection-header"); header.append(title, close);
    const hint = element("p", "保存済み状態を表示します。接続確認は同期を実行しません。時刻は日本時間です。", "connection-hint");
    const feedback = element("p", "読み込み中…"); feedback.setAttribute("role", "status"); feedback.setAttribute("aria-live", "polite");
    const content = element("div", null, "connection-services");
    const refresh = element("button", "保存済み状態を更新"); refresh.type = "button";
    dialog.append(header, hint, feedback, refresh, content); document.body.append(dialog);
    dialog.addEventListener("close", () => {
      dialog.remove();
      if (activeDialog === dialog) { activeDialog = null; previousFocus?.focus(); }
    });
    dialog.showModal();
    const field = (list, label, value) => { list.append(element("dt", label), element("dd", value)); };
    const action = (parent, label, callback) => {
      const button = element("button", label); button.type = "button";
      button.onclick = async () => {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        try { await callback(); }
        catch (error) { if (dialog.open) feedback.textContent = error.message || "操作に失敗しました。"; }
        finally { button.disabled = false; button.removeAttribute("aria-busy"); }
      };
      parent.append(button);
      return button;
    };
    let generation = 0;
    const load = async () => {
      const current = ++generation;
      refresh.disabled = true;
      try {
        const data = await request("/api/connections");
        if (!dialog.open || current !== generation) return;
        const expanded = new Set([...content.querySelectorAll("details[open]")].map(node => node.dataset.service));
        const focused = document.activeElement?.dataset.connectionAction;
        content.replaceChildren();
        feedback.textContent = `表示更新：${time(data.generated_at)}`;
        for (const service of data.services) {
          const details = element("details", null, "connection-service"); details.dataset.service = service.id;
          details.open = expanded.has(service.id);
          const summary = element("summary");
          summary.append(element("span", service.name));
          const badges = element("span", null, "connection-badges");
          for (const [kind, state] of [["接続", service.connection_status], ["同期", service.sync_status]]) {
            if (!state) continue;
            const badge = element("span", `${kind}：${labels[state] || "未確認"}`, "connection-badge"); badge.dataset.state = state;
            badges.append(badge);
          }
          summary.append(badges); details.append(summary);
          const list = element("dl");
          field(list, "接続", labels[service.connection_status] || "未確認");
          if (service.sync_status) field(list, "同期", labels[service.sync_status] || "未確認");
          if (service.sync_status) field(list, "同期キャッシュ", labels[service.cache_status] || "未確認");
          field(list, "最終接続成功", time(service.last_connection_success_at));
          if (service.sync_status) field(list, "最終同期成功", time(service.last_sync_success_at));
          field(list, "最終エラー", time(service.last_error_at));
          field(list, "エラー内容", service.error || "記録なし");
          field(list, "エラーコード", service.error_code || "記録なし");
          field(list, "同期失敗 / 競合", `${service.failed_count || 0}件 / ${service.conflict_count || 0}件`);
          if (service.id === "notion") field(list, "Webhook受信処理失敗", `${service.inbox_failed_count || 0}件`);
          details.append(list, element("p", service.note || "このサービスの状態を取得できませんでした。", "connection-hint"));
          if (service.can_check) {
            const button = action(details, "接続確認", async () => {
              feedback.textContent = `${service.name}の接続を確認中…`;
              await request(`/api/connections/${service.id}/check`, "POST");
              await load();
            });
            button.dataset.connectionAction = service.id;
          }
          for (const operation of service.operations || []) {
            const card = element("section", null, "connection-operation");
            card.append(element("h3", `タスク：${operation.title}`));
            const info = element("dl");
            field(info, "操作", ({ create: "作成", update: "更新" })[operation.operation] || operation.operation);
            field(info, "状態", labels[operation.status] || operation.status);
            field(info, "エラー", operation.last_error || "記録なし");
            field(info, "エラーコード", operation.error_code || "記録なし");
            field(info, "試行回数", `${operation.attempts}/${operation.max_attempts}回`);
            field(info, "最終試行", time(operation.last_attempt_at));
            field(info, "次回自動再試行", operation.next_attempt_at ? time(operation.next_attempt_at) : "予定なし");
            card.append(info);
            if (operation.status === "failed") {
              const button = action(card, "このタスクを再試行", async () => {
                try { await window.PetitTaskSyncRecovery.retrySync(operation.task_id); }
                catch (_) { throw new Error("再試行できませんでした。接続と最新の同期状態を確認してください。"); }
                await load();
                if (dialog.open) feedback.textContent = "このタスクを再試行キューへ戻しました。反映結果は同期状態で確認してください。";
              });
              button.dataset.connectionAction = `retry-${operation.id}`;
            }
            if (operation.status === "conflict") action(card, "競合を比較して解消", async () => {
              dialog.close(); await window.PetitTaskSyncRecovery.openConflict(operation.task_id);
            });
            details.append(card);
          }
          content.append(details);
        }
        if (focused) [...content.querySelectorAll("[data-connection-action]")].find(node => node.dataset.connectionAction === focused)?.focus();
      } catch (error) { if (dialog.open) feedback.textContent = `${error.message} 保存済み表示がある場合は残しています。`; }
      finally { if (current === generation) refresh.disabled = false; }
    };
    refresh.onclick = () => void load();
    void load();
  };
  document.addEventListener("click", event => {
    if (event.target.closest?.("#sync-pill, [data-rail-sync], [data-open-connections]")) open();
  });
  window.PetitConnections = { open };
})();
