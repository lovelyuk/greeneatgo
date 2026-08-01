begin;

-- Reconcile eligible ordinary transaction months that existed before the
-- automatic INSERT trigger was installed. Existing settlements, demo rows,
-- invalid snapshots, and mixed-tax months are deliberately left untouched.
do $$
declare
  g record;
begin
  for g in
    select grouped.*
      from (
        select t.merchant_id,
               t.company_id,
               date_trunc('month',t.created_at at time zone 'Asia/Seoul')::date as period_from,
               (date_trunc('month',t.created_at at time zone 'Asia/Seoul')::date
                 + interval '1 month - 1 day')::date as period_to,
               to_char(t.created_at at time zone 'Asia/Seoul','YYYY-MM') as period_ym
          from public.meal_transactions t
          join public.merchants m on m.id=t.merchant_id and m.status='active'
          join public.companies c on c.id=t.company_id and c.status='active'
          join public.merchant_companies mc on mc.merchant_id=t.merchant_id
           and mc.company_id=t.company_id and mc.status='active'
         where t.company_id is not null
           and t.merchant_id is not null
           and t.pay_type in ('ledger','subsidized')
           and t.kind in ('spend','refund','cancel')
           and not t.is_demo
           and not (coalesce(t.flags,'{}'::jsonb) ? 'settlement_demo')
         group by t.merchant_id,t.company_id,
           date_trunc('month',t.created_at at time zone 'Asia/Seoul')::date,
           to_char(t.created_at at time zone 'Asia/Seoul','YYYY-MM')
        having count(*)=count(*) filter(where t.settlement_tax_type in ('taxable','tax_free')
             and t.settlement_supply_amount is not null
             and t.settlement_vat_amount is not null
             and t.settlement_total_amount is not null
             and t.settlement_supply_amount+t.settlement_vat_amount=t.settlement_total_amount)
           and count(distinct t.settlement_tax_type)=1
      ) grouped
     where not exists(
       select 1 from public.settlements s
        where s.merchant_id=grouped.merchant_id
          and s.company_id=grouped.company_id
          and s.period_ym=grouped.period_ym
          and not s.is_demo)
  loop
    perform pg_advisory_xact_lock(
      pg_catalog.hashtext(g.merchant_id::text),
      pg_catalog.hashtext(g.company_id::text||':'||g.period_ym));
    if not exists(select 1 from public.settlements s
      where s.merchant_id=g.merchant_id and s.company_id=g.company_id
        and s.period_ym=g.period_ym and not s.is_demo) then
      perform public.create_merchant_settlement(
        g.merchant_id,g.company_id,g.period_from,g.period_to);
    end if;
  end loop;

  -- A pre-0053 generated run may still be at stage=seeded. Link it only when
  -- its member IDs are exactly the full ordinary transaction set for the month.
  update public.generated_transaction_runs r
     set settlement_id=s.id
    from public.settlements s
   where r.settlement_id is null
     and s.merchant_id=r.merchant_id
     and s.company_id=r.company_id
     and s.period_ym=r.period_ym
     and s.period_from=r.period_from
     and s.period_to=r.period_to
     and not s.is_demo
     and s.settlement_status in ('draft','calculating','revising')
     and s.tax_invoice_status='not_requested'
     and (select array_agg(m.transaction_id order by m.transaction_id)
            from public.generated_transaction_members m where m.run_id=r.id)
         = (select array_agg(t.id order by t.id)
              from public.meal_transactions t
             where t.merchant_id=r.merchant_id and t.company_id=r.company_id
               and t.pay_type in ('ledger','subsidized')
               and t.kind in ('spend','refund','cancel')
               and not t.is_demo
               and not (coalesce(t.flags,'{}'::jsonb) ? 'settlement_demo')
               and t.created_at >= (r.period_from::timestamp at time zone 'Asia/Seoul')
               and t.created_at < ((r.period_to+1)::timestamp at time zone 'Asia/Seoul'));
end $$;

commit;
