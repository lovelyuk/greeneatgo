-- Local PostgreSQL smoke test for migration 0062. Run only after the base schema
-- and 0062 exist; the ALTERs below emulate columns introduced between 0016/0036
-- when using a lightweight PostgreSQL image rather than the Supabase stack.
alter table public.merchant_companies add column if not exists tax_type text not null default 'tax_free';
alter table public.meal_transactions add column if not exists tax_type text not null default 'unclassified';
alter table public.meal_transactions add column if not exists supply_amount int;
alter table public.meal_transactions add column if not exists vat_amount int;
alter table public.meal_transactions add column if not exists total_amount int;
alter table public.meal_transactions add column if not exists settlement_tax_type text not null default 'unclassified';
alter table public.meal_transactions add column if not exists settlement_supply_amount int;
alter table public.meal_transactions add column if not exists settlement_vat_amount int;
alter table public.meal_transactions add column if not exists settlement_total_amount int;
create or replace function public.split_tax_inclusive(p_total int,p_tax_type text)
returns table(supply_amount int,vat_amount int,total_amount int) language sql immutable as $$
 select case when p_tax_type='taxable' then round(p_total::numeric/1.1)::int else p_total end,
        case when p_tax_type='taxable' then p_total-round(p_total::numeric/1.1)::int else 0 end,p_total
$$;

insert into auth.users(id) values
 ('00000000-0000-0000-0000-000000000001'),('00000000-0000-0000-0000-000000000002') on conflict do nothing;
insert into public.companies(id,name,status) values
 ('10000000-0000-0000-0000-000000000001','Prepaid Co','active'),
 ('10000000-0000-0000-0000-000000000002','Ledger Co','active') on conflict do nothing;
insert into public.merchants(id,name,qr_token,view_token,status) values
 ('20000000-0000-0000-0000-000000000001','Merchant','qr-prepaid','view-prepaid','active') on conflict do nothing;
insert into public.app_users(id,company_id,merchant_id,display_name,role,status) values
 ('00000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',null,'Employee','employee','active'),
 ('00000000-0000-0000-0000-000000000002',null,'20000000-0000-0000-0000-000000000001','Actor','merchant_admin','active') on conflict do nothing;
insert into public.merchant_companies(merchant_id,company_id,status,unit_price,tax_type,prepurchase_enabled) values
 ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','active',9000,'tax_free',true),
 ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000002','active',9000,'tax_free',false)
on conflict(merchant_id,company_id) do update set unit_price=excluded.unit_price,tax_type=excluded.tax_type,prepurchase_enabled=excluded.prepurchase_enabled;

select public.charge_merchant_company_prepurchase(
 '20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',
 '00000000-0000-0000-0000-000000000002',1,9000,'batch-old');
select public.charge_merchant_company_prepurchase(
 '20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',
 '00000000-0000-0000-0000-000000000002',2,9000,'batch-new');
update public.merchant_company_prepurchase_batches set purchased_at=case idempotency_key
 when 'batch-old' then now()-interval '2 days' else now()-interval '1 day' end
where merchant_id='20000000-0000-0000-0000-000000000001';

-- Duplicate charge returns the same row and does not add inventory.
do $$ declare r jsonb; n int; begin
 r:=public.charge_merchant_company_prepurchase(
  '20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000002',1,9000,'batch-old');
 select sum(remaining_quantity) into n from public.merchant_company_prepurchase_batches;
 if not (r->>'duplicate')::boolean or n<>3 then raise exception 'duplicate charge assertion failed'; end if;
end $$;

-- Unit price is an intentional per-batch entitlement snapshot, not a mirror of
-- the mutable current contract price. A committed retry wins over later state.
do $$ declare r jsonb; begin
 update public.merchant_companies set status='paused',prepurchase_enabled=false
  where merchant_id='20000000-0000-0000-0000-000000000001' and company_id='10000000-0000-0000-0000-000000000001';
 r:=public.charge_merchant_company_prepurchase(
  '20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000002',1,9000,'batch-old');
 if not (r->>'duplicate')::boolean or (r->>'unit_price')::int<>9000 then raise exception 'retry after disable assertion failed'; end if;
 begin
  perform public.charge_merchant_company_prepurchase(
   '20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',
   '00000000-0000-0000-0000-000000000002',1,9100,'batch-old');
  raise exception 'conflicting retry did not fail';
 exception when sqlstate 'P0001' then if sqlerrm<>'IDEMPOTENCY_CONFLICT' then raise; end if; end;
 update public.merchant_companies set status='active',prepurchase_enabled=true
  where merchant_id='20000000-0000-0000-0000-000000000001' and company_id='10000000-0000-0000-0000-000000000001';
end $$;

-- First payment consumes the oldest batch. Retry consumes nothing. Second payment
-- advances to the next batch.
select public.process_meal_pay(
 '00000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',
 '20000000-0000-0000-0000-000000000001',9000,'TX1','Lunch','{}','pay-1',null,null,null);
do $$ declare t public.meal_transactions%rowtype; begin
 select * into t from public.meal_transactions where idempotency_key='pay-1';
 if t.pay_type<>'ledger' or t.total_amount<>9000 or t.supply_amount<>9000 or t.vat_amount<>0
    or t.settlement_supply_amount<>0 or t.settlement_vat_amount<>0 or t.settlement_total_amount<>0
    or t.flags->>'prepurchase'<>'true' or nullif(t.flags->>'prepurchase_batch_id','') is null then
  raise exception 'prepaid accounting snapshot assertion failed';
 end if;
end $$;
do $$ declare old_n int; new_n int; r jsonb; begin
 select remaining_quantity into old_n from public.merchant_company_prepurchase_batches where idempotency_key='batch-old';
 if old_n<>0 then raise exception 'fifo assertion failed'; end if;
 r:=public.process_meal_pay(
  '00000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',
  '20000000-0000-0000-0000-000000000001',9000,'TX1','Lunch','{}','pay-1',null,null,null);
 select remaining_quantity into new_n from public.merchant_company_prepurchase_batches where idempotency_key='batch-new';
 if not (r->>'duplicate')::boolean or new_n<>2 then raise exception 'payment idempotency assertion failed'; end if;
end $$;
select public.process_meal_pay(
 '00000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',
 '20000000-0000-0000-0000-000000000001',9000,'TX2','Lunch','{}','pay-2',null,null,null);

-- A non-prepaid contract creates the unchanged ledger row with no consumption.
update public.app_users set company_id='10000000-0000-0000-0000-000000000002' where id='00000000-0000-0000-0000-000000000001';
select public.process_meal_pay(
 '00000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000002',
 '20000000-0000-0000-0000-000000000001',9000,'TX3','Lunch','{}','ledger-1',null,null,null);
do $$ begin
 if (select count(*) from public.merchant_company_prepurchase_consumptions)<>2 then
  raise exception 'non-prepaid consumed inventory';
 end if;
 if not exists(select 1 from public.meal_transactions where idempotency_key='ledger-1'
  and total_amount=9000 and settlement_supply_amount=9000 and settlement_vat_amount=0
  and settlement_total_amount=9000 and not (flags ? 'prepurchase')) then
  raise exception 'ordinary settlement snapshot assertion failed';
 end if;
end $$;

-- Exhaust the final prepaid ticket, then verify the next payment is blocked and
-- cannot leave a transaction behind.
update public.app_users set company_id='10000000-0000-0000-0000-000000000001' where id='00000000-0000-0000-0000-000000000001';
select public.process_meal_pay(
 '00000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',
 '20000000-0000-0000-0000-000000000001',9000,'TX4','Lunch','{}','pay-3',null,null,null);
do $$ begin
 begin
  perform public.process_meal_pay(
   '00000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',
   '20000000-0000-0000-0000-000000000001',9000,'TX5','Lunch','{}','pay-empty',null,null,null);
  raise exception 'empty inventory did not block';
 exception when sqlstate 'P0001' then
  if sqlerrm<>'PREPURCHASE_INVENTORY_EMPTY' then raise; end if;
 end;
 if exists(select 1 from public.meal_transactions where idempotency_key='pay-empty') then
  raise exception 'blocked payment persisted';
 end if;
end $$;

-- Settlement-facing reads retain usage counts but report no prepaid obligation.
do $$ declare ps jsonb; ls jsonb; pst jsonb; lst jsonb;
 month_start date:=date_trunc('month',current_date)::date;
 month_end date:=(date_trunc('month',current_date)+interval '1 month - 1 day')::date;
begin
 ps:=public.merchant_ledger_summary('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',month_start,month_end);
 ls:=public.merchant_ledger_summary('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000002',month_start,month_end);
 if (ps->>'total_amount')::int<>0 or (ps->>'total_count')::int<>3 then raise exception 'prepaid summary assertion failed: %',ps; end if;
 if (ls->>'total_amount')::int<>9000 then raise exception 'ordinary summary assertion failed: %',ls; end if;
 pst:=public.create_merchant_settlement('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',month_start,month_end);
 lst:=public.create_merchant_settlement('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000002',month_start,month_end);
 if (pst->>'total_amount')::int<>0 or (pst->>'tx_count')::int<>3 then raise exception 'prepaid settlement assertion failed: %',pst; end if;
 if (lst->>'total_amount')::int<>9000 then raise exception 'ordinary settlement assertion failed: %',lst; end if;
end $$;

-- Refund/cancel rows referencing one consumed spend restore its batch exactly once.
do $$ declare original_id bigint; before_n int; after_n int; begin
 select id into original_id from public.meal_transactions where idempotency_key='pay-1';
 select remaining_quantity into before_n from public.merchant_company_prepurchase_batches where idempotency_key='batch-old';
 insert into public.meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,flags,idempotency_key,pay_type,
  tax_type,supply_amount,vat_amount,total_amount,settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,original_transaction_id)
 values('00000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001',
  9000,'refund','REF1','{}','refund-1','ledger','tax_free',9000,0,9000,'tax_free',9000,0,9000,original_id);
 insert into public.meal_transactions(user_id,company_id,merchant_id,amount,kind,tx_code,flags,idempotency_key,pay_type,
  tax_type,supply_amount,vat_amount,total_amount,settlement_tax_type,settlement_supply_amount,settlement_vat_amount,settlement_total_amount,original_transaction_id)
 values('00000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001',
  9000,'cancel','CAN1','{}','cancel-1','ledger','tax_free',9000,0,9000,'tax_free',9000,0,9000,original_id);
 select remaining_quantity into after_n from public.merchant_company_prepurchase_batches where idempotency_key='batch-old';
 if after_n<>before_n+1 or after_n>1 then raise exception 'exactly-once restoration assertion failed'; end if;
 if (select count(*) from public.merchant_company_prepurchase_reversals)<>1 then raise exception 'reversal audit assertion failed'; end if;
 if exists(select 1 from public.meal_transactions where idempotency_key in ('refund-1','cancel-1')
  and (settlement_total_amount<>0 or flags->>'prepurchase'<>'true')) then raise exception 'reversal snapshot assertion failed'; end if;
end $$;
