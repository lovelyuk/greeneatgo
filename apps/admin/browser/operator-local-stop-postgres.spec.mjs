import { openRecovery } from './recovery-navigation.mjs';
// Built React -> actual authenticated FastAPI routes -> local PostgreSQL RPCs.
import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {writeFileSync} from 'node:fs';
import {setup,submit,purchaseResponse} from './final-L1-fixture.mjs';
test.use({userAgent:'iPhone'});
function producer(command,payload){return JSON.parse(execFileSync(process.env.FINALIZE_FIXTURE_PYTHON,['browser/finalization-producer.py',command,...(payload?[JSON.stringify(payload)]:[])],{encoding:'utf8',env:{...process.env,ENV:'test',SUPABASE_URL:'https://fixture.invalid',SUPABASE_ANON_KEY:'synthetic',SUPABASE_SERVICE_ROLE_KEY:'synthetic'}}));}
test('operator adjudication restores legacy pending through actual API to fresh deliberate purchase',async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON||!process.env.FINALIZE_TEST_DATABASE_URL,'requires disposable loopback PostgreSQL');
 const seed=producer('init-local'), adjudicated=producer('operator-stop'),calls=[];expect(adjudicated.stopped).toBe(true);const state=await setup(page,context,{gross:1100,points:0});
 await page.route('**/api-fixture/me',r=>r.fulfill({json:{ok:true,data:{user_id:seed.owner,role:'customer',status:'active',display_name:'Synthetic buyer',point_balance:0,voucher_balance:0,voucher_use_history:[],point_transactions:[],recent_transactions:[]}}}));
 await page.route('**/api-fixture/coupons',r=>r.fulfill({json:{ok:true,data:{merchant:{id:'33333333-3333-4333-8333-333333333333',name:'Synthetic merchant'},items:[],issued:[]}}}));
 await page.addInitScript(seed=>{if(!sessionStorage.getItem('synthetic-local-seeded')){sessionStorage.setItem(`greeneat-purchase-pending:${seed.owner}`,JSON.stringify({order_id:seed.order_id,amount:seed.amount,mode:'voucher',checkout_started:true}));sessionStorage.setItem('synthetic-local-seeded','yes');}},seed);
 for(const glob of ['**/api-fixture/vouchers/products','**/api-fixture/vouchers/quote','**/api-fixture/vouchers/purchase','**/api-fixture/payments/recovery?**','**/api-fixture/payments/orders/*/abandon','**/api-fixture/payments/local-abandonments?**'])await page.route(glob,r=>{
  const u=new URL(r.request().url()),path=u.pathname.replace('/api-fixture','')+u.search;
  const result=producer('request',{method:r.request().method(),path,body:r.request().postDataJSON()});calls.push({path,...result});return r.fulfill({status:result.status,json:result.json});
 });
 await page.goto('/shop');await page.getByLabel('이메일',{exact:true}).fill('fixture@example.invalid');await page.getByLabel('비밀번호',{exact:true}).fill('mocked-password-only');await page.getByRole('button',{name:'로그인',exact:true}).click();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();
 await expect.poll(()=>calls.filter(c=>c.path.startsWith('/payments/recovery?')).length).toBe(1);await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();expect(calls.filter(c=>c.path.endsWith('/abandon'))).toHaveLength(0);
 const stop=calls.find(c=>c.path.startsWith('/payments/recovery?'));expect(stop.status).toBe(200);expect(stop.json.data.local_abandonment.source).toBe('manual_database_operator');expect(stop.json.data.local_abandonment.provider_finality).toBe('unknown');
 await page.reload();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();await expect(page.getByRole('button',{name:'Synthetic ticket 선택'})).toBeVisible();
 await expect(page.getByRole('button',{name:'새 견적으로 구매 준비'})).toHaveCount(0);await page.getByRole('button',{name:'Synthetic ticket 선택'}).click();await expect(page.locator('.purchase-quote')).toBeVisible();await expect(page.getByLabel('구매 조건 확인')).not.toBeChecked();await page.getByLabel('구매 조건 확인').check();await page.getByRole('button',{name:'구매하기',exact:true}).click();
 await expect.poll(()=>calls.filter(c=>c.path==='/vouchers/purchase').length).toBe(1);const fresh=calls.find(c=>c.path==='/vouchers/purchase').json.data;expect(fresh.order_id).not.toBe(seed.order_id);
 // Provider transport never runs. A synthetic late approval enters the actual
 // durable SQL notification wrapper after abandonment/fresh order creation.
 const late=producer('late-local');expect(late.reconciliation_required).toBe(true);
 await page.getByRole('navigation').getByRole('button',{name:'내역',exact:true}).click();await expect(page.getByRole('alert').filter({hasText:'실제 청구 재확인'})).toBeVisible();
 const audit=producer('audit');expect(audit.orders).toHaveLength(2);expect(audit.orders.find(o=>o.order_id===seed.order_id)).toMatchObject({status:'canceled',started:true});expect(audit.local_receipts).toHaveLength(0);expect(audit.operator_receipts).toHaveLength(1);expect(audit.closures).toHaveLength(0);expect(audit.voucher_count.count).toBe(0);expect(audit.refund_count.count).toBe(0);expect(audit.discrepancies).toHaveLength(1);expect(state.errors).toEqual([]);
 if(process.env.PURCHASE_RECEIPTS)writeFileSync(`${process.env.PURCHASE_RECEIPTS}/real-operator-stop-ui-pg.json`,JSON.stringify({seed,stop,fresh,late,audit,calls,provider_transport:false},null,2));
});
