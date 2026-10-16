import { openRecovery } from './recovery-navigation.mjs';
import {test,expect} from '@playwright/test';
import {readFileSync,writeFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {setup} from './final-L1-fixture.mjs';
const receipts=process.env.PURCHASE_RECEIPTS;
const source=readFileSync('/home/lovelyuk/.hermes/profiles/aebong/cache/long-tasks/greeneat-pg-reconciliation-receipts/deeper-sdk-script.txt','utf8');
const bridge=readFileSync('/home/lovelyuk/.hermes/profiles/aebong/cache/long-tasks/greeneat-cancel-return-receipts/frame-fail-live.html');
function producer(command,payload){return JSON.parse(execFileSync(process.env.FINALIZE_FIXTURE_PYTHON,['browser/finalization-producer.py',command,...(payload?[JSON.stringify(payload)]:[])],{encoding:'utf8',env:{...process.env,RETURN_ENDED_FIXTURE:'1',ENV:'test',SUPABASE_URL:'https://fixture.invalid',SUPABASE_ANON_KEY:'synthetic',SUPABASE_SERVICE_ROLE_KEY:'synthetic'}}));}
async function fixture(page,context,{bank=false}={}){
 const seed=producer(bank?'init-bank':'init-local'), calls=[], state=await setup(page,context,{gross:1100,points:0});
 await context.route('**/api-fixture/payments/checkout/**',r=>{
   const u=new URL(r.request().url()),result=producer('request',{path:u.pathname.replace('/api-fixture','')+u.search});
   calls.push({path:u.pathname+u.search,...result});return r.fulfill({status:result.status,contentType:'text/html',body:result.html});
 });
 await page.route('**/api-fixture/me',r=>r.fulfill({json:{ok:true,data:{user_id:seed.owner,role:'customer',status:'active',display_name:'Synthetic buyer',point_balance:0,voucher_balance:0,voucher_use_history:[],point_transactions:[],recent_transactions:[]}}}));
 await page.route('**/api-fixture/coupons',r=>r.fulfill({json:{ok:true,data:{merchant:{id:'33333333-3333-4333-8333-333333333333',name:'Synthetic merchant'},items:[],issued:[]}}}));
 for(const glob of ['**/api-fixture/vouchers/products','**/api-fixture/vouchers/quote','**/api-fixture/vouchers/purchase','**/api-fixture/payments/**']) await page.route(glob,r=>{
  const u=new URL(r.request().url()),path=u.pathname.replace('/api-fixture','')+u.search;
  if(r.request().method()==='POST')expect(r.request().headers().authorization).toBe('Bearer fixture-access');
  const result=producer('request',{method:r.request().method(),path,body:r.request().postDataJSON()});calls.push({path,body:r.request().postDataJSON(),...result});return r.fulfill({status:result.status,...(result.json?{json:result.json}:{contentType:'text/html',body:result.html})});
 });
 await context.route('https://ssl-v2.kiwoompay.co.kr/sdk/**',r=>r.fulfill({contentType:'application/javascript',body:source}));
 await context.route('https://ssltest-v2.kiwoompay.co.kr/**',r=>r.request().url().includes('sdkFrameMessage')?r.fulfill({contentType:'text/html; charset=EUC-KR',body:bridge}):r.fulfill({contentType:'application/javascript',body:'function nvl(v,d){return v||d;}'}));
 await context.addInitScript(()=>{window.__channelEvents=[];const Native=BroadcastChannel;window.BroadcastChannel=class extends Native{constructor(name){super(name);this.addEventListener('message',e=>window.__channelEvents.push({origin:e.origin,data:e.data,name}));}};window.__forms=[];HTMLFormElement.prototype.submit=function(){window.__forms.push(Object.fromEntries([...this.elements].map(e=>[e.name,e.value])));};});
 await page.goto('/shop');await page.getByLabel('이메일',{exact:true}).fill('fixture@example.invalid');await page.getByLabel('비밀번호',{exact:true}).fill('mocked-password-only');await page.getByRole('button',{name:'로그인',exact:true}).click();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();
 return {seed,calls,state};
}
async function buy(page){await page.getByRole('button',{name:'Synthetic ticket 선택'}).click();await expect(page.locator('.purchase-quote')).toBeVisible();await expect(page.getByLabel('구매 조건 확인')).not.toBeChecked();await page.getByLabel('구매 조건 확인').check();await page.getByRole('button',{name:'구매하기',exact:true}).click();}
for(const reason of ['cancel','fail'])test(`official FRAME ${reason} actual identical TYPE FAIL -> real owned stop -> original catalog -> distinct fresh purchase`,async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG runner');const {calls,state}=await fixture(page,context);await buy(page);await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();
 const forms=await page.evaluate(()=>window.__forms);expect(forms[0].CLOSEURL).toBe(forms[0].FAILURL);expect(forms[0].FAILURL).toContain('TYPE=FAIL');
 const frame=page.frames().find(f=>f.name()==='___kiwoompayIframe___');await frame.goto(forms[0][reason==='cancel'?'CLOSEURL':'FAILURL']).catch(e=>{if(!e.message.includes('detached'))throw e;});
 await expect(page.getByRole('heading',{name:'식권 구매',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();await expect(page.getByText('구매 진행이 종료됐어요',{exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'할인 선택'})).toHaveCount(0);
 const stop=calls.find(c=>c.path.endsWith('/abandon'));expect(stop.body).toMatchObject({checkout_return_ended:'sdk_frame_fail'});expect(stop.body.acknowledge_provider_uncertainty).toBeUndefined();expect(stop.json.data.local_abandonment.provider_finality).toBe('unknown');
 await buy(page);await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();const orders=calls.filter(c=>c.path==='/vouchers/purchase').map(c=>c.json.data.order_id);expect(new Set(orders).size).toBe(2);expect(calls.filter(c=>c.path==='/vouchers/quote')).toHaveLength(2);expect(state.errors).toEqual([]);
 if(receipts)writeFileSync(`${receipts}/resume-pc-${reason}-real-producer.json`,JSON.stringify({forms,calls,audit:producer('audit'),provider_transport:false},null,2));
});
for(const kind of ['cancel','fail'])test(`served openerless mobile ${kind} nonce bridge -> real local stop -> catalog`,async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG runner');await page.addInitScript(()=>Object.defineProperty(navigator,'userAgent',{value:'iPhone'}));const {calls,state}=await fixture(page,context);await buy(page);await expect.poll(()=>context.pages().length).toBe(2);const child=context.pages().find(p=>p!==page);await child.waitForURL('**/api-fixture/payments/checkout/**');await child.waitForLoadState();expect(await child.evaluate(()=>window.opener)).toBeNull();
 const u=new URL(child.url()),nonce=u.searchParams.get('return_nonce');expect(nonce).toMatch(/^[0-9a-f]{32}$/);const closed=child.waitForEvent('close');await expect.poll(()=>child.evaluate(()=>window.__forms.length)).toBe(1);const mobileFields=await child.evaluate(()=>window.__forms[0]);expect(mobileFields.CLOSEURL).toContain(`#cancel.${nonce}`);expect(mobileFields.FAILURL).toContain(`#fail.${nonce}`);await child.goto(mobileFields[kind==='cancel'?'CLOSEURL':'FAILURL']).catch(()=>{});await closed;
 if(receipts)writeFileSync(`${receipts}/resume-mobile-${kind}-debug.json`,JSON.stringify({calls,stored:await page.evaluate(()=>Object.entries(sessionStorage)),channel:await page.evaluate(()=>window.__channelEvents||[])},null,2));
 await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();await expect(page.getByText(kind==='cancel'?'구매 진행을 취소했어요':'구매 진행이 종료됐어요',{exact:true})).toBeVisible();const stop=calls.find(c=>c.path.endsWith('/abandon'));expect(stop.body).toMatchObject(kind==='cancel'?{explicit_checkout_cancel_intent:true}:{checkout_return_ended:'mobile_fail'});expect(state.errors).toEqual([]);
 if(receipts)writeFileSync(`${receipts}/resume-mobile-${kind}-real-producer.json`,JSON.stringify({calls,audit:producer('audit'),provider_transport:false},null,2));
});
async function frameMessage(page,data={TYPE:'FAIL'},extra={}){
 await page.evaluate(({data,extra})=>{const frame=document.querySelector('#___kiwoompayIframe___');window.dispatchEvent(new MessageEvent('message',{origin:extra.origin||'https://ssltest-v2.kiwoompay.co.kr',source:extra.foreign?window:frame.contentWindow,data}));},{data,extra});
}
async function readyFrame(page,context){const result=await fixture(page,context);await buy(page);await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();return result;}
for(const kind of ['origin','source','order','noevent','blur','forceclose'])test(`unsafe ${kind} never authorizes local stop`,async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG');const {calls}=await readyFrame(page,context);
 if(kind==='origin')await frameMessage(page,{TYPE:'FAIL'},{origin:'https://ssltest-v2.kiwoompay.co.kr.evil.invalid'});
 if(kind==='source')await frameMessage(page,{TYPE:'FAIL'},{foreign:true});
 if(kind==='order')await frameMessage(page,{TYPE:'FAIL',ORDERNO:'GE-other-order'});
 if(kind==='blur')await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
 if(kind==='forceclose')await page.keyboard.press('Escape');
 await page.waitForTimeout(450);expect(calls.filter(c=>c.path.endsWith('/abandon'))).toHaveLength(0);expect(producer('audit').local_receipts).toHaveLength(0);await expect(page.locator('.purchase-catalog .recovery-card')).toHaveCount(0);if(kind!=='forceclose'){await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();await page.keyboard.press('Escape');}await openRecovery(page);await expect(page.getByRole('heading',{name:/이전.*결과/})).toBeVisible();
});
for(const kind of ['success-ready','success-paid','fail-paid'])test(`${kind} uses server completion; no return hint financial authority`,async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG');const {calls}=await readyFrame(page,context);const order=calls.find(c=>c.path==='/vouchers/purchase').json.data.order_id;
 if(kind.endsWith('paid'))producer('approve',{order_id:order});await frameMessage(page,{TYPE:kind.startsWith('fail')?'FAIL':'SUCCESS'});
 await expect.poll(()=>calls.filter(c=>c.path.startsWith('/payments/recovery?')).length).toBe(1);expect(calls.filter(c=>c.path.endsWith('/abandon'))).toHaveLength(0);
 if(kind.endsWith('paid'))await expect(page.getByRole('heading',{name:'결제 완료',exact:true})).toBeVisible();else {await openRecovery(page);await expect(page.getByRole('heading',{name:/이전.*결과/})).toBeVisible();}
});
for(const failure of ['read','write-lost','write-refused','storage'])test(`normal ended ${failure} retains exact intent with actionable retry`,async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG');const {calls}=await readyFrame(page,context);let faults=0;
 if(failure==='read')await page.route('**/api-fixture/payments/recovery?**',r=>++faults===1?r.abort():r.fallback());
 if(failure.startsWith('write'))await page.route('**/api-fixture/payments/orders/*/abandon',r=>{if(++faults!==1)return r.fallback();if(failure==='write-lost'){const u=new URL(r.request().url());producer('request',{method:'POST',path:u.pathname.replace('/api-fixture',''),body:r.request().postDataJSON()});}return r.abort();});
 if(failure==='storage')await page.evaluate(()=>{const remove=Storage.prototype.removeItem;window.__restoreStorage=()=>Storage.prototype.removeItem=remove;Storage.prototype.removeItem=function(k){if(k.startsWith('greeneat-purchase-pending:'))throw Error('synthetic storage failure');return remove.call(this,k);};});
 await frameMessage(page);
 if(failure==='storage')await expect.poll(()=>producer('audit').local_receipts.length).toBe(1);else await expect.poll(()=>faults).toBe(1);
 expect(await page.evaluate(()=>Object.keys(sessionStorage).some(k=>k.startsWith('greeneat-purchase-pending:')))).toBe(true);
 await expect(page.locator('.purchase-catalog .recovery-card')).toHaveCount(0);
 // Entering history is an explicit authenticated read retry. Lost successful
 // writes may already be durable; never require a second stop in that case.
 await openRecovery(page);
 if(failure==='storage'){await expect(page.getByRole('heading',{name:/이전.*결과/})).toBeVisible();await page.evaluate(()=>window.__restoreStorage());await page.getByRole('button',{name:'다시 확인'}).click();}
 await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();expect(producer('audit').local_receipts).toHaveLength(1);expect(calls.filter(c=>c.path==='/vouchers/purchase')).toHaveLength(1);
});
test('ended survives reload after failed read, no second checkbox',async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG');await readyFrame(page,context);let first=true;await page.route('**/api-fixture/payments/recovery?**',r=>{if(first){first=false;return r.abort();}return r.fallback();});await frameMessage(page);await expect.poll(()=>first).toBe(false);await page.reload();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();expect(producer('audit').local_receipts).toHaveLength(1);
});
test('old frame generation and replay cannot stop the next fresh order',async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG');const {calls}=await readyFrame(page,context);await page.evaluate(()=>window.__oldFrame=document.querySelector('#___kiwoompayIframe___').contentWindow);await frameMessage(page);await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();await buy(page);await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();await page.evaluate(()=>window.dispatchEvent(new MessageEvent('message',{origin:'https://ssltest-v2.kiwoompay.co.kr',source:window.__oldFrame,data:{TYPE:'FAIL'}})));await page.waitForTimeout(300);expect(calls.filter(c=>c.path.endsWith('/abandon'))).toHaveLength(1);expect(producer('audit').local_receipts).toHaveLength(1);
});
for(const scenario of ['wrong-nonce','foreign-origin','success','forceclose','reload'])test(`mobile served bridge safety ${scenario}`,async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG');await page.addInitScript(()=>Object.defineProperty(navigator,'userAgent',{value:'iPhone'}));const {calls}=await fixture(page,context);await buy(page);await expect.poll(()=>context.pages().length).toBe(2);const child=context.pages().find(p=>p!==page);await child.waitForURL('**/api-fixture/payments/checkout/**');const nonce=new URL(child.url()).searchParams.get('return_nonce');await child.waitForLoadState();
 if(scenario==='reload'){await page.reload();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();}
 if(scenario==='forceclose')await child.close();
 else if(scenario==='foreign-origin'){
  await context.route('https://foreign.invalid/**',r=>r.fulfill({contentType:'text/html',body:`<script>new BroadcastChannel('greeneat-checkout-return:${nonce}').postMessage({type:'greeneat_checkout_return',kind:'cancel',nonce:'${nonce}'});</script>`}));await child.goto('https://foreign.invalid/return');
 }else await child.goto(`/payment-return#${scenario==='success'?'success':'cancel'}.${scenario==='wrong-nonce'?'0'.repeat(32):nonce}`).catch(()=>{});
 if(scenario==='reload'){await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();expect(producer('audit').local_receipts).toHaveLength(1);}
 else{await page.waitForTimeout(500);expect(calls.filter(c=>c.path.endsWith('/abandon'))).toHaveLength(0);expect(producer('audit').local_receipts).toHaveLength(0);await openRecovery(page);await expect(page.getByRole('heading',{name:['forceclose','success','wrong-nonce'].includes(scenario)?/이전.*결과/:'진행 중인 결제'})).toBeVisible();}
});
test('ended read timeout is bounded and retains actionable retry, no local write',async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG');const {calls}=await readyFrame(page,context);let release;const barrier=new Promise(r=>release=r);await page.route('**/api-fixture/payments/recovery?**',async r=>{await barrier;try{await r.abort();}catch{}});await frameMessage(page);await openRecovery(page);
 try{await expect(page.getByRole('alert')).toContainText('주문 상태 확인 오류',{timeout:12000});await expect(page.getByRole('button',{name:'다시 확인'})).toBeEnabled();expect(calls.filter(c=>c.path.endsWith('/abandon'))).toHaveLength(0);}finally{release();}
});
test('real stopped order late approval is quarantined exactly once after catalog reset',async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG');const {calls}=await readyFrame(page,context);const order=calls.find(c=>c.path==='/vouchers/purchase').json.data.order_id;await frameMessage(page);await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();for(let i=0;i<2;i++)expect(producer('approve',{order_id:order}).reconciliation_required).toBe(true);const audit=producer('audit');expect(audit.voucher_count.count).toBe(0);expect(audit.refund_count.count).toBe(0);expect(audit.discrepancies).toHaveLength(1);expect(audit.local_receipts).toHaveLength(1);if(receipts)writeFileSync(`${receipts}/resume-ui-late-approval.json`,JSON.stringify(audit,null,2));
});
test('desktop BANK-only exception retains native popup method and served cancel bridge',async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG');await fixture(page,context,{bank:true});await buy(page);await expect.poll(()=>context.pages().length).toBe(2);expect(await page.locator('#___kiwoompayIframe___').count()).toBe(0);const child=context.pages().find(p=>p!==page);await child.waitForURL('**/api-fixture/payments/checkout/**');await expect.poll(()=>child.evaluate(()=>window.__forms.length)).toBe(1);const fields=await child.evaluate(()=>window.__forms[0]);expect(fields.PAYMETHOD).toBe('BANK');expect(await child.evaluate(()=>window.opener)).toBeNull();await child.goto(fields.CLOSEURL).catch(()=>{});await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();expect(producer('audit').local_receipts).toHaveLength(1);
});
test('old mobile nonce replay after fresh purchase cannot end the new generation',async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG');await page.addInitScript(()=>Object.defineProperty(navigator,'userAgent',{value:'iPhone'}));await fixture(page,context);await buy(page);let child=context.pages().find(p=>p!==page);await child.waitForURL('**/api-fixture/payments/checkout/**');const old=new URL(child.url()).searchParams.get('return_nonce');await child.goto(`/payment-return#cancel.${old}`).catch(()=>{});await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();await buy(page);child=context.pages().find(p=>p!==page);await child.waitForURL('**/api-fixture/payments/checkout/**');expect(new URL(child.url()).searchParams.get('return_nonce')).not.toBe(old);const replay=await context.newPage();await replay.goto(`/payment-return#cancel.${old}`).catch(()=>{});await page.waitForTimeout(300);expect(producer('audit').local_receipts).toHaveLength(1);await openRecovery(page);await expect(page.getByRole('heading',{name:'진행 중인 결제'})).toBeVisible();
});
for(const width of [360,390,1440])test(`original catalog restored screenshot ${width}`,async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON,'requires disposable PG');await page.setViewportSize({width,height:850});await readyFrame(page,context);await frameMessage(page);await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();await page.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}'});if(receipts)await page.screenshot({path:`${receipts}/resume-original-catalog-${width}.png`,animations:'disabled'});
});
