begin;

-- 0074: banner point rewards are bounded (audit H-3 / M7).
-- A restaurant admin could create a point banner with no per-grant cap, no total
-- budget and unlimited grants, minting company wallet points that are spendable at
-- other restaurants. Same limits as services/api/app/routers/banners.py.
alter table public.banner_rewards drop constraint if exists banner_rewards_point_caps_0074;
alter table public.banner_rewards add constraint banner_rewards_point_caps_0074 check (
  reward_type <> 'point' or (
    point_amount <= 10000
    and total_budget is not null and total_budget <= 10000000
    and (grant_policy <> 'unlimited' or (per_user_limit is not null and per_user_limit <= 100))
  )
) not valid;
alter table public.banner_rewards validate constraint banner_rewards_point_caps_0074;

commit;
