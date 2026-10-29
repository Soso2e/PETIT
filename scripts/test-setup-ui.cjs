/* Real Chromium + isolated HTTP server. Pass PETIT_SETUP_REAL_SDK=1 for real local SDK. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const python = process.env.PETIT_TEST_PYTHON || 'python';
const port = 8893;
const url = `http://127.0.0.1:${port}`;
const live = process.env.PETIT_SETUP_REAL_SDK === '1';
const fixture = path.join(root,'storage','setup-e2e', `${live?'live':'browser'}-${Date.now()}`);
fs.mkdirSync(fixture,{recursive:true});
let child;
function launch(){child=spawn(python,['-m','uvicorn','tests.setup_ui_server:app','--host','127.0.0.1','--port',String(port),'--log-level','error'],{cwd:root,windowsHide:true,stdio:['ignore','ignore','pipe'],env:{...process.env,PETIT_SETUP_TEST_ROOT:fixture}});child.stderr.on('data',chunk=>{ const text=String(chunk);if(/Traceback|Error|Exception/.test(text))process.stderr.write(text.slice(-800));});}
async function wait(){for(let i=0;i<80;i++){try{if((await fetch(url+'/api/setup/session')).ok)return;}catch{}await new Promise(r=>setTimeout(r,250));}throw Error('isolated server unavailable');}
async function clickReady(page,selector,text){await page.locator(selector).click();await page.waitForFunction(({expected})=>document.querySelector('#notice').textContent.includes(expected)||document.querySelector('#notice').classList.contains('error'),{expected:text},{timeout:180000});assert(!await page.locator('#notice').evaluate(x=>x.classList.contains('error')),await page.locator('#notice').textContent());}
async function login(page){await page.goto(url+'/static/setup.html');await page.waitForSelector('#auth:not([hidden])');await page.locator('#password').fill('synthetic-setup-passphrase');await page.locator('#auth-submit').click();try{await page.waitForSelector('#admin:not([hidden])');}catch(error){throw Error('setup login failed: '+await page.locator('#notice').textContent()+'; '+String(error));}}
async function main(){launch();await wait();const browser=await chromium.launch({channel:'chrome',headless:true});const results=[];
try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();const pageErrors=[];page.on('pageerror',e=>pageErrors.push(e.message));
  await page.goto(url+'/static/universe.html');await page.waitForURL(/\/static\/setup\.html(?:\?.*)?$/);await login(page);
  await page.locator('#codex-cli-status').filter({hasText:'ChatGPT認証: 未確認'}).waitFor();
  assert.equal(await page.locator('#brain-transport').inputValue(),'mixed');
  await page.locator('#brain-transport').selectOption('cli_only');
  await clickReady(page,'#save-brain','AI設定を保存');
  const cliOnly=await (await page.request.get(url+'/api/setup/config')).json();
  assert.equal(cliOnly.settings.brain_transport,'cli_only');
  assert(cliOnly.brain.options.filter(x=>x.id!=='codex').every(x=>!x.permitted));
  await page.locator('#brain-transport').selectOption('mixed');
  await clickReady(page,'#save-brain','AI設定を保存');
  results.push({cli_only_saved:true,legacy_mixed_preserved:true,codex_auth_passive:'unknown'});
  await page.locator('#antigravity-cli-status').filter({hasText:'unknown'}).waitFor();
  assert.equal(await page.getByRole('button',{name:'接続・有効化（許諾確認待ち）'}).isDisabled(),true);
  await clickReady(page,'#antigravity-cli-diagnose','CLIの配置だけを確認');
  const cliStatus=await (await page.request.get(url+'/api/setup/antigravity-cli')).json();
  assert.equal(cliStatus.production_enabled,false);assert.equal(cliStatus.authentication,'unknown');
  for(const operation of ['connect','test'])assert.equal((await page.request.post(url+'/api/setup/services/antigravity_cli/'+operation,{headers:{'X-PETIT-Request':'1'}})).status(),409);
  results.push({antigravity_cli:'production blocked',authentication:'unknown',live_cli_verified:false});
  await page.locator('#antigravity-model').fill('petit-setup-probe');await clickReady(page,'[data-connect="antigravity"]','接続設定を保存');
  await clickReady(page,'[data-test="antigravity"]','実応答を確認');
  await page.locator('#brain-enabled').check();await clickReady(page,'#save-brain','AI設定を保存');
  await page.locator('#priority li[data-id="antigravity"]').getByRole('button',{name:'Antigravity SDK↑ 上へ'}).click();await page.waitForFunction(()=>document.querySelector('#priority li').dataset.id==='antigravity');
  const config=await page.request.get(url+'/api/setup/config');assert.equal((await config.json()).settings.priority[0],'antigravity');
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});for(let step=0;step<4;step++){await page.locator(`[data-step="${step}"]`).click();await page.waitForTimeout(80);const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);assert.equal(overflow,false,`overflow ${width}/${step}`);await page.screenshot({path:path.join(fixture,`setup-${width}-${step}.png`),fullPage:true});}results.push({width,steps:4,no_horizontal_overflow:true});}
  await page.locator('#complete').click();await page.waitForURL('**/static/universe.html');await page.waitForSelector('#setup-settings-card',{state:'attached'});
  const response=await page.request.post(url+'/api/chat',{headers:{'X-PETIT-Request':'1'},data:{message:'接続テストです。こんにちはと短く返答してください。',session_id:'setup-live-thread',request_id:'setup-live-hello'}});const hello=await response.json();assert(!hello.error,JSON.stringify(hello));assert.equal(hello.model_route.provider,'antigravity_sdk');
  const replay=await (await page.request.post(url+'/api/chat',{headers:{'X-PETIT-Request':'1'},data:{message:'接続テストです。こんにちはと短く返答してください。',session_id:'setup-live-thread',request_id:'setup-live-hello'}})).json();assert.equal(replay.reply,hello.reply);
  results.push({conversation:true,provider:hello.model_route.provider,replay:true,real_sdk:live});
  if(live){
    const write=await (await page.request.post(url+'/api/chat',{headers:{'X-PETIT-Request':'1'},data:{message:'合成Tool契約の検証です。petit_read_toolを必ず呼び、nameはsave_memory、arguments_jsonはJSON文字列 {"content":"合成検証コードは SETUP-ORBIT-25"} としてください。呼び出し結果を確認してから短く答えてください。',session_id:'setup-live-thread',request_id:'setup-live-memory'}})).json();assert(!write.error,JSON.stringify(write));assert(write.used_tools.some(x=>x.name==='save_memory'),JSON.stringify(write));
    const read=await (await page.request.post(url+'/api/chat',{headers:{'X-PETIT-Request':'1'},data:{message:'合成Tool契約の検証です。petit_read_toolを呼び、nameはget_schedule、arguments_jsonはJSON文字列 {"date":"2026-10-25"} としてください。',session_id:'setup-live-thread',request_id:'setup-live-schedule'}})).json();assert(!read.error,JSON.stringify(read));assert(read.used_tools.some(x=>x.name==='get_schedule'),JSON.stringify(read));
    const pending=await (await page.request.post(url+'/api/chat',{headers:{'X-PETIT-Request':'1'},data:{message:'合成Tool契約の検証です。petit_read_toolを必ず呼び、nameはadd_schedule、arguments_jsonはJSON文字列 {"title":"合成UI承認テスト","start_time":"2026-10-25T12:00:00+09:00","end_time":"2026-10-25T13:00:00+09:00"} としてください。確認待ちなら直ちに返答を終了してください。',session_id:'setup-live-thread',request_id:'setup-live-approval'}})).json();assert(!pending.error,JSON.stringify(pending));assert.equal(pending.status,'waiting_approval',JSON.stringify(pending));
    const decision=await (await page.request.post(url+'/api/actions/'+pending.pending_actions[0].approval_id,{headers:{'X-PETIT-Request':'1'},data:{approved:true}})).json();assert(!decision.error,JSON.stringify(decision));assert.equal(decision.status,'completed',JSON.stringify(decision));
    results.push({real_sdk_read_tool:true,real_sdk_memory_write:true,real_sdk_approval_resume:true,explicit_bridge_contract_prompts:true});
  }

  child.kill();await new Promise(r=>child.once('exit',r));launch();await wait();
  await page.goto(url+'/static/setup.html');await login(page);const saved=await (await page.request.get(url+'/api/setup/config')).json();assert.equal(saved.settings.priority[0],'antigravity');assert.equal(saved.settings.brain_enabled,true);assert.equal(saved.settings.completed,true);results.push({restart_settings:true,reauthentication_required:true});
  const follow=await (await page.request.post(url+'/api/chat',{headers:{'X-PETIT-Request':'1'},data:{message:'前の会話に続いて、こんにちはと短く返答してください。',session_id:'setup-live-thread',request_id:'setup-live-follow'}})).json();assert(!follow.error,JSON.stringify(follow));results.push({restart_conversation:true,provider:follow.model_route.provider});
  if(live){
    // Synthetic stale connection flag only. Codex's official auth home is still unauthenticated.
    execFileSync(python,['-c',"from backend import setup_store as s; d=s.load(); s.update({'connected': sorted(set(d['connected'])|{'codex'}), 'priority':['codex','antigravity','deepseek']})"],{cwd:root,windowsHide:true,env:{...process.env,PETIT_SETTINGS_DIR:path.join(fixture,'settings')}});
    const fallback=await (await page.request.post(url+'/api/chat',{headers:{'X-PETIT-Request':'1'},data:{message:'合成の接続確認です。こんにちはと短く返答してください。',session_id:'setup-fallback-thread',request_id:'setup-fallback-real'}})).json();assert(!fallback.error,JSON.stringify(fallback));assert.equal(fallback.model_route.provider,'antigravity_sdk');assert.equal(fallback.model_route.fallback,true);assert.equal(fallback.model_route.fallback_reason,'authentication_expired');
    results.push({fallback:'real unauthenticated Codex -> real local SDK',stale_connection_fixture:true,reason:fallback.model_route.fallback_reason});
  }
  assert.deepEqual(pageErrors,[]);await context.close();
  fs.writeFileSync(path.join(fixture,'result.json'),JSON.stringify({mode:live?'real SDK + real LM Studio':'synthetic provider',results},null,2));console.log(JSON.stringify({mode:live?'real SDK + real LM Studio':'synthetic provider',results,fixture}));
}finally{await browser.close();child.kill();}}
main().catch(error=>{fs.writeFileSync(path.join(fixture,'failure.json'),JSON.stringify({mode:live?'real SDK + real LM Studio':'synthetic provider',ok:false,error:String(error)},null,2));console.error(error);if(child)child.kill();process.exitCode=1;});
