import {test,expect} from '@playwright/test';
import {setup} from './final-L1-fixture.mjs';
const owner='11111111-1111-4111-8111-111111111111',key=`greeneat-purchase-pending:${owner}`;
const pending={order_id:'GE-old-reservation',amount:1100,mode:'subsidized',checkout_started:false};
const ready={order_id:pending.order_id,amount:1100,status:'ready',recovery_action:'reconcile',resumable:false,checkout_url:null};
const tab=(p,n)=>p.getByRole('navigation').getByRole('button',{name:n,exact:true});
async function boot(page,context){
 await setup(page,context,{gross:1100,points:0});
 await page.addInitScript(({key,pending})=>sessionStorage.setItem(key,JSON.stringify(pending)),{key,pending});
 await page.route('**/api-fixture/payments/recovery?**',r=>r.fulfill({json:{ok:true,data:ready}}));
 await page.goto('/shop');await page.getByLabel('이메일',{exact:true}).fill('fixture@example.invalid');await page.getByLabel('비밀번호',{exact:true}).fill('mocked-password-only');await page.getByRole('button',{name:'로그인',exact:true}).click();await tab(page,'내역').click();await page.getByText('상세 보기',{exact:true}).click();
}
for(const scenario of ['hidden','roundtrip','newer','sentinel','corrupt','unreadable','remove-failed','success'])test(`reservation cancel preserves authority: ${scenario}`,async({page,context})=>{
 let release,started=0;const barrier=new Promise(r=>release=r);await boot(page,context);
 await page.route('**/api-fixture/vouchers/subsidized-orders/*/cancel',async r=>{started++;await barrier;await r.fulfill({json:{ok:true,data:{released:true,point_amount:0}}});});
 await page.getByRole('button',{name:'예약 취소 요청'}).click();await expect.poll(()=>started).toBe(1);
 let expected=JSON.stringify(pending);
 if(scenario==='hidden'||scenario==='roundtrip'){await tab(page,'구매').click();if(scenario==='roundtrip')await tab(page,'내역').click();}
 if(scenario==='newer'||scenario==='sentinel'||scenario==='corrupt'){
  expected=scenario==='newer'?JSON.stringify({...pending,order_id:'GE-newer-reservation'}):scenario==='sentinel'?JSON.stringify({unknown:true,attempt_id:'different-admission'}):'{invalid-json';
  await page.evaluate(({key,value})=>sessionStorage.setItem(key,value),{key,value:expected});
 }
 if(scenario==='unreadable'||scenario==='remove-failed')await page.evaluate(({key,method})=>{
  const original=Storage.prototype[method];window.restoreCancelStorage=()=>Storage.prototype[method]=original;
  Storage.prototype[method]=function(k,...args){if(this===sessionStorage&&k===key)throw new Error('synthetic storage failure');return original.call(this,k,...args);};
 },{key,method:scenario==='unreadable'?'getItem':'removeItem'});
 release();
 if(scenario==='success'){
  await expect(page.getByRole('heading',{name:'결제 취소 확인'})).toBeVisible();
  expect(await page.evaluate(key=>sessionStorage.getItem(key),key)).toBeNull();
 }else{
  if(!['hidden','roundtrip'].includes(scenario))await expect(page.locator('.recovery-card').getByRole('button',{name:'다시 확인',exact:true})).toBeEnabled();
  await page.waitForTimeout(250);
  await page.evaluate(()=>window.restoreCancelStorage?.());
  expect(await page.evaluate(key=>sessionStorage.getItem(key),key)).toBe(expected);
  await expect(page.getByRole('heading',{name:'결제 취소 확인'})).toHaveCount(0);
  await tab(page,'구매').click();await page.getByRole('button',{name:'테스트 식권 선택'}).click();await expect(page.locator('.purchase-quote')).toBeVisible();await page.getByLabel('구매 조건 확인').check();await page.getByRole('button',{name:'구매하기',exact:true}).click();await expect(tab(page,'구매')).toHaveAttribute('aria-current','page');await expect(page.getByText('이전 주문의 결제 결과를 먼저 확인해 주세요',{exact:false})).toHaveCount(0);
 }
 expect(started).toBe(1);
});
