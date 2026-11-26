-- 0084: 종사업장번호 (branch-office number) on companies.
--
-- One business registration number can cover several branch offices, each billed
-- separately. A branch is registered as its own company row with the same
-- biz_reg_no and a four-digit sub_biz_no; the tax invoice carries it as the buyer's
-- 종사업장 식별번호. Null = head office / no branch number.
--
-- Additive: one nullable column. Safe to run before the server deploy.

alter table public.companies add column if not exists sub_biz_no text;
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'companies_sub_biz_no_check') then
    alter table public.companies add constraint companies_sub_biz_no_check
      check (sub_biz_no is null or sub_biz_no ~ '^[0-9]{4}$');
  end if;
end $$;

notify pgrst, 'reload schema';
