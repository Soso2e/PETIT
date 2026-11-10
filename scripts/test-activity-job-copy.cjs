"use strict";
// Static regression contract for the read-only Activity ID copy action.
const fs = require("node:fs");
const assert = require("node:assert/strict");
const source = fs.readFileSync(require("node:path").join(__dirname, "../frontend/activity-jobs.js"), "utf8");
assert.match(source, /copy\.addEventListener\("click", async \(\) => \{/);
assert.match(source, /navigator\.clipboard\.writeText\(String\(job\.id\)\)/);
assert.match(source, /copy\.disabled = !job\.id/);
assert.match(source, /copy\.textContent = "コピー失敗"/);
assert.doesNotMatch(source, /navigator\.clipboard\.writeText\(.*(?:input|result|error|payload)/);
console.log("Activity job ID copy contract OK");
