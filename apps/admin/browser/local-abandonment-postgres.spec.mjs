// Built React -> actual authenticated FastAPI routes -> local PostgreSQL RPCs.
import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {writeFileSync} from 'node:fs';
import {setup,submit,purchaseResponse} from './final-L1-fixture.mjs';
test.use({userAgent:'iPhone'});
function producer(command,payload){return JSON.parse(execFileSync(process.env.FINALIZE_FIXTURE_PYTHON,['browser/finalization-producer.py',command,...(payload?[JSON.stringify(payload)]:[])],{encoding:'utf8',env:{...process.env,ENV:'test',SUPABASE_URL:'https://fixture.invalid',SUPABASE_ANON_KEY:'synthetic',SUPABASE_SERVICE_ROLE_KEY:'synthetic'}}));}
test('real owner stop producer to reload/new distinct purchase and durable late charge history',async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON||!process.env.FINALIZE_TEST_DATABASE_URL,'requires disposable loopback PostgreSQL');
 const seed=producer('init-local'),calls=[];const state=await setup(page,context,{gross:1100,points:0});
 await page.route('**/api-fixture/me',r=>r.fulfill({json:{ok:true,data:{user_id:seed.owner,role:'customer',status:'active',display_name:'Synthetic buyer',point_balance:0,voucher_balance:0,voucher_use_history:[],point_transactions:[],recent_transactions:[]}}}));
 await page.route('**/api-fixture/coupons',r=>r.fulfill({json:{ok:true,data:{merchant:{id:'33333333-3333-4333-8333-333333333333',name:'Synthetic merchant'},items:[],issued:[]}}}));
 await page.addInitScript(seed=>{if(!sessionStorage.getItem('synthetic-local-seeded')){sessionStorage.setItem(`greeneat-purchase-pending:${seed.owner}`,JSON.stringify({order_id:seed.order_id,amount:seed.amount,mode:'voucher',checkout_started:true}));sessionStorage.setItem('synthetic-local-seeded','yes');}},seed);
 for(const glob of ['**/api-fixture/vouchers/products','**/api-fixture/vouchers/quote','**/api-fixture/vouchers/purchase','**/api-fixture/payments/recovery?**','**/api-fixture/payments/orders/*/abandon','**/api-fixture/payments/local-abandonments?**'])await page.route(glob,r=>{
  const u=new URL(r.request().url()),path=u.pathname.replace('/api-fixture','')+u.search;
  const result=producer('request',{method:r.request().method(),path,body:r.request().postDataJSON()});calls.push({path,...result});return r.fulfill({status:result.status,json:result.json});
 });
 await page.goto('/shop');await page.getByLabel('이메일',{exact:true}).fill('fixture@example.invalid');await page.getByLabel('비밀번호',{exact:true}).fill('mocked-password-only');await page.getByRole('button',{name:'로그인',exact:true}).click();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();
 await page.getByRole('button',{name:'저장된 주문 상태 확인'}).click();await page.getByRole('button',{name:'이 주문 구매 중단',exact:true}).click();await page.getByLabel('PG 취소·환불 확정이 아님을 이해했습니다').check();await page.getByRole('button',{name:'확인하고 구매 진행 중단'}).click();await expect(page.getByRole('heading',{name:'구매 진행 중단 접수'})).toBeVisible();
 const stop=calls.find(c=>c.path.endsWith('/abandon'));expect(stop.status).toBe(200);expect(stop.json.data.local_abandonment.provider_finality).toBe('unknown');
 await page.reload();await page.getByRole('navigation').getByRole('button',{name:'구매',exact:true}).click();await expect(page.getByRole('heading',{name:'구매 진행 중단 접수'})).toBeVisible();
 await page.getByRole('button',{name:'새 견적으로 구매 준비'}).click();await page.getByRole('button',{name:'Synthetic ticket 선택'}).click();await page.getByRole('button',{name:'견적 확인',exact:true}).click();await expect(page.getByLabel('구매 조건 확인')).not.toBeChecked();await page.getByLabel('구매 조건 확인').check();await page.getByRole('button',{name:'구매하기',exact:true}).click();
 await expect.poll(()=>calls.filter(c=>c.path==='/vouchers/purchase').length).toBe(1);const fresh=calls.find(c=>c.path==='/vouchers/purchase').json.data;expect(fresh.order_id).not.toBe(seed.order_id);
 // Provider transport never runs. A synthetic late approval enters the actual
 // durable SQL notification wrapper after abandonment/fresh order creation.
 const late=producer('late-local');expect(late.reconciliation_required).toBe(true);
 await page.getByRole('navigation').getByRole('button',{name:'내역',exact:true}).click();await expect(page.getByRole('alert').filter({hasText:'실제 청구 재확인'})).toBeVisible();
 const audit=producer('audit');expect(audit.orders).toHaveLength(2);expect(audit.orders.find(o=>o.order_id===seed.order_id)).toMatchObject({status:'canceled',started:true});expect(audit.local_receipts).toHaveLength(1);expect(audit.closures).toHaveLength(0);expect(audit.voucher_count.count).toBe(0);expect(audit.refund_count.count).toBe(0);expect(audit.discrepancies).toHaveLength(1);expect(state.errors).toEqual([]);
 if(process.env.PURCHASE_RECEIPTS)writeFileSync(`${process.env.PURCHASE_RECEIPTS}/real-owner-stop-ui-pg.json`,JSON.stringify({seed,stop,fresh,late,audit,calls,provider_transport:false},null,2));
});
for(const path of ['/c','/f','/p'])test(`actual safe return page ${path} closes openerless mobile popup; parent only reads status`,async({page,context})=>{
 test.skip(!process.env.FINALIZE_FIXTURE_PYTHON||!process.env.FINALIZE_TEST_DATABASE_URL,'requires local-only router adapter');
 const html=producer('request',{path}).html;expect(html).toContain('PG 승인·취소·환불 확정이 아닙니다');const state=await setup(page,context,{gross:42000,points:1000});let reads=0,stops=0;
 await page.route('**/api-fixture/vouchers/purchase-subsidized',r=>r.fulfill({json:{ok:true,data:purchaseResponse(42000,1000)}}));
 await page.route('**/api-fixture/payments/recovery?**',r=>{reads++;return r.fulfill({json:{ok:true,data:{order_id:'GE-S-final-L1',amount:41000,status:'ready',recovery_action:'reconcile',resumable:false,checkout_url:null}}});});
 await page.route('**/api-fixture/payments/orders/*/abandon',r=>{stops++;return r.abort();});
 await context.route(`**/return-fixture${path}`,r=>r.fulfill({contentType:'text/html',body:html}));await submit(page,1000);await expect.poll(()=>state.checkout).toBe(1);const child=context.pages().find(p=>p!==page);await child.waitForURL('**/api-fixture/payments/checkout/**');await child.waitForLoadState();expect(await child.evaluate(()=>window.opener)).toBeNull();const closed=child.waitForEvent('close');await child.goto(`/return-fixture${path}`).catch(()=>{});await closed;
 await expect.poll(()=>reads).toBe(1);await expect(page.getByRole('button',{name:'이 주문 구매 중단',exact:true})).toBeVisible();expect(stops).toBe(0);expect(state.confirm).toBe(0);
});
