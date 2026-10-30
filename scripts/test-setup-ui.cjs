/* Real Chromium + isolated HTTP server; synthetic DeepSeek, no external calls. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const python = process.env.PETIT_TEST_PYTHON || 'python';
const port = Number(process.env.PETIT_SETUP_TEST_PORT || 8893);
const url = `http://127.0.0.1:${port}`;
const live = false;
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
  await page.route('**/api/setup/services/*/models',route=>route.fulfill({json:{models:[{id:'fixture-model',label:'合成モデル'}],inference_verified:false}}));
  for(const [provider,input,key] of [['codex','codex-model','codex_model'],['antigravity_cli','antigravity-cli-model','antigravity_cli_model']]){
    await clickReady(page,`[data-models="${provider}"]`,'モデル候補を取得');
    await page.locator('#'+input+'-options').selectOption('fixture-model');
    await clickReady(page,`[data-save-model="${provider}"]`,'モデル設定を保存');
    assert.equal((await(await page.request.get(url+'/api/setup/config')).json()).settings[key],'fixture-model');
    await page.locator('#'+input).fill('');await clickReady(page,`[data-save-model="${provider}"]`,'モデル設定を保存');
  }
  results.push({cli_model_catalog_selection_and_save:true,catalog_provider:'synthetic'});
  await page.unroute('**/api/setup/services/*/models');
  await page.locator('#brain-transport').selectOption('cli_only');
  await clickReady(page,'#save-brain','AI設定を保存');
  const cliOnly=await (await page.request.get(url+'/api/setup/config')).json();
  assert.equal(cliOnly.settings.brain_transport,'cli_only');
  assert(cliOnly.brain.options.filter(x=>x.id!=='codex').every(x=>!x.permitted));
  await page.locator('#brain-transport').selectOption('mixed');
  await clickReady(page,'#save-brain','AI設定を保存');
  results.push({cli_only_saved:true,legacy_mixed_preserved:true,codex_auth_passive:'unknown'});
  await page.locator('#antigravity-cli-status').filter({hasText:'unknown'}).waitFor();
  assert.equal(await page.locator('[data-connect="antigravity_cli"]').isEnabled(),true);
  await clickReady(page,'#antigravity-cli-diagnose','CLIの配置だけを確認');
  const cliStatus=await (await page.request.get(url+'/api/setup/antigravity-cli')).json();
  assert.equal(cliStatus.production_enabled,false);assert.equal(cliStatus.authentication,'unknown');
  assert.equal((await page.request.post(url+'/api/setup/services/antigravity_cli/test',{headers:{'X-PETIT-Request':'1'}})).status(),400);
  assert.equal((await page.request.post(url+'/api/setup/services/antigravity_cli/connect',{headers:{'X-PETIT-Request':'1'}})).status(),200);
  assert.equal((await (await page.request.get(url+'/api/setup/antigravity-cli')).json()).production_enabled,true);
  await page.request.post(url+'/api/setup/services/antigravity_cli/disconnect',{headers:{'X-PETIT-Request':'1'}});
  await page.request.put(url+'/api/setup/config',{headers:{'X-PETIT-Request':'1'},data:{priority:['codex','deepseek']}});
  await clickReady(page,'#refresh','保存済み状態を更新');
  results.push({antigravity_cli:'explicit connect/disconnect',authentication:'unknown',live_cli_verified:false});
  assert.equal(await page.locator('[data-connect="antigravity"]').count(),0);
  await page.locator('#deepseek-key').fill('synthetic-key');await page.locator('#paid-deepseek').check();
  await clickReady(page,'[data-connect="deepseek"]','接続設定を保存');
  await clickReady(page,'[data-test="deepseek"]','実応答を確認');
  await page.locator('#brain-enabled').check();await clickReady(page,'#save-brain','AI設定を保存');
  await page.locator('#priority li[data-id="deepseek"]').getByRole('button',{name:'DeepSeek↑ 上へ'}).click();await page.waitForFunction(()=>document.querySelector('#priority li').dataset.id==='deepseek');
  const config=await page.request.get(url+'/api/setup/config');assert.equal((await config.json()).settings.priority[0],'deepseek');
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});for(let step=0;step<4;step++){await page.locator(`[data-step="${step}"]`).click();await page.waitForTimeout(80);const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);assert.equal(overflow,false,`overflow ${width}/${step}`);await page.screenshot({path:path.join(fixture,`setup-${width}-${step}.png`),fullPage:true});}results.push({width,steps:4,no_horizontal_overflow:true});}
  await page.locator('#complete').click();await page.waitForURL('**/static/universe.html');await page.waitForSelector('#setup-settings-card',{state:'attached'});
  const response=await page.request.post(url+'/api/chat',{headers:{'X-PETIT-Request':'1'},data:{message:'接続テストです。こんにちはと短く返答してください。',session_id:'setup-live-thread',request_id:'setup-live-hello'}});const hello=await response.json();assert(!hello.error,JSON.stringify(hello));assert.equal(hello.model_route.provider,'deepseek');
  const replay=await (await page.request.post(url+'/api/chat',{headers:{'X-PETIT-Request':'1'},data:{message:'接続テストです。こんにちはと短く返答してください。',session_id:'setup-live-thread',request_id:'setup-live-hello'}})).json();assert.equal(replay.reply,hello.reply);
  results.push({conversation:true,provider:hello.model_route.provider,replay:true,real_sdk:live});

  child.kill();await new Promise(r=>child.once('exit',r));launch();await wait();
  await page.goto(url+'/static/setup.html');await page.waitForSelector('#admin:not([hidden])');const saved=await (await page.request.get(url+'/api/setup/config')).json();assert.equal(saved.settings.priority[0],'deepseek');assert.equal(saved.settings.brain_enabled,true);assert.equal(saved.settings.completed,true);results.push({restart_settings:true,persisted_admin_session:true});
  const follow=await (await page.request.post(url+'/api/chat',{headers:{'X-PETIT-Request':'1'},data:{message:'前の会話に続いて、こんにちはと短く返答してください。',session_id:'setup-live-thread',request_id:'setup-live-follow'}})).json();assert(!follow.error,JSON.stringify(follow));results.push({restart_conversation:true,provider:follow.model_route.provider});
  assert.deepEqual(pageErrors,[]);await context.close();
  fs.writeFileSync(path.join(fixture,'result.json'),JSON.stringify({mode:live?'real provider (unused)':'synthetic provider',results},null,2));console.log(JSON.stringify({mode:live?'real provider (unused)':'synthetic provider',results,fixture}));
}finally{await browser.close();child.kill();}}
main().catch(error=>{fs.writeFileSync(path.join(fixture,'failure.json'),JSON.stringify({mode:live?'real provider (unused)':'synthetic provider',ok:false,error:String(error)},null,2));console.error(error);if(child)child.kill();process.exitCode=1;});
