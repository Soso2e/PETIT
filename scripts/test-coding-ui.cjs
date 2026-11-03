/* Real browser/HTTP, synthetic coding agent and repository. No account inference. */
const { chromium }=require('playwright');
const { spawn }=require('node:child_process');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const root=path.resolve(__dirname,'..'),port=8896,url=`http://127.0.0.1:${port}`;
const fixture=path.join(root,'storage','coding-e2e','browser-'+Date.now());fs.mkdirSync(fixture,{recursive:true});
let child,browser;
async function main(){child=spawn(process.env.PETIT_TEST_PYTHON||'python',['-m','uvicorn','tests.coding_ui_server:app','--host','127.0.0.1','--port',String(port),'--log-level','error'],{cwd:root,windowsHide:true,stdio:['ignore','ignore','pipe'],env:{...process.env,PETIT_SETUP_TEST_ROOT:fixture}});let errors='';child.stderr.on('data',x=>{errors+=String(x);});
try{let ready=false;for(let i=0;i<100;i++){try{if((await fetch(url+'/api/setup/session')).ok){ready=true;break;}}catch{}await new Promise(r=>setTimeout(r,200));}assert(ready,errors.slice(-1500));
browser=await chromium.launch({channel:'chrome',headless:true});const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();const pageErrors=[];page.on('pageerror',x=>pageErrors.push(x.message));
await page.goto(url+'/static/setup.html');await page.locator('#auth:not([hidden])').waitFor();await page.locator('#password').fill('synthetic-coding-passphrase');await page.locator('#auth-submit').click();await page.locator('#codex-cli-status').filter({hasText:'ChatGPT認証: 未確認'}).waitFor();
await page.goto(url+'/static/development.html');await page.locator('#content:not([hidden])').waitFor();await page.locator('#goal').fill('合成タスク: answer.pyのANSWERを2へ変更してください');await page.locator('#propose').click();await page.getByRole('button',{name:'この対象・目的・CLIで開始'}).waitFor();assert.equal((await(await page.request.get(url+'/api/coding/jobs')).json()).jobs[0].status,'proposed');
await page.getByRole('button',{name:'この対象・目的・CLIで開始'}).click();await page.locator('.job-status').filter({hasText:'レビュー待ち'}).waitFor({timeout:30000});await page.getByRole('button',{name:'変更ファイル・差分を見る'}).click();await page.locator('.diff').filter({hasText:'+ANSWER = 2'}).waitFor();assert.equal(fs.readFileSync(path.join(fixture,'fixture-repository','answer.py'),'utf8').trim(),'ANSWER = 1');
for(const width of [1440,390]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);await page.screenshot({path:path.join(fixture,`development-${width}.png`),fullPage:true});}
await page.reload();await page.locator('.job-status').filter({hasText:'レビュー待ち'}).waitFor();await page.getByRole('button',{name:'差分を確認したのでレビュー完了'}).click();await page.locator('.job-status').filter({hasText:'利用者がレビュー完了'}).waitFor();assert.deepEqual(pageErrors,[]);assert(!/Traceback/.test(errors),errors.slice(-1500));console.log(JSON.stringify({provider:'synthetic',approval:true,source_unchanged:true,diff:true,reload:true,manual_completion:true,widths:[1440,390],fixture}));
}finally{if(browser)await browser.close();if(child)child.kill();}}
main().catch(e=>{console.error(e);process.exitCode=1;});
