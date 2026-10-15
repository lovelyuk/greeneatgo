import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {setup,submit,purchaseResponse} from './final-L1-fixture.mjs';
const SDK='https://ssl-v2.kiwoompay.co.kr/sdk/v1/latest/kiwoompayEnc.js';
const source=readFileSync('/home/lovelyuk/.hermes/profiles/aebong/cache/long-tasks/greeneat-pg-reconciliation-receipts/deeper-sdk-script.txt','utf8');
const owner='11111111-1111-4111-8111-111111111111', key=`greeneat-purchase-pending:${owner}`;
const old='GE-S-final-L1';
const receipt=()=>({order_id:old,user_id:owner,amount:41000,status:'canceled',recovery_action:'locally_abandoned',resumable:false,checkout_url:null,completion:null,local_abandonment:{id:'22222222-2222-4222-8222-222222222222',source:'owner_request',scope:'local_order',outcome:'abandoned',requested_by:owner,requested_at:'2026-10-15T01:02:03+09:00',provider_finality:'unknown',residual_late_approval_possible:true}});
async function expectRecoveryError(page, diagnostic) {
 await expect(page.getByRole('alert')).toContainText(/주문 상태 확인 오류|구매 중단 결과를 확인하지 못했어요/);
 const details=page.locator('details');
 await expect(details).toHaveCount(1);
 await expect(details).not.toHaveAttribute('open','');
 await details.locator('summary').click();
 await expect(details).toContainText(diagnostic);
 await details.locator('summary').click();
}
async function fixture(page,context,{response,postError}={}){
 const s=await setup(page,context,{gross:42000,points:1000});Object.assign(s,{purchases:0,hashes:0,reads:0,stops:0,local:null});
 s.response = response; s.postError = postError;
 const ready = {order_id:old,amount:41000,status:'ready',recovery_action:'reconcile',resumable:false,checkout_url:null};
 await context.route(SDK,r=>r.fulfill({contentType:'application/javascript',body:source}));
 await page.addInitScript(()=>{HTMLFormElement.prototype.submit=function(){};});
 await page.route('**/api-fixture/vouchers/purchase-subsidized',r=>{s.purchases++;return r.fulfill({json:{ok:true,data:{...purchaseResponse(42000,1000),order_id:s.purchases===1?old:'GE-S-fresh-local'}}});});
 await page.route('**/api-fixture/payments/checkout/*/sdk?**',r=>{s.hashes++;return r.fulfill({json:{ok:true,data:{sdk_mode:'DEV',fields:{TYPE:'P',PAYMETHOD:'TOTAL',CPID:'TEST0001',ORDERNO:s.purchases===1?old:'GE-S-fresh-local',AMOUNT:'41000',KIWOOM_ENC:'synthetic-hash',PRODUCTNAME:'fixture',USERID:'fixture'}}}});});
 await page.route('**/api-fixture/payments/recovery?**',r=>{s.reads++;expect(r.request().method()).toBe('GET');return r.fulfill({json:{ok:true,data:s.local||s.response||ready}});});
 await page.route('**/api-fixture/payments/orders/*/abandon',async r=>{s.stops++;expect(r.request().headers().authorization).toBe('Bearer fixture-access');expect(r.request().postDataJSON()).toEqual({amount:41000,acknowledge_provider_uncertainty:true});expect(r.request().url()).toContain(`/orders/${old}/abandon`);if(s.postError)return r.fulfill({status:503,json:{detail:{message:'synthetic unavailable'}}});s.local=s.stopResponse||receipt();return r.fulfill({json:{ok:true,data:s.local}});});
 await page.route('**/api-fixture/payments/local-abandonments?**',r=>r.fulfill({json:{ok:true,data:{orders:s.local?[s.local]:[]}}}));
 s.close = async () => { await page.getByRole('button',{name:'결제창 닫기'}).click(); await expect.poll(()=>s.reads).toBeGreaterThan(0); await expect(page.getByRole('button',{name:'구매 진행 중단',exact:true})).toBeVisible(); };
 s.stop = async () => { await page.getByRole('button',{name:'구매 진행 중단',exact:true}).click();await page.getByLabel('PG 취소·환불 확정이 아님을 이해했습니다').check();await page.getByRole('button',{name:'확인하고 구매 진행 중단'}).click(); };
 return s;
}
test('PC close performs one read; explicit owner stop retires only this intent; reload/history/fresh consent distinct order',async({page,context})=>{
 const s=await fixture(page,context);await submit(page,1000);await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();
 await page.getByRole('button',{name:'결제창 닫기'}).click();await expect.poll(()=>s.reads).toBe(1);
 await expect(page.getByRole('heading',{name:'결제 결과 확인 중'})).toHaveCount(0);expect(s.stops).toBe(0);
 await page.getByRole('button',{name:'구매 진행 중단',exact:true}).click();await expect(page.getByRole('button',{name:'확인하고 구매 진행 중단'})).toBeDisabled();
 await page.getByLabel('PG 취소·환불 확정이 아님을 이해했습니다').check();await page.getByRole('button',{name:'확인하고 구매 진행 중단'}).click();
 await expect(page.getByRole('button',{name:'테스트 식권 선택'})).toBeVisible();expect(s.purchases).toBe(1);expect(s.hashes).toBe(1);expect(s.confirm).toBe(0);expect(s.stops).toBe(1);expect(await page.evaluate(k=>sessionStorage.getItem(k),key)).toBeNull();await expect(page.getByRole('status')).toContainText(/중단/);
 await page.reload();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();await expect(page.getByRole('button',{name:'테스트 식권 선택'})).toBeVisible();expect(s.purchases).toBe(1);
 await expect(page.getByRole('button',{name:'새 견적으로 구매 준비'})).toHaveCount(0);await page.getByRole('button',{name:'테스트 식권 선택'}).click();await page.getByLabel('사용 포인트').fill('1000');await expect(page.locator('.purchase-quote')).toBeVisible();await expect(page.getByLabel('구매 조건 확인')).not.toBeChecked();await page.getByLabel('구매 조건 확인').check();await page.getByRole('button',{name:'구매하기',exact:true}).click();await expect(page.locator('#___kiwoompayIframe___')).toBeVisible();
 expect(s.purchases).toBe(2);expect(s.hashes).toBe(2);expect(await page.evaluate(k=>JSON.parse(sessionStorage.getItem(k)).order_id,key)).toBe('GE-S-fresh-local');
 await page.getByRole('button',{name:'결제창 닫기'}).click();await page.getByRole('navigation').getByRole('button',{name:'내역',exact:true}).click();await expect(page.getByRole('heading',{name:'중단한 구매 주문',exact:true})).toBeVisible();await expect(page.getByText(old,{exact:false}).last()).toBeVisible();
 expect(s.errors).toEqual([]);
});

for(const mutate of [r=>({...r,user_id:'foreign'}),r=>({...r,order_id:'GE-foreign'}),r=>({...r,amount:41001}),r=>({...r,local_abandonment:{...r.local_abandonment,source:'trusted_provider'}}),r=>({...r,local_abandonment:{...r.local_abandonment,provider_finality:'verified'}}),r=>({...r,resumable:true}),r=>({...r,recovery_action:'reconcile'})])test(`malformed or contradictory stop receipt ${mutate.toString()}`,async({page,context})=>{
 const s=await fixture(page,context);s.stopResponse=mutate(receipt());await submit(page,1000);await s.close();await s.stop();
 await expectRecoveryError(page,'구매 중단 결과 확인 필요');await expect(page.getByRole('heading',{name:/이전.*결과/})).toBeVisible();
 expect(await page.evaluate(k=>JSON.parse(sessionStorage.getItem(k)).order_id,key)).toBe(old);expect(s.stops).toBe(1);expect(s.purchases).toBe(1);expect(s.hashes).toBe(1);
});
test('uncertain HTTP503 stop preserves intent; only a subsequent read recovers durable success',async({page,context})=>{
 const s=await fixture(page,context,{postError:true});await submit(page,1000);await s.close();await s.stop();await expectRecoveryError(page,'구매 중단 결과 확인 필요');expect(s.stops).toBe(1);
 s.local=receipt();await page.getByRole('button',{name:'다시 확인'}).click();await expect(page.getByRole('button',{name:'테스트 식권 선택'})).toBeVisible();expect(s.stops).toBe(1);
});
test('storage tombstone write failure retains pending before any retirement',async({page,context})=>{
 const s=await fixture(page,context);await submit(page,1000);await s.close();await page.evaluate(()=>{const original=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(v.includes('local_abandonment_receipt'))throw Error('synthetic write denied');return original.call(this,k,v);};});await s.stop();
 await expectRecoveryError(page,'구매 중단 결과 확인 필요');expect(await page.evaluate(k=>JSON.parse(sessionStorage.getItem(k)).order_id,key)).toBe(old);expect(s.stops).toBe(1);
 await page.reload();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();await expect(page.getByRole('status')).toContainText(/중단/);expect(await page.evaluate(k=>sessionStorage.getItem(k),key)).toBeNull();expect(s.stops).toBe(1);
});
test('storage removal failure fails closed then exact recovery can retry persistence',async({page,context})=>{
 const s=await fixture(page,context);await submit(page,1000);await s.close();await page.evaluate(()=>{const original=Storage.prototype.removeItem;Storage.prototype.removeItem=function(k){if(k.startsWith('greeneat-purchase-pending:'))throw Error('synthetic removal denied');return original.call(this,k);};});await s.stop();
 await expectRecoveryError(page,'구매 중단 결과 확인 필요');expect(await page.evaluate(k=>JSON.parse(sessionStorage.getItem(k)).pending.order_id,key)).toBe(old);
 await page.reload();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();await expect(page.getByRole('button',{name:'테스트 식권 선택'})).toBeVisible();expect(s.stops).toBe(1);
});
for(const status of ['done','failed'])test(`close resolves known ${status} without forcing local stop warning`,async({page,context})=>{
 const completion={order_id:old,amount:41000,status:'done',issued_count:11};
 const response=status==='done'?{order_id:old,amount:41000,status:'done',recovery_action:'complete',checkout_url:null,resumable:false,completion}:{order_id:old,user_id:owner,amount:41000,status:'failed',recovery_action:'closed',checkout_url:null,resumable:false,completion:null,closure:{scope:'order',finality:'verified',outcome:'failed',id:'22222222-2222-4222-8222-222222222222',evidence_sha256:'a'.repeat(64),closed_at:'2026-10-15T01:02:03+09:00'}};
 const s=await fixture(page,context,{response});await submit(page,1000);await page.getByRole('button',{name:'결제창 닫기'}).click();if(status==='done')await expect(page.getByRole('heading',{name:'결제 완료'})).toBeVisible();else {await expect(page.getByRole('button',{name:'테스트 식권 선택'})).toBeVisible();await expect(page.getByRole('status')).toContainText(/종료|취소/);}expect(s.stops).toBe(0);expect(s.confirm).toBe(0);await expect(page.getByLabel('PG 취소·환불 확정이 아님을 이해했습니다')).toHaveCount(0);
});
test('close read network503 is bounded, ends loading, and enables only read retry',async({page,context})=>{
 const s=await fixture(page,context);await page.route('**/api-fixture/payments/recovery?**',r=>{s.reads++;return r.fulfill({status:503,json:{detail:{message:'synthetic unavailable'}}});});await submit(page,1000);await page.getByRole('button',{name:'결제창 닫기'}).click();await expect(page.getByRole('alert')).toContainText('주문 상태 확인 오류');
 await page.waitForTimeout(1000);expect(s.reads).toBe(1);await expect(page.getByRole('button',{name:'구매 진행 중단',exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'다시 확인'})).toBeEnabled();await expect(page.getByRole('heading',{name:'결제 결과 확인 중'})).toHaveCount(0);expect(s.stops).toBe(0);expect(s.confirm).toBe(0);
});
test('late approval becomes visible reconciliation in history after reload, never fake no-charge',async({page,context})=>{
 const s=await fixture(page,context);await submit(page,1000);await s.close();await s.stop();await expect(page.getByRole('button',{name:'테스트 식권 선택'})).toBeVisible();s.local={...receipt(),recovery_action:'reconcile'};
 await page.reload();await page.getByRole('navigation').getByRole('button',{name:'내역',exact:true}).click();await expect(page.getByRole('alert')).toContainText('실제 청구 재확인');await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();await expect(page.getByRole('button',{name:'테스트 식권 선택'})).toBeVisible();expect(await page.evaluate(k=>sessionStorage.getItem(k),key)).toBeNull();expect(s.stops).toBe(1);expect(s.purchases).toBe(1);
});
test('late authenticated stop result after logout cannot retire or expose account state',async({page,context})=>{
 const s=await fixture(page,context);let release,started;const barrier=new Promise(r=>release=r),request=new Promise(r=>started=r);
 await page.route('**/api-fixture/payments/orders/*/abandon',async r=>{s.stops++;started();await barrier;try{await r.fulfill({json:{ok:true,data:receipt()}});}catch{}});
 await submit(page,1000);await s.close();await s.stop();await request;
 await page.getByRole('navigation').getByRole('button',{name:'내정보',exact:true}).click();await page.getByRole('button',{name:'로그아웃',exact:true}).click();release();
 await expect(page.getByRole('button',{name:'로그인',exact:true})).toBeVisible();await page.waitForTimeout(100);expect(await page.evaluate(k=>JSON.parse(sessionStorage.getItem(k)).order_id,key)).toBe(old);await expect(page.getByRole('status').filter({hasText:/구매 진행.*중단/})).toHaveCount(0);expect(s.stops).toBe(1);
});
test('a newer stored intent prevents retiring it with an old valid stop receipt',async({page,context})=>{
 const s=await fixture(page,context);await submit(page,1000);await s.close();await page.evaluate(k=>sessionStorage.setItem(k,JSON.stringify({order_id:'GE-newer-intent',amount:41000,mode:'subsidized'})),key);await s.stop();await expectRecoveryError(page,'저장된 주문이 변경');expect(await page.evaluate(k=>JSON.parse(sessionStorage.getItem(k)).order_id,key)).toBe('GE-newer-intent');await expect(page.getByRole('status').filter({hasText:/구매 진행.*중단/})).toHaveCount(0);
});
test('corrupt saved local receipt never reopens checkout or authorizes new purchase',async({page,context})=>{
 const s=await fixture(page,context);await submit(page,1000);await s.close();await s.stop();await expect(page.getByRole('button',{name:'테스트 식권 선택'})).toBeVisible();
 await page.evaluate(({k,receipt})=>{receipt.local_abandonment.requested_by='foreign';sessionStorage.setItem(k,JSON.stringify({order_id:receipt.order_id,amount:receipt.amount,mode:'subsidized',pending:{order_id:receipt.order_id,amount:receipt.amount,mode:'subsidized',checkout_started:true},local_abandonment_receipt:receipt}));},{k:key,receipt:receipt()});
 await page.reload();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();await expect(page.getByRole('heading',{name:'주문 상태 확인 필요'})).toBeVisible();expect(s.purchases).toBe(1);expect(s.hashes).toBe(1);await expect(page.getByRole('button',{name:'새 견적으로 구매 준비'})).toHaveCount(0);
});

test('a stalled close status read ends after its bounded timeout without any write',async({page,context})=>{
 const s=await fixture(page,context);let release;const barrier=new Promise(r=>release=r);
 await page.route('**/api-fixture/payments/recovery?**',async r=>{s.reads++;await barrier;try{await r.fulfill({json:{ok:true,data:{}}});}catch{}});
 await submit(page,1000);await page.getByRole('button',{name:'결제창 닫기'}).click();
 try {await expect(page.getByRole('alert')).toContainText('주문 상태 확인 오류',{timeout:13000});await expect(page.getByRole('button',{name:'다시 확인'})).toBeEnabled();expect(s.stops).toBe(0);expect(s.confirm).toBe(0);}finally{release();}
});

for(const device of [{name:'mobile-narrow',width:360,ua:'iPhone'},{name:'mobile-wide',width:1440,ua:'Android'},{name:'ipad',width:1024,ua:'Macintosh',touch:true}])test(`popup ${device.name}: focus loss not cancel; close read then explicit stop`,async({browser})=>{
 const context=await browser.newContext({viewport:{width:device.width,height:850},userAgent:device.ua,hasTouch:!!device.touch});const page=await context.newPage();
 if(device.touch)await page.addInitScript(()=>Object.defineProperty(navigator,'maxTouchPoints',{value:5}));
 try {const s=await fixture(page,context);await submit(page,1000);await expect.poll(()=>s.checkout).toBe(1);const child=context.pages().find(p=>p!==page);expect(child).toBeTruthy();await page.evaluate(()=>{window.dispatchEvent(new Event('blur'));window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'));});await page.waitForTimeout(500);expect(s.reads).toBe(0);expect(s.stops).toBe(0);
 await child.close();await expect.poll(()=>s.reads).toBe(1);await s.stop();await expect(page.getByRole('button',{name:'테스트 식권 선택'})).toBeVisible();expect(s.confirm).toBe(0);expect(s.hashes).toBe(0);expect(s.stops).toBe(1);
 if(process.env.PURCHASE_RECEIPTS)await page.screenshot({path:`${process.env.PURCHASE_RECEIPTS}/local-stop-${device.name}.png`,fullPage:true});
 }finally{await context.close();}
});
