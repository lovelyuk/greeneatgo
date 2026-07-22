-- Firebase/Supabase dual-auth migration.
-- Remove only the two known public-column foreign keys to auth.users. Constraint
-- names are discovered from the catalog so generated or manually renamed FKs
-- are handled without broad-dropping future auth.users relationships.
do $$
declare
  auth_fk record;
begin
  for auth_fk in
    select source_ns.nspname as table_schema,
           source_table.relname as table_name,
           con.conname
      from pg_constraint con
      join pg_class source_table on source_table.oid = con.conrelid
      join pg_namespace source_ns on source_ns.oid = source_table.relnamespace
      join pg_attribute source_column
        on source_column.attrelid = source_table.oid
       and source_column.attnum = con.conkey[1]
     where source_ns.nspname = 'public'
       and con.contype = 'f'
       and con.confrelid = to_regclass('auth.users')
       and cardinality(con.conkey) = 1
       and (
         (source_table.relname = 'app_users' and source_column.attname = 'id')
         or
         (source_table.relname = 'employee_bulk_invites' and source_column.attname = 'claimed_by')
       )
  loop
    execute format(
      'alter table %I.%I drop constraint %I',
      auth_fk.table_schema,
      auth_fk.table_name,
      auth_fk.conname
    );
  end loop;
end
$$;

-- claimed_by now references the provider-neutral application identity. This is
-- catalog-checked for idempotency and does not depend on a constraint name.
-- ON DELETE SET NULL is incompatible with the existing active-row check, which
-- requires active invites to retain claimed_by, so the default NO ACTION applies.
do $$
begin
  if not exists (
    select 1
      from pg_constraint con
      join pg_class source_table on source_table.oid = con.conrelid
      join pg_namespace source_ns on source_ns.oid = source_table.relnamespace
      join pg_attribute source_column
        on source_column.attrelid = source_table.oid
       and source_column.attnum = con.conkey[1]
      join pg_class referenced_table on referenced_table.oid = con.confrelid
      join pg_namespace referenced_ns on referenced_ns.oid = referenced_table.relnamespace
      join pg_attribute referenced_column
        on referenced_column.attrelid = referenced_table.oid
       and referenced_column.attnum = con.confkey[1]
     where con.contype = 'f'
       and source_ns.nspname = 'public'
       and source_table.relname = 'employee_bulk_invites'
       and source_column.attname = 'claimed_by'
       and cardinality(con.conkey) = 1
       and con.confrelid = to_regclass('public.app_users')
       and referenced_ns.nspname = 'public'
       and referenced_table.relname = 'app_users'
       and referenced_column.attname = 'id'
       and cardinality(con.confkey) = 1
  ) then
    alter table public.employee_bulk_invites
      add constraint employee_bulk_invites_claimed_by_app_user_fk
      foreign key (claimed_by) references public.app_users(id);
  end if;
end
$$;
