import { openRecovery } from './recovery-navigation.mjs';
import {test,expect} from '@playwright/test';
import {setup,submit,purchaseResponse} from './final-L1-fixture.mjs';
const owner='11111111-1111-4111-8111-111111111111',key=`greeneat-purchase-pending:${owner}`;
for(const points of [0,1100])test(`hidden delayed admitted purchase stays locked across reentry card points ${points}`,async({page,context})=>{
 const state=await setup(page,context,{gross:1100,points});let count=0,release;const barrier=new Promise(r=>release=r);
 await page.addInitScript(()=>Object.defineProperty(navigator,'userAgent',{value:'iPhone'}));
 await page.route('**/api-fixture/vouchers/purchase-subsidized',async r=>{count++;await barrier;try{await r.fulfill({json:{ok:true,data:purchaseResponse(1100,points)}});}catch{}});
 await submit(page,points);await expect.poll(()=>count).toBe(1);await page.getByRole('navigation').getByRole('button',{name:'홈',exact:true}).click();release();await page.waitForTimeout(150);await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();
 await openRecovery(page);await expect(page.getByRole('heading',{name:'주문 상태 확인 필요'})).toBeVisible();await expect(page.getByRole('button',{name:'구매하기',exact:true})).toHaveCount(0);expect(count).toBe(1);expect(JSON.parse(await page.evaluate(k=>sessionStorage.getItem(k),key)).unknown).toBe(true);expect(state.confirm).toBe(0);
});
for(const kind of ['cancel','fail','success'])test(`mobile live return survives mounted tab roundtrip ${kind}`,async({page,context})=>{
 await page.addInitScript(()=>Object.defineProperty(navigator,'userAgent',{value:'iPhone'}));await setup(page,context,{gross:1100,points:0});let stops=0,reads=0;
 await page.route('**/api-fixture/vouchers/purchase-subsidized',r=>r.fulfill({json:{ok:true,data:purchaseResponse(1100,0)}}));
 await page.route('**/api-fixture/payments/recovery?**',r=>{reads++;return r.fulfill({json:{ok:true,data:{order_id:'GE-S-final-L1',amount:1100,status:'ready',recovery_action:'reconcile',resumable:false,checkout_url:null}}});});
 await page.route('**/api-fixture/payments/orders/*/abandon',r=>{stops++;expect(r.request().postDataJSON()).toEqual(kind==='cancel'?{amount:1100,explicit_checkout_cancel_intent:true}:{amount:1100,checkout_return_ended:'mobile_fail'});return r.fulfill({json:{ok:true,data:{order_id:'GE-S-final-L1',amount:1100,user_id:owner,status:'canceled',recovery_action:'locally_abandoned',resumable:false,checkout_url:null,completion:null,local_abandonment:{id:'22222222-2222-4222-8222-222222222222',source:'owner_request',scope:'local_order',outcome:'abandoned',requested_by:owner,requested_at:'2026-10-15T01:02:03+09:00',provider_finality:'unknown',residual_late_approval_possible:true}}}});});
 await submit(page,0);await expect.poll(()=>context.pages().length).toBe(2);const child=context.pages().find(p=>p!==page);await child.waitForURL('**/api-fixture/payments/checkout/**');const nonce=new URL(child.url()).searchParams.get('return_nonce');await page.getByRole('navigation').getByRole('button',{name:'홈',exact:true}).click();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();await expect.poll(()=>reads).toBe(1);
 await child.goto(`/payment-return#${kind}.${nonce}`).catch(()=>{});
 if(kind==='success'){await expect.poll(()=>reads).toBe(2);expect(stops).toBe(0);}else{await expect(page.getByRole('heading',{name:'식권 구매',exact:true})).toBeVisible();await expect.poll(()=>stops).toBe(1);}
});
for(const mutation of ['newer','corrupt','unreadable'])test(`automatic done cannot erase ${mutation} stored intent`,async({page,context})=>{
 await setup(page,context,{gross:1100,points:0});const old={order_id:'GE-old-completion',amount:1100,mode:'subsidized',checkout_started:true};let release;const barrier=new Promise(r=>release=r);
 await page.addInitScript(({key,old})=>sessionStorage.setItem(key,JSON.stringify(old)),{key,old});
 await page.route('**/api-fixture/payments/recovery?**',async r=>{await barrier;return r.fulfill({json:{ok:true,data:{order_id:old.order_id,amount:1100,status:'done',recovery_action:'complete',resumable:false,checkout_url:null,completion:{order_id:old.order_id,amount:1100,status:'done',issued_count:1}}}});});
 await page.goto('/shop');await page.getByLabel('이메일',{exact:true}).fill('fixture@example.invalid');await page.getByLabel('비밀번호',{exact:true}).fill('mocked-password-only');await page.getByRole('button',{name:'로그인',exact:true}).click();await openRecovery(page);await expect(page.getByRole('heading',{name:'결제 결과 확인 중'})).toBeVisible();
 await page.evaluate(({key,mutation})=>{if(mutation==='unreadable'){const get=Storage.prototype.getItem;window.restoreGet=()=>Storage.prototype.getItem=get;Storage.prototype.getItem=function(k){if(k===key)throw Error('synthetic unreadable');return get.call(this,k);};}else sessionStorage.setItem(key,mutation==='corrupt'?'{broken':JSON.stringify({order_id:'GE-newer-order',amount:1100,mode:'subsidized'}));},{key,mutation});release();
 await expect(page.getByRole('alert')).toContainText('주문 상태 확인 오류');await expect(page.getByRole('heading',{name:'결제 완료',exact:true})).toHaveCount(0);
 if(mutation==='unreadable')await page.evaluate(()=>window.restoreGet());const saved=await page.evaluate(k=>sessionStorage.getItem(k),key);expect(saved).not.toBeNull();if(mutation==='newer')expect(JSON.parse(saved).order_id).toBe('GE-newer-order');if(mutation==='corrupt')expect(saved).toBe('{broken');
});
