/* Contract tests for the read-only Development Hub projection. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function project(snapshot) {
  const window = {};
  const document = { querySelector: () => null, getElementById: () => null };
  const source = fs.readFileSync(path.join(__dirname, "..", "frontend", "development-hub.js"), "utf8");
  vm.runInNewContext(source, { window, document }, { timeout: 1000 });
  return window.PetitDevelopmentHub.summarizeSnapshot(snapshot);
}

test("disabled workspace observation is explicitly disabled, not an empty success", () => {
  const value = project({ enabled: false, status: "disabled" });
  assert.equal(value.state, "disabled");
  assert.equal(value.projects.length, 0);
});

test("pending and stale observations do not masquerade as current evidence", () => {
  assert.equal(project({ enabled: true, status: "pending" }).state, "stale");
  assert.equal(project({ enabled: true, status: "observed", stale: true }).state, "stale");
});

test("only bounded local evidence is projected, never document excerpts or file paths", () => {
  const value = project({ enabled: true, status: "observed", stale: false, collected_at: "2026-11-03T00:00:00Z",
    workspaces: [{ workspace_id: "abc", name: "WEVORA", status: "ok", branch: "feat/ui",
      changed_entries: 3, conflicts: 1, files: [{ path: ".env" }],
      development: { head_sha: "1234567890abcdef", upstream: "origin/main", upstream_ahead: 2, upstream_behind: 0,
        recent_commits: [{ sha: "12345", subject: "Add VFX" }],
        documents: [{ name: "PROGRESS.md", status: "ok", excerpt: "PRIVATE_CONTENT", modified_at: "2026-11-03T00:00:00Z" }] }] });
  assert.equal(value.state, "ready");
  assert.equal(value.projects[0].head, "1234567890ab");
  assert.equal(value.projects[0].changes, 3);
  assert.equal(value.projects[0].documents[0].name, "PROGRESS.md");
  assert.equal(value.projects[0].documents[0].excerpt, undefined);
  assert.equal(value.projects[0].files, undefined);
  assert.equal(value.projects[0].status, "ok");
});

test("missing Git development data remains visibly unverified", () => {
  const value = project({ enabled: true, status: "observed", stale: false, workspaces: [
    { name: "no data", status: "unavailable" }] });
  assert.equal(value.projects[0].evidence, false);
  assert.equal(value.projects[0].changes, null);
  assert.equal(value.projects[0].ahead, null);
  assert.equal(project({ enabled: true, status: "observed", stale: false, workspaces: [
    { name: "null evidence", status: "ok", development: null }] }).projects[0].evidence, false);
});

test("snapshot and document catalog are bounded", () => {
  const workspaces = Array.from({ length: 15 }, (_, i) => ({
    name: "repo-" + i, status: "ok", development: {
      documents: [{ name: "Concept.md" }, { name: ".env" }, { name: "README.md" }],
      recent_commits: Array.from({ length: 20 }, (_, j) => ({ subject: "commit-" + j })),
    },
  }));
  const result = project({ enabled: true, status: "observed", stale: false, workspaces });
  assert.equal(result.projects.length, 8);
  assert.equal(result.projects[0].documents.length, 2);
  assert.equal(result.projects[0].commits.length, 5);
});
