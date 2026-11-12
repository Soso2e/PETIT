"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "../frontend/activity-jobs.js"), "utf8");
const context = { window: {}, document: { querySelector: () => null } };
vm.runInNewContext(source, context);
const { summarize, matchesJobId } = context.window.PetitActivityJobs;
const rows = summarize({ jobs: [
  { id: 42, type: "durable_read", status: "running", updated_at: "2026-11-11T00:00:00Z" },
  { id: 420, type: "durable_read", status: "done" },
  { id: 7, type: "background_research", status: "failed" },
] }).jobs;
assert.equal(rows.length, 3);
assert.equal(rows.filter((job) => matchesJobId(job, "42")).length, 1, "ID must match exactly");
assert.equal(rows.filter((job) => matchesJobId(job, "")).length, 3, "empty query lists all");
assert.equal(rows.filter((job) => matchesJobId(job, "999")).length, 0);
assert.equal(rows.filter((job) => matchesJobId(job, "42") && job.status === "running").length, 1);
assert.equal(rows.filter((job) => matchesJobId(job, "42") && job.status === "failed").length, 0);
assert.equal("result" in rows[0], false, "no secret job result is projected");
console.log("Activity job ID lookup contracts passed");
