import {test,expect} from '@playwright/test';
import {setup,submit,purchaseResponse} from './final-L1-fixture.mjs';
const owner='11111111-1111-4111-8111-111111111111';
const pending={order_id:'GE-history-legacy',amount:1100,mode:'subsidized',checkout_started:true};
const ready={...pending,status:'ready',recovery_action:'reconcile',checkout_url:null,resumable:false};
// Login always lands on 홈 (user rule); a restored pending checkout is resolved
// in the mounted catalog, so tests open 구매 the way a buyer would.
async function login(page){await page.goto('/shop');await page.getByLabel('이메일',{exact:true}).fill('fixture@example.invalid');await page.getByLabel('비밀번호',{exact:true}).fill('mocked-password-only');await page.getByRole('button',{name:'로그인',exact:true}).click();const nav=page.getByRole('navigation',{name:'구매자 탭'});if(await nav.waitFor({state:'visible',timeout:3000}).then(()=>true).catch(()=>false))await nav.getByRole('button',{name:'구매',exact:true}).click();}
const tab=(page,name)=>page.getByRole('navigation').getByRole('button',{name,exact:true});

const receipt={...ready,user_id:owner,status:'canceled',recovery_action:'locally_abandoned',completion:null,local_abandonment:{id:'22222222-2222-4222-8222-222222222222',source:'owner_request',scope:'local_order',outcome:'abandoned',requested_by:owner,requested_at:'2026-10-15T01:02:03+09:00',provider_finality:'unknown',residual_late_approval_possible:true}};
test('buy again with a leftover unpaid order stops it silently and continues straight into the new purchase',async({page,context})=>{
 const state=await setup(page,context,{gross:1100,points:0});let stops=0,purchases=0;const bodies=[];
 await page.addInitScript(({owner,pending})=>{if(!sessionStorage.getItem('seeded')){sessionStorage.setItem(`greeneat-purchase-pending:${owner}`,JSON.stringify(pending));sessionStorage.setItem('seeded','1');}},{owner,pending});
 await page.route('**/api-fixture/payments/recovery?**',r=>r.fulfill({json:{ok:true,data:stops?receipt:ready}}));
 await page.route('**/api-fixture/payments/orders/*/abandon',r=>{stops++;bodies.push(r.request().postDataJSON());return r.fulfill({json:{ok:true,data:receipt}});});
 await page.addInitScript(()=>Object.defineProperty(navigator,'userAgent',{value:'iPhone'}));
 await page.route('**/api-fixture/vouchers/purchase-subsidized',r=>{purchases++;return r.fulfill({json:{ok:true,data:purchaseResponse(1100,0)}});});
 await login(page);await page.getByRole('button',{name:'테스트 식권 선택'}).click();await expect(page.locator('.purchase-quote')).toBeVisible();await page.getByLabel('구매 조건 확인').check();await page.getByRole('button',{name:'구매하기',exact:true}).click();
 await expect.poll(()=>purchases,{timeout:8000}).toBe(1);
 expect(stops).toBe(1);expect(bodies).toEqual([{amount:1100,explicit_checkout_cancel_intent:true}]);
 await expect(tab(page,'구매')).toHaveAttribute('aria-current','page');await expect(page.getByText('이전 주문의 결제 결과를 먼저 확인해 주세요',{exact:false})).toHaveCount(0);
 expect(state.confirm).toBe(0);
});
test('manual history stop still requires meaningful consent when the automatic stop is not possible',async({page,context})=>{
 const state=await setup(page,context,{gross:1100,points:0});let stops=0;
 await page.addInitScript(({owner,pending})=>sessionStorage.setItem(`greeneat-purchase-pending:${owner}`,JSON.stringify(pending)),{owner,pending});
 await page.route('**/api-fixture/payments/recovery?**',r=>r.fulfill({json:{ok:true,data:ready}}));
 await page.route('**/api-fixture/payments/orders/*/abandon',r=>{stops++;expect(r.request().postDataJSON()).toEqual({amount:1100,acknowledge_provider_uncertainty:true});return r.fulfill({json:{ok:true,data:receipt}});});
 await page.addInitScript(()=>Object.defineProperty(navigator,'userAgent',{value:'iPhone'}));
 await login(page);await tab(page,'내역').click();
 await page.getByRole('button',{name:'구매 진행 중단',exact:true}).click();await expect(page.getByRole('region',{name:'구매 진행 중단 안내'})).toContainText('나중에 승인·청구될 수 있어요');await expect(page.getByRole('button',{name:'확인하고 구매 진행 중단'})).toBeDisabled();expect(stops).toBe(0);
 await page.getByLabel('PG 취소·환불 확정이 아님을 이해했습니다').check();await page.getByRole('button',{name:'확인하고 구매 진행 중단'}).click();
 await expect(tab(page,'구매')).toHaveAttribute('aria-current','page');await expect(page.getByRole('button',{name:'테스트 식권 선택'})).toBeVisible();expect(stops).toBe(1);expect(state.confirm).toBe(0);
});

for(const points of [0,1100])test(`purchase POST survives buy-history view change without new financial admission ${points}`,async({page,context})=>{
 await setup(page,context,{gross:1100,points});let writes=0,release;const barrier=new Promise(r=>release=r);
 await page.addInitScript(()=>Object.defineProperty(navigator,'userAgent',{value:'iPhone'}));
 await page.route('**/api-fixture/vouchers/purchase-subsidized',async r=>{writes++;await barrier;return r.fulfill({json:{ok:true,data:purchaseResponse(1100,points)}});});
 await submit(page,points);await expect.poll(()=>writes).toBe(1);const key=`greeneat-purchase-pending:${owner}`;expect(JSON.parse(await page.evaluate(k=>sessionStorage.getItem(k),key)).unknown).toBe(true);
 await tab(page,'내역').click();release();
 if(points===1100){await expect(page.getByRole('heading',{name:'결제 완료',exact:true})).toBeVisible();await expect(page.getByText('발급 식권 11장')).toBeVisible();}
 else {await expect(page.getByRole('button',{name:'다시 확인',exact:true})).toBeVisible();expect(JSON.parse(await page.evaluate(k=>sessionStorage.getItem(k),key)).order_id).toBe('GE-S-final-L1');}
 expect(writes).toBe(1);expect(context.pages()).toHaveLength(1);
});
for(const width of [360,390,1440])test(`purchase and history DOM and screenshots ${width}`,async({page,context})=>{
 await page.setViewportSize({width,height:850});await setup(page,context,{gross:1100,points:0});let fail=false;
 await page.addInitScript(({owner,pending})=>sessionStorage.setItem(`greeneat-purchase-pending:${owner}`,JSON.stringify(pending)),{owner,pending});
 await page.route('**/api-fixture/payments/recovery?**',r=>r.fulfill(fail?{status:503,json:{detail:{message:'synthetic unavailable'}}}:{json:{ok:true,data:ready}}));
 const capture=async name=>{await page.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important}'});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);if(process.env.PURCHASE_RECEIPTS)await page.screenshot({path:`${process.env.PURCHASE_RECEIPTS}/history-${name}-${width}.png`,fullPage:true});};
 await login(page);await expect(page.getByRole('button',{name:'테스트 식권 선택'})).toBeVisible();await expect(page.locator('.recovery-card')).toHaveCount(0);await capture('buy-initial');
 await page.getByRole('button',{name:'테스트 식권 선택'}).click();await expect(page.locator('.purchase-quote')).toBeVisible();await expect(page.locator('.recovery-card')).toHaveCount(0);await capture('buy-selected');
 await tab(page,'내역').click();await expect(page.getByRole('button',{name:'구매 진행 중단',exact:true})).toBeVisible();await capture('pending');fail=true;await page.getByRole('button',{name:'다시 확인',exact:true}).click();await expect(page.getByRole('alert')).toContainText('주문 상태 확인 오류');await capture('error');
});

test('history read cannot retire pending after navigating away',async({page,context})=>{
 await setup(page,context,{gross:1100,points:0});let reads=0,release;const barrier=new Promise(r=>release=r);
 await page.addInitScript(({owner,pending})=>sessionStorage.setItem(`greeneat-purchase-pending:${owner}`,JSON.stringify(pending)),{owner,pending});
 await page.route('**/api-fixture/payments/recovery?**',async r=>{reads++;if(reads===1)return r.fulfill({json:{ok:true,data:ready}});await barrier;return r.fulfill({json:{ok:true,data:{...ready,status:'done',recovery_action:'complete',completion:{order_id:pending.order_id,amount:1100,status:'done',issued_count:1}}}});});
 await login(page);await expect.poll(()=>reads).toBe(1);await tab(page,'내역').click();await expect.poll(()=>reads).toBe(2);await tab(page,'구매').click();release();await page.waitForTimeout(150);
 expect(JSON.parse(await page.evaluate(owner=>sessionStorage.getItem(`greeneat-purchase-pending:${owner}`),owner))).toEqual(pending);
 await expect(page.getByRole('heading',{name:'결제 완료',exact:true})).toHaveCount(0);
});
test('legacy pending is absent from purchase DOM; explicit purchase sets it aside and continues on purchase',async({page,context})=>{
 const state=await setup(page,context,{gross:1100,points:0});let reads=0,writes=0;
 await page.addInitScript(({owner,pending})=>{if(!sessionStorage.getItem('seeded')){sessionStorage.setItem(`greeneat-purchase-pending:${owner}`,JSON.stringify(pending));sessionStorage.setItem('seeded','1');}},{owner,pending});
 await page.route('**/api-fixture/payments/recovery?**',r=>{reads++;expect(r.request().headers().authorization).toBe('Bearer fixture-access');return r.fulfill({json:{ok:true,data:ready}});});
 await page.route('**/api-fixture/payments/orders/*/abandon',r=>r.fulfill({status:409,json:{detail:{code:'ORDER_HAS_PAYMENT_OR_RESOURCE_HISTORY',message:'synthetic refusal'}}}));
 await page.addInitScript(()=>Object.defineProperty(navigator,'userAgent',{value:'iPhone'}));
 await page.route('**/api-fixture/vouchers/purchase-subsidized',r=>{writes++;return r.abort();});
 await login(page);await expect.poll(()=>reads).toBe(1);
 await expect(page.locator('.purchase-catalog .recovery-card')).toHaveCount(0);
 await expect(page.getByRole('heading',{name:'이전 결제 결과를 확인하지 못했어요.'})).toHaveCount(0);
 await page.getByRole('button',{name:'테스트 식권 선택'}).click();await expect(page.locator('.purchase-quote')).toBeVisible();
 await page.getByLabel('구매 조건 확인').check();await page.getByRole('button',{name:'구매하기',exact:true}).click();
 await expect.poll(()=>writes,{timeout:8000}).toBe(1);
 await expect(tab(page,'구매')).toHaveAttribute('aria-current','page');
 await expect(page.getByText('이전 주문의 결제 결과를 먼저 확인해 주세요',{exact:false})).toHaveCount(0);
 expect(state.confirm).toBe(0);
});
