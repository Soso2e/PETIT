const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function project(payload) {
  const window = {};
  const document = { querySelector: () => null };
  const source = fs.readFileSync(path.join(__dirname, "..", "frontend", "coding-activity.js"), "utf8");
  vm.runInNewContext(source, { window, document }, { timeout: 1000 });
  return window.PetitCodingActivity.summarize(payload);
}

test("coding activity is a bounded, private status projection", () => {
  const value = project({ initialized: true, jobs: [{
    id: "0123456789abcdef", task_id: 22, provider: "antigravity_cli", status: "ready_for_review",
    updated_at: "2026-11-03T00:00:00Z", goal: "PRIVATE_GOAL",
    repository: "PRIVATE_PATH", summary: "PRIVATE_OUTPUT", error: "PRIVATE_EXCEPTION",
  }] });
  assert.equal(value.jobs[0].status, "ready_for_review");
  assert.equal(value.jobs[0].provider, "Antigravity CLI");
  assert.equal(value.jobs[0].taskId, 22);
  assert.equal(value.jobs[0].id, "0123456789abcdef");
  assert.ok(!JSON.stringify(value).includes("PRIVATE_"));
});

test("uninitialized and invalid states are not reported as completed", () => {
  assert.equal(project({ initialized: false, jobs: [] }).initialized, false);
  assert.equal(project({ initialized: true, jobs: [{ status: "some_new_state" }] }).jobs[0].status, "unknown");
});

test("huge payloads are bounded", () => {
  const result = project({ initialized: true, jobs: Array.from({ length: 130 }, (_, i) => ({ id: "id-" + i })) });
  assert.equal(result.jobs.length, 100);
});
