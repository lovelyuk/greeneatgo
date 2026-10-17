import { openRecovery } from './recovery-navigation.mjs';
import { test, expect } from '@playwright/test';
import { setup } from './final-L1-fixture.mjs';
const owner='11111111-1111-4111-8111-111111111111';
const pending={order_id:'GE-S-legacy-unknown',amount:1100,mode:'subsidized',checkout_started:true};
const ready={...pending,status:'ready',recovery_action:'reconcile',checkout_url:null,resumable:false};
// Login always lands on 홈 (user rule); a restored pending checkout is resolved
// in the mounted catalog, so tests open 구매 the way a buyer would.
async function login(page){await page.goto('/shop');await page.getByLabel('이메일',{exact:true}).fill('fixture@example.invalid');await page.getByLabel('비밀번호',{exact:true}).fill('mocked-password-only');await page.getByRole('button',{name:'로그인',exact:true}).click();const nav=page.getByRole('navigation',{name:'구매자 탭'});if(await nav.waitFor({state:'visible',timeout:3000}).then(()=>true).catch(()=>false))await nav.getByRole('button',{name:'구매',exact:true}).click();}
async function restored(page,context,result=ready){
 const state=await setup(page,context,{gross:1100,points:0});let reads=0;
 await page.addInitScript(({owner,pending})=>sessionStorage.setItem(`greeneat-purchase-pending:${owner}`,JSON.stringify(pending)),{owner,pending});
 await page.route('**/api-fixture/payments/recovery?**',r=>{reads++;expect(r.request().headers().authorization).toBe('Bearer fixture-access');return r.fulfill({json:{ok:true,data:result}});});
 return {state,reads:()=>reads};
}
test('legacy unknown automatically reads once, shows two actions and collapsed technical details',async({page,context})=>{
 const f=await restored(page,context);await login(page);
 await openRecovery(page);await expect(page.getByRole('heading',{name:'이전 결제 결과를 확인하지 못했어요.'})).toBeVisible();
 expect(f.reads()).toBe(2); // automatic catalog entry + explicit history entry
 await expect(page.getByRole('button',{name:'다시 확인',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'구매 진행 중단',exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'승인 상태 확인',exact:true})).toHaveCount(0);
 await expect(page.getByText(`주문 ${pending.order_id}`,{exact:true})).not.toBeVisible();
 await openRecovery(page);await page.getByText('상세 보기',{exact:true}).click();await expect(page.getByText(`주문 ${pending.order_id}`,{exact:true})).toBeVisible();
 await page.waitForTimeout(350);expect(f.reads()).toBe(2);expect(f.state.confirm).toBe(0);
 await openRecovery(page);await page.getByRole('button',{name:'다시 확인',exact:true}).click();await expect.poll(f.reads).toBe(3);
});
const stopped={...ready,user_id:owner,status:'canceled',recovery_action:'locally_abandoned',completion:null,local_abandonment:{id:'22222222-2222-4222-8222-222222222222',source:'owner_request',scope:'local_order',outcome:'abandoned',requested_by:owner,requested_at:'2026-10-15T01:02:03+09:00',provider_finality:'unknown',residual_late_approval_possible:true}};
test('trusted local stop receipt returns original catalog without another buyer step',async({page,context})=>{
 const f=await restored(page,context,stopped);await login(page);
 await expect(page.getByText('구매 진행을 중단했어요. PG 취소·환불 확정은 아니에요.',{exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'구매 진행 중단 접수'})).toHaveCount(0);
 expect(await page.evaluate(owner=>sessionStorage.getItem(`greeneat-purchase-pending:${owner}`),owner)).toBeNull();
 await page.getByRole('button',{name:'테스트 식권 선택'}).click();await expect(page.locator('.purchase-quote')).toBeVisible();await expect(page.getByLabel('구매 조건 확인')).not.toBeChecked();expect(f.reads()).toBe(1);
});

