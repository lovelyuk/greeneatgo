-- Non-destructive operational rollback: disable the review producer only.
-- Keeps all evidence, closures, wallet releases, checkout guards and callbacks.
-- Do NOT restore an old checkout implementation while payable entry is enabled.
begin;
revoke execute on function public.review_failed_payment_order(uuid,uuid,jsonb,text,text,boolean) from service_role;
notify pgrst,'reload schema';
commit;
-- Resume only after review: GRANT EXECUTE ON FUNCTION
-- public.review_failed_payment_order(uuid,uuid,jsonb,text,text,boolean) TO service_role;
