-- Normalize the buffet label and keep only today/future menu schedules.
alter table merchant_daily_menus
  alter column title set default '오늘 뷔페 메뉴';

update merchant_daily_menus
set title = replace(title, '부' || '페', '뷔페'), updated_at = now()
where title like '%' || '부' || '페' || '%';

update merchant_daily_menus
set title = '오늘 뷔페 메뉴', updated_at = now()
where title = '오늘의 뷔페 메뉴';

delete from merchant_daily_menus
where service_date < (now() at time zone 'Asia/Seoul')::date;