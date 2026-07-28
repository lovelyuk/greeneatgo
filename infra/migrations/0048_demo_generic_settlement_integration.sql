begin;

-- During development, demo usage is intentionally eligible for the ordinary
-- merchant settlement workflow as well as the dedicated demo workflow. Keep
-- the immutable marker and customer-limit isolation; change only the generic
-- creator's transaction aggregate. Its existing-row lookup must continue to
-- select `not is_demo` so a dedicated demo settlement never gets mutated into
-- an ordinary settlement.
do $integrate_demo_generic_settlement$
declare
  ddl text;
  isolated_source constant text := 'from public.normal_meal_transactions t where';
  integrated_source constant text := 'from public.meal_transactions t where';
  source_count int;
begin
  ddl := pg_get_functiondef('public.create_merchant_settlement(uuid,uuid,date,date)'::regprocedure);

  if position(integrated_source in ddl) = 0 then
    source_count := (length(ddl)-length(replace(ddl,isolated_source,'')))/length(isolated_source);
    if source_count <> 1 then
      raise exception '0048 generic settlement source assertion failed';
    end if;
    ddl := replace(ddl,isolated_source,integrated_source);
  end if;

  if position(integrated_source in ddl) = 0
     or position('and not is_demo for update' in ddl) = 0 then
    raise exception '0048 generic settlement safety assertion failed';
  end if;

  execute ddl;
end $integrate_demo_generic_settlement$;

-- The dedicated creator was cloned before ordinary/demo settlements could
-- coexist. Make its lookup and insert explicitly demo-only so running generic
-- settlement first can never cause the demo workflow to reclassify that row.
do $harden_dedicated_demo_creator$
declare
  ddl text;
  lookup_source constant text :=
    'where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=v_period_ym for update';
  demo_lookup constant text :=
    'where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=v_period_ym and is_demo for update';
  insert_columns constant text :=
    'settlement_tax_type,status,settlement_status,tax_invoice_status,payment_status,due_date)';
  demo_insert_columns constant text :=
    'settlement_tax_type,status,settlement_status,tax_invoice_status,payment_status,due_date,is_demo)';
  insert_values constant text :=
    'v_tax_type,''draft'',''draft'',''not_requested'',''unpaid'',p_period_to+30) returning * into v_row;';
  demo_insert_values constant text :=
    'v_tax_type,''draft'',''draft'',''not_requested'',''unpaid'',p_period_to+30,true) returning * into v_row;';
begin
  ddl := pg_get_functiondef(
    'public.settlement_demo_create_merchant_settlement(uuid,uuid,date,date)'::regprocedure
  );

  if position(demo_lookup in ddl) = 0 then
    if position(lookup_source in ddl) = 0 then
      raise exception '0048 demo settlement lookup assertion failed';
    end if;
    ddl := replace(ddl,lookup_source,demo_lookup);
  end if;
  if position(demo_insert_columns in ddl) = 0 then
    if position(insert_columns in ddl) = 0 or position(insert_values in ddl) = 0 then
      raise exception '0048 demo settlement insert assertion failed';
    end if;
    ddl := replace(ddl,insert_columns,demo_insert_columns);
    ddl := replace(ddl,insert_values,demo_insert_values);
  end if;

  if position(demo_lookup in ddl) = 0
     or position(demo_insert_columns in ddl) = 0
     or position(demo_insert_values in ddl) = 0 then
    raise exception '0048 demo settlement safety assertion failed';
  end if;

  execute ddl;
end $harden_dedicated_demo_creator$;

revoke all on function public.create_merchant_settlement(uuid,uuid,date,date)
  from public,anon,authenticated;
grant execute on function public.create_merchant_settlement(uuid,uuid,date,date)
  to service_role;

notify pgrst,'reload schema';
commit;
