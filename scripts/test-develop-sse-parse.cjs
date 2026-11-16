// Regression: malformed SSE payloads must not stop subsequent Develop updates.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../frontend/development.js"), "utf8");
const match = source.match(/    const parseEvent = \(event\) => \{[\s\S]*?\n    \};/);
assert.ok(match, "Develop progress parser exists");
const parseEvent = vm.runInNewContext(match[0].trim().replace(/^const parseEvent = /, "").replace(/;$/, ""));
assert.deepEqual(JSON.parse(JSON.stringify(parseEvent({data:'{"status":"running","phase":"model_request"}'}))), {status:"running",phase:"model_request"});
assert.equal(parseEvent({data:"{broken"}), null);
assert.equal(parseEvent({data:""}), null);
assert.equal(parseEvent({data:"null"}), null);
assert.equal(parseEvent({data:'{"status":"completed"}'}).status, "completed");
console.log("Develop SSE parse regression: OK");
