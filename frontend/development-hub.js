// Development Hub: read-only view of the existing opt-in WorkspaceObserver cache.
// Never fetch Git remotes, inspect arbitrary paths, or execute a coding agent.
(() => {
  "use strict";

  const summarizeSnapshot = (snapshot) => {
    if (!snapshot || snapshot.enabled === false || snapshot.status === "disabled") {
      return { state: "disabled", projects: [], collectedAt: null };
    }
    if (snapshot.status !== "observed" || snapshot.stale) {
      return { state: "stale", projects: [], collectedAt: snapshot.collected_at || null };
    }
    const projects = (Array.isArray(snapshot.workspaces) ? snapshot.workspaces : []).slice(0, 8)
      .map((item) => {
        const detail = item && item.development && typeof item.development === "object" ? item.development : {};
        return {
          id: String(item?.workspace_id || ""),
          name: String(item?.name || "無名のリポジトリ").slice(0, 120),
          status: item?.status === "ok" ? "ok" : "unavailable",
          branch: String(item?.branch || "不明").slice(0, 120),
          changes: Number.isInteger(item?.changed_entries) ? Math.max(0, item.changed_entries) : null,
          conflicts: Number.isInteger(item?.conflicts) ? Math.max(0, item.conflicts) : null,
          head: typeof detail.head_sha === "string" ? detail.head_sha.slice(0, 12) : "",
          upstream: typeof detail.upstream === "string" ? detail.upstream.slice(0, 120) : "",
          ahead: Number.isInteger(detail.upstream_ahead) ? detail.upstream_ahead : null,
          behind: Number.isInteger(detail.upstream_behind) ? detail.upstream_behind : null,
          commits: Array.isArray(detail.recent_commits) ? detail.recent_commits.slice(0, 5) : [],
          documents: Array.isArray(detail.documents) ? detail.documents.filter((d) =>
            ["Concept.md", "PROGRESS.md", "README.md"].includes(d?.name)) : [],
          evidence: Boolean(item?.development),
        };
      });
    return { state: "ready", projects, collectedAt: snapshot.collected_at || null };
  };

  // Keep a pure transformation available to the Node contract test.
  window.PetitDevelopmentHub = { summarizeSnapshot };

  const panel = document.querySelector('[data-view-panel="development"]');
  const list = document.getElementById("development-projects");
  const state = document.getElementById("development-state");
  const refresh = document.getElementById("development-refresh");
  if (!panel || !list || !state || !refresh) return;

  const node = (tag, content, className) => {
    const result = document.createElement(tag);
    if (content != null) result.textContent = String(content);
    if (className) result.className = className;
    return result;
  };
  const time = (value) => {
    const parsed = Date.parse(value || "");
    return Number.isFinite(parsed) ? new Date(parsed).toLocaleString("ja-JP") : "時刻未確認";
  };

  const message = (title, detail) => {
    const item = node("section", null, "development-empty");
    item.append(node("h2", title), node("p", detail));
    list.replaceChildren(item);
  };

  const renderProject = (data) => {
    const card = node("article", null, "development-project");
    const header = node("div", null, "development-project__header");
    const heading = node("h2", data.name);
    const badge = node("span", data.status === "ok" ? "ローカル観測" : "取得不可", "development-badge");
    badge.dataset.status = data.status;
    header.append(heading, badge);
    card.append(header);

    const stats = node("dl", null, "development-project__stats");
    const field = (label, value) => {
      stats.append(node("dt", label), node("dd", value));
    };
    field("ブランチ", data.branch);
    field("HEAD", data.head || "取得できず");
    field("変更", data.changes === null ? "未確認" : data.changes + "件");
    field("コンフリクト", data.conflicts === null ? "未確認" : data.conflicts + "件");
    field("追跡ブランチ", data.upstream || "未設定／不明");
    field("ahead / behind", data.ahead === null || data.behind === null
      ? "未確認" : data.ahead + " / " + data.behind + "（ローカル参照）");
    card.append(stats);

    if (!data.evidence) {
      card.append(node("p", "詳細観測が無効か、情報を取得できませんでした。", "development-muted"));
      return card;
    }
    const details = node("details", null, "development-project__details");
    details.append(node("summary", "最近のコミット・プロジェクト文書"));
    const commits = node("ul");
    if (!data.commits.length) commits.append(node("li", "コミット情報は未取得"));
    for (const commit of data.commits) {
      commits.append(node("li", String(commit.sha || "") + "  " + String(commit.subject || "題名なし").slice(0, 150)));
    }
    details.append(node("h3", "最近のコミット"), commits);
    const documents = node("ul");
    if (!data.documents.length) documents.append(node("li", "文書情報は未取得"));
    for (const doc of data.documents) {
      documents.append(node("li", doc.name + "："
        + (doc.status === "ok" ? "あり（更新 " + time(doc.modified_at) + "）" : String(doc.status || "不明"))));
    }
    details.append(node("h3", "ルート文書（本文は表示しない）"), documents);
    card.append(details);
    return card;
  };

  let loading = false;
  let lastLoaded = 0;
  let requestNumber = 0;
  const load = async (force = false) => {
    if (loading || (!force && Date.now() - lastLoaded < 30000)) return;
    loading = true;
    const current = ++requestNumber;
    refresh.disabled = true;
    state.textContent = "ローカル開発状況を取得中…";
    try {
      const response = await fetch("/api/workspace-context", {
        credentials: "same-origin", cache: "no-store", signal: AbortSignal.timeout(10000),
      });
      if (!response.ok) throw new Error(response.status === 401
        ? "管理者ログインが必要です。" : "接続エラー（HTTP " + response.status + "）");
      const result = summarizeSnapshot(await response.json());
      if (requestNumber !== current) return;
      lastLoaded = Date.now();
      if (result.state === "disabled") {
        state.textContent = "PC観測はOFF";
        message("ローカル開発観測が無効です",
          "環境変数 PETIT_WORKSPACE_CONTEXT_ENABLED=1 と PETIT_WORKSPACE_LOCAL_DEVELOPMENT_ENABLED=1 を設定し、PETIT_WORKSPACE_CONTEXT_DIRS に許可するGitルートを登録してください。");
      } else if (result.state === "stale") {
        state.textContent = "観測待ち・古い情報：" + time(result.collectedAt);
        message("最新の開発状況を確認できません",
          "PC側Observerがまだ取得していないか、保存した観測結果が古くなっています。ローカルPCのPETIT起動状態を確認してください。");
      } else {
        state.textContent = "最終観測：" + time(result.collectedAt) + " · " + result.projects.length + "プロジェクト";
        if (!result.projects.length) {
          message("登録済みのリポジトリがありません", "許可されたGitルートを設定すると、ここに一覧が表示されます。");
        } else {
          list.replaceChildren(...result.projects.map(renderProject));
        }
      }
    } catch (error) {
      state.textContent = error.message || "取得に失敗しました。";
      if (!list.childElementCount) message("表示できません", "接続状態とログイン状態を確認し、更新してください。");
    } finally {
      loading = false;
      refresh.disabled = false;
    }
  };

  refresh.addEventListener("click", () => void load(true));
  window.addEventListener("petit:area-change", (event) => {
    if (event.detail?.area === "development") void load();
  });
  window.PetitDevelopmentHub.reload = () => load(true);
  if (!panel.hidden) void load();
})();
