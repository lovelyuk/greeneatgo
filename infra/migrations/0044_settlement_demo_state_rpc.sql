begin;

-- PostgREST runs STABLE RPCs in a read-only transaction. This state function
-- performs lock-aware integrity checks through settlement_demo_validate_run,
-- so it must be VOLATILE even though it does not intentionally mutate data.
alter function public.settlement_demo_state(uuid, uuid) volatile;

notify pgrst, 'reload schema';

commit;
