import { openRecovery } from './recovery-navigation.mjs';
import { test, expect } from '@playwright/test';
import { setup } from './final-L1-fixture.mjs';
const owner='11111111-1111-4111-8111-111111111111',key=`greeneat-purchase-pending:${owner}`;
const pending={order_id:'GE-S-restored-entry',amount:1100,mode:'subsidized',checkout_started:true};
const ready={order_id:pending.order_id,amount:1100,status:'ready',recovery_action:'reconcile',checkout_url:null,resumable:false};
const done={...ready,status:'done',recovery_action:'complete',completion:{order_id:pending.order_id,amount:1100,status:'done',issued_count:1,product_name:'테스트 식권'}};
async function boot(page,context,saved=pending){const state=await setup(page,context,{gross:1100,points:0});await page.addInitScript(({key,saved})=>{if(!sessionStorage.getItem('seeded')){sessionStorage.setItem(key,typeof saved==='string'?saved:JSON.stringify(saved));sessionStorage.setItem('seeded','yes');}},{key,saved});return state;}
async function login(page){await page.goto('/shop');await page.getByLabel('이메일',{exact:true}).fill('fixture@example.invalid');await page.getByLabel('비밀번호',{exact:true}).fill('mocked-password-only');await page.getByRole('button',{name:'로그인',exact:true}).click();}
async function unknown(page){await openRecovery(page);await expect(page.getByRole('heading',{name:'이전 결제 결과를 확인하지 못했어요.'})).toBeVisible();}
for(const width of [360,390,1440])test(`automatic restored done, loading, unknown and details screenshots ${width}`,async({page,context})=>{
 await page.setViewportSize({width,height:850});const state=await boot(page,context);let release,reads=0;const barrier=new Promise(r=>release=r);
 await page.route('**/api-fixture/payments/recovery?**',async r=>{const n=++reads;if(n<=2)await barrier;return r.fulfill({json:{ok:true,data:n>=4?done:ready}});});await login(page);await expect.poll(()=>reads).toBe(1);
 await openRecovery(page);await expect(page.getByRole('heading',{name:'결제 결과 확인 중'})).toBeVisible();const root=process.env.PURCHASE_RECEIPTS;
 const capture=async name=>{await page.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important}'});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);if(root)await page.screenshot({path:`${root}/recovery-${name}-${width}.png`,fullPage:true});};
 await capture('loading');release();await unknown(page);await capture('unknown');await openRecovery(page);await page.getByText('상세 보기',{exact:true}).click();await capture('details');await openRecovery(page);await page.getByRole('button',{name:'다시 확인',exact:true}).click();await unknown(page);expect(reads).toBe(3);await openRecovery(page);await page.getByRole('button',{name:'다시 확인',exact:true}).click();await expect(page.getByRole('heading',{name:'결제 완료',exact:true})).toBeVisible();await capture('done');expect(await page.evaluate(k=>sessionStorage.getItem(k),key)).toBeNull();expect(state.confirm).toBe(0);expect(state.errors).toEqual([]);
});
test('hidden mounted checkout ignores stale completion and reads once on actual reentry',async({page,context})=>{
 await boot(page,context);let reads=0,release;const barrier=new Promise(r=>release=r);
 await page.route('**/api-fixture/payments/recovery?**',async r=>{const n=++reads;if(n===1)await barrier;return r.fulfill({json:{ok:true,data:n===1?done:ready}});});await login(page);await expect.poll(()=>reads).toBe(1);await page.getByRole('navigation').getByRole('button',{name:'홈',exact:true}).click();release();await page.waitForTimeout(150);expect(await page.evaluate(k=>sessionStorage.getItem(k),key)).not.toBeNull();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();await expect.poll(()=>reads).toBe(2);await unknown(page);expect(reads).toBe(3);await page.waitForTimeout(350);expect(reads).toBe(3);await expect(page.getByRole('heading',{name:'결제 완료',exact:true})).toHaveCount(0);
});
test('restored status timeout retains exact pending and only retries read on demand',async({page,context})=>{
 const state=await boot(page,context);let reads=0,release;const barrier=new Promise(r=>release=r);
 await page.route('**/api-fixture/payments/recovery?**',async r=>{if(++reads<=2)await barrier;try{await r.fulfill({json:{ok:true,data:ready}});}catch{}});await login(page);await expect.poll(()=>reads).toBe(1);await openRecovery(page);
 try{await expect(page.getByRole('alert')).toContainText('주문 상태 확인 오류',{timeout:12500});await expect(page.getByRole('button',{name:'구매 진행 중단',exact:true})).toHaveCount(0);expect(JSON.parse(await page.evaluate(k=>sessionStorage.getItem(k),key))).toEqual(pending);await openRecovery(page);await page.getByRole('button',{name:'다시 확인',exact:true}).click();await expect(page.getByRole('button',{name:'구매 진행 중단',exact:true})).toBeVisible();expect(reads).toBe(3);expect(state.confirm).toBe(0);expect(state.checkout).toBe(0);}finally{release();}
});
for(const saved of ['{broken',{unknown:true},{completion:{status:'done',order_id:'GE-fake',amount:1100}}])test(`unsafe storage remains locked ${JSON.stringify(saved)}`,async({page,context})=>{
 const state=await boot(page,context,saved);await login(page);await expect(page.getByRole('heading',{name:'주문 상태 확인 필요'})).toHaveCount(0);await page.getByRole('button',{name:'테스트 식권 선택'}).click();await expect(page.locator('.purchase-quote')).toBeVisible();await page.getByLabel('구매 조건 확인').check();await page.getByRole('button',{name:'구매하기',exact:true}).click();await expect(page.getByRole('heading',{name:'주문 상태 확인 필요'})).toBeVisible();await expect(page.getByRole('heading',{name:'결제 완료',exact:true})).toHaveCount(0);expect(state.checkout).toBe(0);
});
