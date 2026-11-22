-- شغّل الملف ده كله مرة واحدة في Supabase: SQL Editor ← New query ← Run
-- (غيّر 7 في سطر التجربة المجانية لو عايز مدة تانية)

create table if not exists public.cafe_data (
  user_id uuid primary key references auth.users(id) on delete cascade,
  data jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

create table if not exists public.subscriptions (
  user_id uuid primary key references auth.users(id) on delete cascade,
  status text not null default 'inactive',      -- active | trialing | inactive | canceled
  current_period_end timestamptz,               -- تاريخ انتهاء الشهر المدفوع
  provider text,
  provider_ref text,
  updated_at timestamptz not null default now()
);

-- هل المستخدم عنده صلاحية؟ (تجربة مجانية 7 أيام من تاريخ التسجيل أو اشتراك ساري)
create or replace function public.has_access(uid uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select coalesce((select u.created_at + interval '7 days' > now() from auth.users u where u.id = uid), false)
      or exists (select 1 from public.subscriptions s
                 where s.user_id = uid and s.status in ('active','trialing')
                   and (s.current_period_end is null or s.current_period_end > now()));
$$;

-- التطبيق بيسأل بيها عن حالة المستخدم الحالي
create or replace function public.my_access()
returns jsonb language plpgsql stable security definer set search_path = public as $$
declare
  uid uuid := auth.uid();
  created timestamptz;
  trial_end timestamptz;
  s public.subscriptions%rowtype;
begin
  if uid is null then return jsonb_build_object('access', false); end if;
  select created_at into created from auth.users where id = uid;
  trial_end := created + interval '7 days';
  select * into s from public.subscriptions where user_id = uid;
  return jsonb_build_object(
    'access', public.has_access(uid),
    'trial_ends', trial_end,
    'sub_status', s.status,
    'period_end', s.current_period_end
  );
end $$;

grant execute on function public.my_access() to authenticated;

alter table public.cafe_data enable row level security;
alter table public.subscriptions enable row level security;

drop policy if exists "cafe_select_own" on public.cafe_data;
drop policy if exists "cafe_insert_own" on public.cafe_data;
drop policy if exists "cafe_update_own" on public.cafe_data;
drop policy if exists "sub_select_own"  on public.subscriptions;

-- القراءة متاحة لصاحب الحساب دايماً (عشان يصدّر بياناته)
create policy "cafe_select_own" on public.cafe_data for select using (auth.uid() = user_id);
-- الكتابة مش مسموحة إلا لو التجربة أو الاشتراك ساريين (الحماية من السيرفر نفسه)
create policy "cafe_insert_own" on public.cafe_data for insert
  with check (auth.uid() = user_id and public.has_access(auth.uid()));
create policy "cafe_update_own" on public.cafe_data for update
  using (auth.uid() = user_id and public.has_access(auth.uid()))
  with check (auth.uid() = user_id and public.has_access(auth.uid()));
-- الاشتراكات: المستخدم يقرأ بس. الكتابة بتتم من لوحة Supabase أو من webhook الدفع (service role).
create policy "sub_select_own" on public.subscriptions for select using (auth.uid() = user_id);
