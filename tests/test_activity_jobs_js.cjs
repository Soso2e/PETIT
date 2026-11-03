const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function project(payload) {
  const window = {};
  const document = { querySelector: () => null };
  const source = fs.readFileSync(path.join(__dirname, "..", "frontend", "activity-jobs.js"), "utf8");
  vm.runInNewContext(source, { window, document }, { timeout: 1000 });
  return window.PetitActivityJobs.summarize(payload);
}

test("activity includes bounded statuses and never projects raw model inputs and output", () => {
  const result = project({ jobs: [{ id: 4, status: "running", type: "background_research",
    created_at: "2026-11-03T00:00:00Z", result_text: "PRIVATE_RESPONSE",
    input_json: "PRIVATE_PROMPT", error: "PRIVATE_ERROR", updated_at: "2026-11-03T00:00:00Z" }],
    coding_jobs_included: false });
  assert.equal(result.jobs[0].id, 4);
  assert.equal(result.jobs[0].status, "running");
  assert.equal(result.excludesCoding, true);
  assert.ok(!JSON.stringify(result).includes("PRIVATE_"));
});

test("unknown state is not reported as completed", () => {
  assert.equal(project({ jobs: [{ id: 1, status: "stuck" }] }).jobs[0].status, "unknown");
  assert.equal(project({ jobs: [{ id: 2, status: "done" }] }).jobs[0].status, "done");
});

test("invalid input and large job counts stay bounded", () => {
  assert.equal(project({ jobs: null }).jobs.length, 0);
  assert.equal(project({ jobs: Array.from({ length: 120 }, (_, id) => ({ id })) }).jobs.length, 100);
});
