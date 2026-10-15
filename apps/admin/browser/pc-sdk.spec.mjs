import { test, expect } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { setup, submit, purchaseResponse } from './final-L1-fixture.mjs';
const SDK_URL='https://ssl-v2.kiwoompay.co.kr/sdk/v1/latest/kiwoompayEnc.js';
const source=readFileSync(process.env.KIWOOM_SDK_FIXTURE_SOURCE || '/home/lovelyuk/.hermes/profiles/aebong/cache/long-tasks/greeneat-pg-reconciliation-receipts/deeper-sdk-script.txt','utf8');
const sourceSha256 = '2e104d2178f8e447164e57f0a72e0b10c2b803a4597bb1f6c6d964fa7cf18e20';
expect(createHash('sha256').update(source).digest('hex')).toBe(sourceSha256);
const states = new WeakMap();
test.afterEach(async ({page}) => { expect(states.get(page)?.errors || []).toEqual([]); });
const receipts=process.env.PURCHASE_RECEIPTS;
const pendingKey='greeneat-purchase-pending:11111111-1111-4111-8111-111111111111';
const fields={TYPE:'P',PAYMETHOD:'TOTAL',CPID:'TEST0001',ORDERNO:'GE-S-final-L1',AMOUNT:'41000',KIWOOM_ENC:'synthetic-hash',PRODUCTNAME:'fixture ticket',USERID:'fixture-user'};
async function sdkFixture(page,context,{failScript=false,mode='DEV',badFields={},delay=0,priceMismatch=false,hashFailure=false}={}){
 const state=await setup(page,context,{gross:42000,points:1000});
 states.set(page,state);
 Object.assign(state,{scripts:0,purchases:0,hashes:0,recoveries:0,forms:[]});
 await context.route(SDK_URL,async route=>{state.scripts++; if(failScript)return route.abort(); return route.fulfill({contentType:'application/javascript',body:source});});
 // Actual SDK form.submit is intercepted before ANY provider transport. DOM/form/frame construction remains official code.
 await page.addInitScript(()=>{window.__forms=[]; HTMLFormElement.prototype.submit=function(){window.__forms.push({action:this.action,target:this.target,fields:Object.fromEntries([...this.elements].map(e=>[e.name,e.value]))});};});
 await page.route('**/api-fixture/vouchers/purchase-subsidized',async route=>{
  state.purchases++;
  if(state.scripts===0) { expect(context.pages()).toHaveLength(2); expect(context.pages()[1].url()).toBe('about:blank'); }
  if(delay)await new Promise(r=>setTimeout(r,delay));return route.fulfill({json:{ok:true,data:purchaseResponse(42000,priceMismatch?999:1000)}});
 });
 await page.route('**/api-fixture/payments/checkout/*/sdk',async route=>{
  state.hashes++; expect(route.request().method()).toBe('POST'); expect(route.request().headers().authorization).toBe('Bearer fixture-access');
  expect(await page.evaluate(key=>JSON.parse(sessionStorage.getItem(key)),pendingKey)).toMatchObject({order_id:fields.ORDERNO,amount:41000,checkout_started:true});
  return route.fulfill(hashFailure?{status:502,json:{detail:{message:'synthetic hash failure'}}}:{json:{ok:true,data:{sdk_mode:mode,fields:{...fields,...badFields}}}});
 });
 await page.route('**/api-fixture/payments/recovery?**',route=>{state.recoveries++;expect(route.request().method()).toBe('GET');expect(route.request().headers().authorization).toBe('Bearer fixture-access');return route.fulfill({json:{ok:true,data:{order_id:fields.ORDERNO,amount:41000,status:'ready',recovery_action:'reconcile',checkout_url:null,completion:null,resumable:false}}});});
 return state;
}
for (const mode of ['DEV', 'REAL']) test(`real router exported contract executes official SDK ${mode}`, async ({ page, context }) => {
 test.skip(!process.env.PC_SDK_ROUTER_RECEIPTS, 'requires synthetic real-router contract export');
 const contract = JSON.parse(readFileSync(`${process.env.PC_SDK_ROUTER_RECEIPTS}/router-sdk-contract-${mode}.json`, 'utf8'));
 const state = await sdkFixture(page, context, { mode });
 await page.route('**/api-fixture/payments/checkout/*/sdk', async route => {
  state.hashes++;
  expect(route.request().headers().authorization).toBe('Bearer fixture-access');
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)), pendingKey)).toMatchObject({ order_id: contract.fields.ORDERNO, amount: Number(contract.fields.AMOUNT), checkout_started: true });
  return route.fulfill({ json: { ok: true, data: contract } });
 });
 await submit(page, 1000);
 await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();
 const forms = await page.evaluate(() => window.__forms);
 expect(forms).toHaveLength(1);
 for (const key of ['TYPE','PAYMETHOD','CPID','ORDERNO','AMOUNT','KIWOOM_ENC','PRODUCTNAME','USERID']) expect(forms[0].fields[key]).toBe(contract.fields[key]);
 expect(forms[0].action).toBe(`https://${mode === 'REAL' ? 'api' : 'apitest'}.kiwoompay.co.kr/pay/linkEnc`);
 expect(forms[0].target).toBe('___kiwoompayIframe___');
 expect(context.pages()).toHaveLength(1);
 if (receipts) writeFileSync(`${receipts}/router-official-sdk-trace-${mode}.json`, JSON.stringify({ contract, forms, sdk_source_sha256: sourceSha256, provider_transport: false }, null, 2));
});

test('desktop actual official SDK FRAME, no popup, single hash, persistence and close/reload',async({page,context})=>{
 const state=await sdkFixture(page,context); await submit(page,1000);
 await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();
 expect(context.pages()).toHaveLength(1); expect(state.hashes).toBe(1);expect(state.scripts).toBe(1);
 const forms=await page.evaluate(()=>window.__forms);expect(forms).toHaveLength(1);expect(forms[0].target).toBe('___kiwoompayIframe___');expect(forms[0].action).toBe('https://apitest.kiwoompay.co.kr/pay/linkEnc');expect(forms[0].fields.TYPE).toBe('P');expect(forms[0].fields.PAYMETHOD).toBe('TOTAL');
 expect(await page.evaluate(key=>JSON.parse(sessionStorage.getItem(key)).checkout_started,pendingKey)).toBe(true);
 await page.keyboard.press('Escape');await expect(page.locator('#___kiwoompayIframe___')).toHaveCount(0);
 await expect(page.getByRole('heading',{name:'진행 중인 결제'})).toBeVisible();await page.reload();
 await expect(page.getByRole('heading',{name:'진행 중인 결제'})).toBeVisible();expect(state.hashes).toBe(1);expect(state.purchases).toBe(1);expect(state.scripts).toBe(1);
 if(receipts)writeFileSync(`${receipts}/official-sdk-browser-trace.json`,JSON.stringify({source_sha256:createHash('sha256').update(source).digest('hex'),forms,provider_transport:false,hashes:state.hashes,purchases:state.purchases},null,2));
});
for (const options of [{hashFailure:true},{badFields:{TYPE:'W'}},{badFields:{PAYMETHOD:'BANK'}},{badFields:{AMOUNT:'1'}},{mode:'OTHER'}]) {
 test(`admitted SDK failure retains pending no retry/fallback ${JSON.stringify(options)}`,async({page,context})=>{
  const state=await sdkFixture(page,context,options);await submit(page,1000);
  await expect(page.getByRole('alert')).toContainText('같은 주문의 상태');
  await expect(page.locator('#___kiwoompayIframe___')).toHaveCount(0);expect(context.pages()).toHaveLength(1);
  await page.getByRole('button',{name:'저장된 주문 상태 확인'}).click();expect(state.hashes).toBe(1);expect(state.purchases).toBe(1);
  expect(await page.evaluate(key=>JSON.parse(sessionStorage.getItem(key)).checkout_started,pendingKey)).toBe(true);expect(state.errors).toEqual([]);
 });
}
test('consent withdrawn during delayed SDK preload prevents order and hash creation', async ({page,context}) => {
 const state=await sdkFixture(page,context);
 let release, started;
 const barrier=new Promise(resolve=>release=resolve), requested=new Promise(resolve=>started=resolve);
 await context.route(SDK_URL,async route=>{state.scripts++;started();await barrier;await route.fulfill({contentType:'application/javascript',body:source});});
 await submit(page,1000);
 await requested;
 await page.getByLabel('구매 조건 확인').uncheck();
 release();
 await expect(page.getByRole('alert')).toContainText('변경');
 await expect(page.getByRole('button',{name:'구매하기',exact:true})).toBeDisabled();
 expect(state.purchases).toBe(0);expect(state.hashes).toBe(0);
 expect(await page.evaluate(key=>sessionStorage.getItem(key),pendingKey)).toBeNull();
 expect(context.pages()).toHaveLength(1);
});
test('desktop pricing mismatch never admits SDK; pending retained',async({page,context})=>{
 const state=await sdkFixture(page,context,{priceMismatch:true});await submit(page,1000);
 await expect(page.getByRole('alert')).toContainText('최종 주문 금액');expect(state.hashes).toBe(0);expect(context.pages()).toHaveLength(1);
});
async function message(page,{origin='https://ssltest-v2.kiwoompay.co.kr',data={TYPE:'SUCCESS',RESULTCODE:'0000'},source='frame'}={}){
 await page.evaluate(({origin,data,source})=>window.dispatchEvent(new MessageEvent('message',{origin,data,source:source==='frame'?document.querySelector('#___kiwoompayIframe___').contentWindow:window})),{origin,data,source});
}
for(const mode of ['DEV','REAL']) test(`exact ${mode} origin/source/type guard; callback only authenticated recovery`,async({page,context})=>{
 const state=await sdkFixture(page,context,{mode});await submit(page,1000);await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();
 const origin=mode==='DEV'?'https://ssltest-v2.kiwoompay.co.kr':'https://ssl-v2.kiwoompay.co.kr';
 for(const attack of [{origin:origin+'.evil.invalid'}, {origin:'https://attacker.kiwoompay.co.kr'}, {origin:mode==='DEV'?'https://ssl-v2.kiwoompay.co.kr':'https://ssltest-v2.kiwoompay.co.kr'}, {origin,source:'window'}, {origin,data:null}, {origin,data:{RESULTCODE:'0000'}}, {origin,data:{TYPE:'BOGUS',RESULTCODE:'0000'}}, {origin,data:{TYPE:'FAIL',RESULTCODE:'0000'}}]) {
  await message(page,attack);await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();
 }
 expect(state.recoveries).toBe(0);await message(page,{origin});await expect.poll(()=>state.recoveries).toBe(1);
 await expect(page.getByRole('heading',{name:'진행 중인 결제'})).toBeVisible();expect(state.confirm).toBe(0);expect(state.purchases).toBe(1);expect(state.hashes).toBe(1);expect(state.errors).toEqual([]);
});
test('valid FAIL cannot cancel or clear pending, only server read',async({page,context})=>{
 const state=await sdkFixture(page,context);await submit(page,1000);await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();
 await message(page,{data:{TYPE:'FAIL',RESULTCODE:'9999'}});await expect.poll(()=>state.recoveries).toBe(1);
 await expect(page.getByRole('heading',{name:'진행 중인 결제'})).toBeVisible();expect(await page.evaluate(key=>!!sessionStorage.getItem(key),pendingKey)).toBe(true);
});
test('close control and focus cycle use official close, retain pending without cancellation',async({page,context})=>{
 const state=await sdkFixture(page,context);await submit(page,1000);
 const close=page.getByRole('button',{name:'결제창 닫기'});await expect(close).toBeFocused();
 await page.keyboard.press('Tab');await expect(page.locator('#___kiwoompayIframe___')).toBeFocused();
 await page.keyboard.press('Shift+Tab');await expect(close).toBeFocused();await close.click();
 await expect(page.getByRole('dialog')).toHaveCount(0);expect(state.hashes).toBe(1);await expect.poll(()=>state.recoveries).toBe(1);
 expect(await page.evaluate(key=>!!sessionStorage.getItem(key),pendingKey)).toBe(true);
});
for(const phase of ['script','hash','frame','callback']) test(`logout fences late ${phase} and cleans frame`,async({page,context})=>{
 const state=await sdkFixture(page,context);let release,started;
 const barrier=new Promise(r=>release=r), request=new Promise(r=>started=r);
 if(phase==='script')await context.route(SDK_URL,async route=>{started();await barrier;await route.fulfill({contentType:'application/javascript',body:source});});
 if(phase==='hash')await page.route('**/api-fixture/payments/checkout/*/sdk',async route=>{state.hashes++;started();await barrier;await route.fulfill({json:{ok:true,data:{sdk_mode:'DEV',fields}}});});
 await submit(page,1000);
 if(['script','hash'].includes(phase))await request;else await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();
 await page.evaluate(phase=>{
 if(phase==='callback')window.dispatchEvent(new MessageEvent('message',{origin:'https://ssltest-v2.kiwoompay.co.kr',source:document.querySelector('#___kiwoompayIframe___').contentWindow,data:{TYPE:'SUCCESS',RESULTCODE:'0000'}}));
 [...document.querySelectorAll('nav button')].find(b=>b.textContent==='내정보').click();
 },phase);
 await page.locator('button').filter({hasText:'로그아웃'}).evaluate(b=>b.click());release();
 await expect(page.getByRole('button',{name:'로그인',exact:true})).toBeVisible();await expect(page.locator('#___kiwoompayIframe___')).toHaveCount(0);
 await page.waitForTimeout(200);expect(state.recoveries).toBe(phase==='callback'?1:0);if(phase==='script')expect(state.purchases).toBe(0);
});
test('slow purchase locks double-click; resize never converts active desktop',async({page,context})=>{
 const state=await sdkFixture(page,context,{delay:250});await submit(page,1000);
 await page.getByRole('button',{name:'구매하기',exact:true}).evaluate(b=>{b.click();b.click();});
 await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();await page.setViewportSize({width:360,height:780});
 await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();expect(state.purchases).toBe(1);expect(state.hashes).toBe(1);expect(context.pages()).toHaveLength(1);
});
test('zero point-only desktop performs no script/popup/frame/hash',async({page,context})=>{
 const state=await sdkFixture(page,context);
 await page.route('**/api-fixture/vouchers/quote',route=>route.fulfill({json:{ok:true,data:{merchant_id:'merchant-fixture',purchase_mode:'subsidized',merchant_name:'fixture',product_id:'package-fixture',gross_amount:42000,coupon_discount_amount:0,point_amount:42000,payment_amount:0}}}));
 await page.route('**/api-fixture/vouchers/purchase-subsidized',route=>route.fulfill({json:{ok:true,data:purchaseResponse(42000,42000)}}));
 await submit(page,42000);await expect(page.getByRole('heading',{name:'결제 완료'})).toBeVisible();expect(state.scripts).toBe(0);expect(state.hashes).toBe(0);expect(context.pages()).toHaveLength(1);
});
test('desktop BANK explicit old popup no SDK method broadening',async({page,context})=>{
 const state=await sdkFixture(page,context);
 await page.route('**/api-fixture/vouchers/products',route=>route.fulfill({json:{ok:true,data:{purchase_mode:'subsidized',items:[{id:'package-fixture',name:'테스트 식권',voucher_count:10,bonus_count:1,unit_price:8000,sale_price:72000,employee_pay_amount:42000,kiwoom_pay_method:'BANK'}]}}}));
 await submit(page,1000);await expect(page.getByRole('heading',{name:'진행 중인 결제'})).toBeVisible();
 await expect.poll(()=>state.checkout).toBe(1);expect(context.pages()).toHaveLength(2);expect(state.scripts).toBe(0);expect(state.hashes).toBe(0);
});
for(const device of [{name:'desktop-narrow',width:360,ua:null},{name:'desktop-1024',width:1024,ua:null},{name:'desktop-1440',width:1440,ua:null},{name:'mobile-360',width:360,ua:'iPhone'},{name:'mobile-390',width:390,ua:'iPhone'},{name:'mobile-wide',width:1440,ua:'Android'},{name:'ipad-desktop-touch',width:1024,ua:'Macintosh',touch:true}]){
 test(`snapshot device not viewport and screenshot ${device.name}`,async({browser})=>{
  const context=await browser.newContext({viewport:{width:device.width,height:850},...(device.ua?{userAgent:device.ua}:{}),hasTouch:!!device.touch});const page=await context.newPage();
  if(device.touch)await page.addInitScript(()=>Object.defineProperty(navigator,'maxTouchPoints',{value:5}));
  try{
   const state=await sdkFixture(page,context);await submit(page,1000);
   if(device.ua){await expect.poll(()=>state.checkout).toBe(1);expect(state.scripts).toBe(0);expect(state.hashes).toBe(0);expect(context.pages()).toHaveLength(2);}
   else {await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();expect(context.pages()).toHaveLength(1);expect(state.hashes).toBe(1);}
   await page.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important;scroll-behavior:auto!important}'});
   if(receipts)await page.screenshot({path:`${receipts}/pc-sdk-${device.name}.png`,animations:'disabled',fullPage:false});
   expect(state.errors).toEqual([]);
  }finally{await context.close();}
 });
}

test('quote change during slow preload invalidates purchase before order creation',async({page,context})=>{
 const state=await sdkFixture(page,context);let release,started;const barrier=new Promise(r=>release=r),request=new Promise(r=>started=r);
 await context.route(SDK_URL,async route=>{state.scripts++;started();await barrier;return route.fulfill({contentType:'application/javascript',body:source});});
 await submit(page,1000);await request;await page.getByRole('button',{name:'상품 다시 선택'}).click();release();
 await page.waitForTimeout(250);expect(state.purchases).toBe(0);expect(state.hashes).toBe(0);
});
test('actual SDK creation throw after hash retains pending, no popup or retry',async({page,context})=>{
 const state=await sdkFixture(page,context);
 await page.addInitScript(()=>{HTMLFormElement.prototype.submit=function(){throw new Error('synthetic provider transport disabled');};});
 await submit(page,1000);await expect(page.getByRole('alert')).toContainText('같은 주문의 상태');
 await expect(page.getByRole('heading',{name:'진행 중인 결제'})).toBeVisible();await expect(page.locator('#___kiwoompayIframe___')).toHaveCount(0);
 await page.getByRole('button',{name:'저장된 주문 상태 확인'}).click();expect(state.hashes).toBe(1);expect(state.purchases).toBe(1);expect(context.pages()).toHaveLength(1);
});
test('desktop lost purchase response preserves unknown on reload, no hash or retry',async({page,context})=>{
 const state=await sdkFixture(page,context);await page.route('**/api-fixture/vouchers/purchase-subsidized',route=>{state.purchases++;return route.abort();});
 await submit(page,1000);await expect(page.getByRole('heading',{name:'주문 상태 확인 필요'})).toBeVisible();
 await page.reload();await expect(page.getByRole('heading',{name:'주문 상태 확인 필요'})).toBeVisible();expect(state.hashes).toBe(0);expect(state.purchases).toBe(1);expect(context.pages()).toHaveLength(1);
});
test('desktop pending write failure stops before authenticated SDK POST',async({page,context})=>{
 const state=await sdkFixture(page,context);
 await page.addInitScript(()=>{const original=Storage.prototype.setItem;let writes=0;Storage.prototype.setItem=function(key,value){if(key.startsWith('greeneat-purchase-pending:')&&++writes===2)throw new Error('synthetic pending write failure');return original.call(this,key,value);};});
 await submit(page,1000);await expect(page.getByRole('heading',{name:'진행 중인 결제'})).toBeVisible();await expect(page.getByRole('alert')).toContainText('저장 또는 결제창 진입');expect(state.hashes).toBe(0);expect(state.purchases).toBe(1);
});
test('malformed loaded SDK blocks before purchase',async({page,context})=>{
 const state=await sdkFixture(page,context);await context.route(SDK_URL,route=>{state.scripts++;return route.fulfill({contentType:'application/javascript',body:'// deliberately missing SDK object'});});
 await submit(page,1000);await expect(page.getByRole('alert')).toContainText('SDK');expect(state.purchases).toBe(0);expect(state.hashes).toBe(0);
});
test('script failure before purchase creates no order or hash and never retries',async({page,context})=>{
 const state=await sdkFixture(page,context,{failScript:true});await submit(page,1000);await expect(page.getByRole('alert')).toContainText('SDK');
 await page.getByRole('button',{name:'구매하기',exact:true}).click();expect(state.scripts).toBe(1);expect(state.purchases).toBe(0);expect(state.hashes).toBe(0);
});
