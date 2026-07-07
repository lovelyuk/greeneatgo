# Repositories

DB 쓰기는 Supabase `service_role`을 사용하는 repository에서만 수행한다.

## Join approval repository가 보장해야 하는 원자성

`POST /join/request`:

1. `company_invite_codes.code`를 `for update`로 조회한다.
2. active/expiry/max_uses를 재검증한다.
3. `app_users`를 `pending`으로 upsert한다.
4. `company_invite_codes.used_count`를 증가시킨다.
5. `employee_join_audit_logs(action='requested')`를 기록한다.

`POST /admin/join-requests/{id}/approve`:

1. actor가 같은 회사의 active `company_admin`인지 확인한다.
2. 대상이 같은 회사의 `pending`인지 확인한다.
3. `app_users.status='active'`, `approved_at=now()`로 변경한다.
4. `employee_join_audit_logs(action='approved')`를 기록한다.

`reject`도 동일하게 `status='rejected'`, `rejected_at=now()`, reason 필수로 기록한다.
