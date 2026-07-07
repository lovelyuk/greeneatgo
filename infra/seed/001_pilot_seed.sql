-- Pilot seed draft: company 1, groups 2, merchants 5.
-- Auth users are not inserted here because Supabase auth.users must be created through Auth/admin tooling.
insert into companies (id, name, biz_reg_no) values
('00000000-0000-0000-0000-000000000001', '파일럿 주식회사', '123-45-67890')
on conflict (id) do nothing;

insert into employee_groups (id, company_id, name) values
('10000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000001', '개발팀'),
('10000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', '운영팀')
on conflict (company_id, name) do nothing;

insert into meal_policies (company_id, group_id, daily_limit, monthly_grant, weekend_allowed, carry_over) values
('00000000-0000-0000-0000-000000000001', null, 22000, 200000, false, false);

insert into merchants (id, name, owner_phone, bank_account, address, lat, lng, category, avg_price, qr_token, view_token) values
('20000000-0000-0000-0000-000000000001', '밥장부 김치찌개', '010-0000-0001', '{"bank":"국민","number":"000001-01-000001","holder":"김치찌개"}', '서울 중구 세종대로 1', 37.5665, 126.9780, '한식', 9000, 'QR-PILOT-KIMCHI', 'VIEW-PILOT-KIMCHI'),
('20000000-0000-0000-0000-000000000002', '든든분식', '010-0000-0002', '{"bank":"신한","number":"000-000-000002","holder":"든든분식"}', '서울 중구 세종대로 2', 37.5670, 126.9785, '분식', 8000, 'QR-PILOT-BUNSIK', 'VIEW-PILOT-BUNSIK'),
('20000000-0000-0000-0000-000000000003', '점심중화', '010-0000-0003', '{"bank":"우리","number":"1000-000-000003","holder":"점심중화"}', '서울 중구 세종대로 3', 37.5675, 126.9790, '중식', 9500, 'QR-PILOT-CHINA', 'VIEW-PILOT-CHINA'),
('20000000-0000-0000-0000-000000000004', '샐러드회사', '010-0000-0004', '{"bank":"하나","number":"000-910004-00004","holder":"샐러드회사"}', '서울 중구 세종대로 4', 37.5680, 126.9795, '샐러드', 11000, 'QR-PILOT-SALAD', 'VIEW-PILOT-SALAD'),
('20000000-0000-0000-0000-000000000005', '저녁국밥', '010-0000-0005', '{"bank":"기업","number":"000-000005-01-000","holder":"저녁국밥"}', '서울 중구 세종대로 5', 37.5685, 126.9800, '한식', 10000, 'QR-PILOT-GUKBAP', 'VIEW-PILOT-GUKBAP')
on conflict (id) do nothing;

insert into company_merchants (company_id, merchant_id)
select '00000000-0000-0000-0000-000000000001', id from merchants where qr_token like 'QR-PILOT-%'
on conflict do nothing;
