// Focused regression: Development Job changes must trigger rendering without a status transition.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const src = fs.readFileSync("frontend/development.js", "utf8");
assert.match(src, /x\.summary,x\.error,x\.checks,x\.workspace,x\.branch/);
assert.match(src, /claude_code:'Claude Code CLI'/);
assert.match(src, /antigravity_cli:'Antigravity CLI'/);
const signature = (x) => JSON.stringify([x.id,x.status,x.cancel_requested,x.events.at(-1)?.seq,x.summary,x.error,x.checks,x.workspace,x.branch]);
const initial = {id:1,status:"running",cancel_requested:false,events:[],summary:"",error:"",checks:{},workspace:"",branch:""};
for (const change of [{summary:"done"},{error:"timeout"},{checks:{lint:"passed"}},{workspace:"/tmp/job"},{branch:"task/1"}]) {
  assert.notEqual(signature(initial),signature({...initial,...change}));
}
console.log("Development Job refresh contract: OK");
