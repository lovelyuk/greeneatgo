-- 0082: keep Popbill's rejection reason with the failed invoice.
--
-- The API now passes a sanitized "[provider code] provider message" (no secrets, at most
-- 300 chars) as p_failure_message when Popbill rejects an issue. The function already
-- stores it in tax_invoices.failure_message (left(...,300)); the only change here is that
-- the tax_invoice_issue_rejected event payload also records that message, so the history
-- keeps the reason even after a later retry overwrites the invoice row.
--
-- Replaces merchant_finalize_tax_invoice_issue from infra/migrations/0039 verbatim except
-- the line marked 0082. Signature, grants and every other branch are unchanged.

create or replace function public.merchant_finalize_tax_invoice_issue(
 p_actor_id uuid,p_merchant_id uuid,p_settlement_id uuid,p_attempt_token uuid,p_outcome text,p_failure_code text default null,p_failure_message text default null)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare s public.settlements%rowtype; inv public.tax_invoices%rowtype; v_now timestamptz:=clock_timestamp();
begin
 if not exists(select 1 from public.app_users where id=p_actor_id and merchant_id=p_merchant_id and role='merchant_admin' and status='active') then raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001'; end if;
 select * into s from public.settlements where id=p_settlement_id and merchant_id=p_merchant_id for update;
 if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
 select * into inv from public.tax_invoices where settlement_id=s.id and document_type='original' for update;
 if not found then raise exception 'POPBILL_DOCUMENT_NOT_FOUND' using errcode='P0001'; end if;
 -- A provider refresh may win the race. Only success may then complete idempotently,
 -- and only while the persisted provider fact proves issuance.
 if s.tax_invoice_status in ('issued','nts_sending','nts_accepted') and inv.popbill_status='issued' then
   if p_outcome='success' then return jsonb_build_object('settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'idempotent',true); end if;
   raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001';
 end if;
 if s.tax_invoice_status<>'issuing' then raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001'; end if;
 if inv.issue_attempt_token is null or inv.issue_attempt_token is distinct from p_attempt_token then raise exception 'ISSUE_ATTEMPT_TOKEN_MISMATCH' using errcode='P0001'; end if;
 if p_outcome='success' then
   update public.tax_invoices set popbill_status='issued',issued_by=p_actor_id,
     failure_code=null,failure_message=null,failed_at=null,reconciliation_required_at=null,issue_attempt_token=null,issue_lease_expires_at=null,updated_by=p_actor_id,updated_at=v_now where id=inv.id returning * into inv;
   update public.settlements set tax_invoice_status='issued',updated_at=v_now where id=s.id returning * into s;
   insert into public.tax_invoice_events(tax_invoice_id,event_type,payload,actor_id,occurred_at) values(inv.id,'tax_invoice_issue_succeeded',jsonb_build_object('attempt_token',p_attempt_token),p_actor_id,v_now);
 elsif p_outcome='reconciliation_required' then
   update public.tax_invoices set reconciliation_required_at=coalesce(reconciliation_required_at,v_now),updated_by=p_actor_id,updated_at=v_now where id=inv.id returning * into inv;
   insert into public.tax_invoice_events(tax_invoice_id,event_type,payload,actor_id,occurred_at) values(inv.id,'tax_invoice_reconciliation_required',jsonb_build_object('attempt_token',p_attempt_token),p_actor_id,v_now);
 elsif p_outcome='rejected' then
   update public.tax_invoices set popbill_status='failed',failure_code=left(coalesce(p_failure_code,'POPBILL_ISSUE_REJECTED'),80),
     failure_message=left(coalesce(p_failure_message,'Popbill rejected the request'),300),failed_at=v_now,reconciliation_required_at=null,
     issue_attempt_token=null,issue_lease_expires_at=null,updated_by=p_actor_id,updated_at=v_now where id=inv.id returning * into inv;
   update public.settlements set tax_invoice_status='failed',updated_at=v_now where id=s.id returning * into s;
   insert into public.tax_invoice_events(tax_invoice_id,event_type,payload,actor_id,occurred_at) values(inv.id,'tax_invoice_issue_rejected',jsonb_build_object('attempt_token',p_attempt_token,'failure_code',inv.failure_code,'failure_message',inv.failure_message) /* 0082 */,p_actor_id,v_now);
 else raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001'; end if;
 return jsonb_build_object('settlement',to_jsonb(s),'tax_invoice',public.safe_tax_invoice_json(inv),'idempotent',false);
end $$;

revoke all on function public.merchant_finalize_tax_invoice_issue(uuid,uuid,uuid,uuid,text,text,text) from public,anon,authenticated;
grant execute on function public.merchant_finalize_tax_invoice_issue(uuid,uuid,uuid,uuid,text,text,text) to service_role;
