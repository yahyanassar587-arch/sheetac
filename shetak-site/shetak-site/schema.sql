-- ============================================================
-- shetak: قاعدة البيانات والصلاحيات (Supabase / Postgres)
-- الصق الملف كله في Supabase > SQL Editor ودوس Run مرة واحدة.
-- ============================================================

-- ---------- الحسابات ----------
create table if not exists public.profiles (
  id          uuid primary key references auth.users(id) on delete cascade,
  name        text not null default '',
  is_admin    boolean not null default false,
  created_at  timestamptz not null default now()
);

create or replace function public.is_admin()
returns boolean language sql stable security definer set search_path = public as $$
  select coalesce((select is_admin from public.profiles where id = auth.uid()), false)
$$;

create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, name)
  values (new.id, coalesce(new.raw_user_meta_data->>'name', ''))
  on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------- إعدادات المتجر (صف واحد) ----------
create table if not exists public.settings (
  id            int primary key default 1 check (id = 1),
  insta_handle  text not null default '',
  insta_name    text not null default '',
  whatsapp      text not null default '',
  min_withdraw  numeric(10,2) not null default 100
);
insert into public.settings (id) values (1) on conflict (id) do nothing;

-- ---------- الشيتات ----------
create table if not exists public.products (
  id              uuid primary key default gen_random_uuid(),
  name            text not null,
  description     text not null default '',
  price           numeric(10,2) not null check (price > 0),
  commission_pct  numeric(5,2) not null default 10 check (commission_pct between 0 and 100),
  color           text not null default 'green',
  cover_url       text,
  active          boolean not null default true,
  created_at      timestamptz not null default now()
);

-- لينك التحميل: السطر ده مايتشافش غير للأدمن، والعميل بياخده بعد قبول طلبه بس
create table if not exists public.product_secrets (
  product_id    uuid primary key references public.products(id) on delete cascade,
  download_url  text not null default ''
);

-- ---------- الطلبات ----------
create table if not exists public.orders (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null default auth.uid() references public.profiles(id) on delete cascade,
  product_id       uuid references public.products(id) on delete set null,
  product_name     text not null default '',
  price            numeric(10,2) not null default 0,
  commission_pct   numeric(5,2) not null default 0,
  ref_code         text,
  sender           text not null,
  screenshot_path  text not null,
  status           text not null default 'pending' check (status in ('pending','approved','rejected')),
  note             text,
  created_at       timestamptz not null default now(),
  decided_at       timestamptz
);
create index if not exists orders_user_idx   on public.orders (user_id, created_at desc);
create index if not exists orders_status_idx on public.orders (status, created_at desc);

-- السيرفر هو اللي بيحدد السعر والحالة، مش المتصفح
create or replace function public.orders_before_insert()
returns trigger language plpgsql security definer set search_path = public as $$
declare p public.products%rowtype;
begin
  if auth.uid() is null then raise exception 'لازم تسجّل دخول الأول'; end if;
  select * into p from public.products where id = new.product_id and active;
  if not found then raise exception 'الشيت ده مش متاح دلوقتي'; end if;
  if exists (select 1 from public.orders
             where user_id = auth.uid() and product_id = new.product_id
               and status in ('pending','approved')) then
    raise exception 'عندك طلب لنفس الشيت بالفعل';
  end if;
  new.user_id := auth.uid();
  new.product_name := p.name;
  new.price := p.price;
  new.commission_pct := p.commission_pct;
  new.status := 'pending';
  new.note := null;
  new.decided_at := null;
  if new.ref_code is not null then
    new.ref_code := upper(trim(new.ref_code));
    if not exists (select 1 from public.affiliates a
                   where a.code = new.ref_code and a.user_id <> auth.uid()) then
      new.ref_code := null;
    end if;
  end if;
  return new;
end $$;

-- ---------- المسوّقين ----------
create table if not exists public.affiliates (
  user_id     uuid primary key references public.profiles(id) on delete cascade,
  code        text not null unique,
  created_at  timestamptz not null default now()
);

drop trigger if exists orders_before_insert on public.orders;
create trigger orders_before_insert
  before insert on public.orders
  for each row execute function public.orders_before_insert();

create table if not exists public.commissions (
  id            uuid primary key default gen_random_uuid(),
  order_id      uuid not null unique references public.orders(id) on delete cascade,
  affiliate_id  uuid not null references public.profiles(id) on delete cascade,
  amount        numeric(10,2) not null,
  product_name  text not null default '',
  created_at    timestamptz not null default now()
);
create index if not exists commissions_aff_idx on public.commissions (affiliate_id, created_at desc);

create table if not exists public.withdrawals (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.profiles(id) on delete cascade,
  amount      numeric(10,2) not null check (amount > 0),
  pay_to      text not null,
  status      text not null default 'pending' check (status in ('pending','paid','rejected')),
  created_at  timestamptz not null default now(),
  decided_at  timestamptz
);
create index if not exists withdrawals_user_idx on public.withdrawals (user_id, created_at desc);

-- ---------- الصلاحيات (RLS) ----------
alter table public.profiles        enable row level security;
alter table public.settings        enable row level security;
alter table public.products        enable row level security;
alter table public.product_secrets enable row level security;
alter table public.orders          enable row level security;
alter table public.affiliates      enable row level security;
alter table public.commissions     enable row level security;
alter table public.withdrawals     enable row level security;

drop policy if exists profiles_read on public.profiles;
create policy profiles_read on public.profiles for select to authenticated
  using (id = auth.uid() or public.is_admin());
drop policy if exists profiles_update_own on public.profiles;
create policy profiles_update_own on public.profiles for update to authenticated
  using (id = auth.uid()) with check (id = auth.uid());
-- المستخدم يقدر يغيّر اسمه بس، مش صلاحية الأدمن
revoke update on public.profiles from authenticated, anon;
grant  update (name) on public.profiles to authenticated;

drop policy if exists settings_read on public.settings;
create policy settings_read on public.settings for select to anon, authenticated using (true);
drop policy if exists settings_admin on public.settings;
create policy settings_admin on public.settings for update to authenticated
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists products_read on public.products;
create policy products_read on public.products for select to anon, authenticated
  using (active or public.is_admin());
drop policy if exists products_admin on public.products;
create policy products_admin on public.products for all to authenticated
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists secrets_admin on public.product_secrets;
create policy secrets_admin on public.product_secrets for all to authenticated
  using (public.is_admin()) with check (public.is_admin());

drop policy if exists orders_read on public.orders;
create policy orders_read on public.orders for select to authenticated
  using (user_id = auth.uid() or public.is_admin());
drop policy if exists orders_insert on public.orders;
create policy orders_insert on public.orders for insert to authenticated
  with check (user_id = auth.uid());
-- مفيش update ولا delete من المتصفح خالص: القرار بيتم من الدوال تحت

drop policy if exists affiliates_read on public.affiliates;
create policy affiliates_read on public.affiliates for select to authenticated
  using (user_id = auth.uid() or public.is_admin());

drop policy if exists commissions_read on public.commissions;
create policy commissions_read on public.commissions for select to authenticated
  using (affiliate_id = auth.uid() or public.is_admin());

drop policy if exists withdrawals_read on public.withdrawals;
create policy withdrawals_read on public.withdrawals for select to authenticated
  using (user_id = auth.uid() or public.is_admin());

-- ---------- الرصيد ----------
create or replace function public._balance_of(u uuid)
returns table (earned numeric, paid numeric, pending numeric, available numeric)
language sql stable security definer set search_path = public as $$
  select e.v, w.paid, w.pend, e.v - w.paid - w.pend
  from (select coalesce(sum(amount), 0) v from public.commissions where affiliate_id = u) e,
       (select coalesce(sum(amount) filter (where status = 'paid'), 0)    paid,
               coalesce(sum(amount) filter (where status = 'pending'), 0) pend
          from public.withdrawals where user_id = u) w
$$;

create or replace function public.my_balance()
returns table (earned numeric, paid numeric, pending numeric, available numeric)
language sql stable security definer set search_path = public as $$
  select * from public._balance_of(auth.uid())
$$;

-- ---------- لينكات التحميل (للطلبات المقبولة بس) ----------
create or replace function public.my_downloads()
returns table (order_id uuid, url text)
language sql stable security definer set search_path = public as $$
  select o.id, s.download_url
  from public.orders o
  join public.product_secrets s on s.product_id = o.product_id
  where o.user_id = auth.uid() and o.status = 'approved' and s.download_url <> ''
$$;

-- ---------- المسوّق ----------
create or replace function public.join_affiliate()
returns text language plpgsql security definer set search_path = public as $$
declare
  c text; i int; tries int := 0;
  chars text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
begin
  if auth.uid() is null then raise exception 'لازم تسجّل دخول الأول'; end if;
  select code into c from public.affiliates where user_id = auth.uid();
  if found then return c; end if;
  loop
    c := '';
    for i in 1..6 loop
      c := c || substr(chars, 1 + floor(random() * length(chars))::int, 1);
    end loop;
    begin
      insert into public.affiliates (user_id, code) values (auth.uid(), c);
      return c;
    exception when unique_violation then
      tries := tries + 1;
      if tries > 20 then raise; end if;
    end;
  end loop;
end $$;

create or replace function public.request_withdrawal(p_amount numeric, p_to text)
returns uuid language plpgsql security definer set search_path = public as $$
declare mn numeric; av numeric; wid uuid;
begin
  if auth.uid() is null then raise exception 'لازم تسجّل دخول الأول'; end if;
  perform 1 from public.affiliates where user_id = auth.uid() for update;
  if not found then raise exception 'سجّل كمسوّق الأول'; end if;
  select min_withdraw into mn from public.settings where id = 1;
  select available into av from public._balance_of(auth.uid());
  if coalesce(trim(p_to), '') = '' then raise exception 'اكتب حسابك أو رقمك'; end if;
  if p_amount is null or p_amount < mn then raise exception 'الحد الأدنى للسحب % ج.م', mn; end if;
  if p_amount > av then raise exception 'المبلغ أكبر من رصيدك المتاح'; end if;
  insert into public.withdrawals (user_id, amount, pay_to)
  values (auth.uid(), p_amount, trim(p_to)) returning id into wid;
  return wid;
end $$;

-- ---------- قرارات الأدمن ----------
create or replace function public.approve_order(p_order uuid)
returns void language plpgsql security definer set search_path = public as $$
declare o public.orders%rowtype; url text; aff public.affiliates%rowtype;
begin
  if not public.is_admin() then raise exception 'مش مسموح'; end if;
  select * into o from public.orders where id = p_order for update;
  if not found then raise exception 'الطلب مش موجود'; end if;
  if o.status <> 'pending' then raise exception 'الطلب ده اتقرر فيه قبل كده'; end if;
  select download_url into url from public.product_secrets where product_id = o.product_id;
  if coalesce(url, '') = '' then raise exception 'ضيف لينك تحميل الشيت الأول'; end if;
  update public.orders set status = 'approved', decided_at = now(), note = null where id = p_order;
  if o.ref_code is not null and o.commission_pct > 0 then
    select * into aff from public.affiliates where code = o.ref_code;
    if found and aff.user_id <> o.user_id then
      insert into public.commissions (order_id, affiliate_id, amount, product_name)
      values (o.id, aff.user_id, round(o.price * o.commission_pct / 100, 2), o.product_name)
      on conflict (order_id) do nothing;
    end if;
  end if;
end $$;

create or replace function public.reject_order(p_order uuid, p_note text default null)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'مش مسموح'; end if;
  update public.orders
     set status = 'rejected', decided_at = now(), note = nullif(trim(coalesce(p_note, '')), '')
   where id = p_order and status = 'pending';
  if not found then raise exception 'الطلب مش موجود أو اتقرر فيه قبل كده'; end if;
end $$;

create or replace function public.decide_withdrawal(p_id uuid, p_status text)
returns void language plpgsql security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'مش مسموح'; end if;
  if p_status not in ('paid', 'rejected') then raise exception 'حالة غير صحيحة'; end if;
  update public.withdrawals set status = p_status, decided_at = now()
   where id = p_id and status = 'pending';
  if not found then raise exception 'الطلب مش موجود أو اتقرر فيه قبل كده'; end if;
end $$;

create or replace function public.admin_affiliates()
returns table (user_id uuid, name text, code text, sales bigint, earned numeric, paid numeric, pending numeric, available numeric)
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'مش مسموح'; end if;
  return query
    select a.user_id, p.name, a.code,
           (select count(*) from public.commissions c where c.affiliate_id = a.user_id),
           b.earned, b.paid, b.pending, b.available
    from public.affiliates a
    join public.profiles p on p.id = a.user_id
    cross join lateral public._balance_of(a.user_id) b
    order by b.earned desc, a.created_at;
end $$;

create or replace function public.admin_overview()
returns table (sales_total numeric, sales_count bigint, waiting_orders bigint, waiting_withdrawals bigint, affiliates_count bigint, owed numeric)
language plpgsql stable security definer set search_path = public as $$
begin
  if not public.is_admin() then raise exception 'مش مسموح'; end if;
  return query select
    coalesce((select sum(price) from public.orders where status = 'approved'), 0),
    (select count(*) from public.orders where status = 'approved'),
    (select count(*) from public.orders where status = 'pending'),
    (select count(*) from public.withdrawals where status = 'pending'),
    (select count(*) from public.affiliates),
    coalesce((select sum(amount) from public.commissions), 0)
      - coalesce((select sum(amount) from public.withdrawals where status = 'paid'), 0);
end $$;

-- الدوال متاحة للمسجّلين بس
revoke all on function public._balance_of(uuid)              from public, anon, authenticated;
revoke all on function public.handle_new_user()              from public, anon, authenticated;
revoke all on function public.orders_before_insert()         from public, anon, authenticated;
revoke all on function public.my_balance()                   from public, anon;
revoke all on function public.my_downloads()                 from public, anon;
revoke all on function public.join_affiliate()               from public, anon;
revoke all on function public.request_withdrawal(numeric, text) from public, anon;
revoke all on function public.approve_order(uuid)            from public, anon;
revoke all on function public.reject_order(uuid, text)       from public, anon;
revoke all on function public.decide_withdrawal(uuid, text)  from public, anon;
revoke all on function public.admin_affiliates()             from public, anon;
revoke all on function public.admin_overview()               from public, anon;
grant execute on function public.my_balance()                   to authenticated;
grant execute on function public.my_downloads()                 to authenticated;
grant execute on function public.join_affiliate()               to authenticated;
grant execute on function public.request_withdrawal(numeric, text) to authenticated;
grant execute on function public.approve_order(uuid)            to authenticated;
grant execute on function public.reject_order(uuid, text)       to authenticated;
grant execute on function public.decide_withdrawal(uuid, text)  to authenticated;
grant execute on function public.admin_affiliates()             to authenticated;
grant execute on function public.admin_overview()               to authenticated;
grant execute on function public.is_admin()                     to anon, authenticated;

-- ---------- تخزين الصور ----------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('screenshots', 'screenshots', false, 5242880, array['image/jpeg','image/png','image/webp'])
on conflict (id) do nothing;
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('covers', 'covers', true, 5242880, array['image/jpeg','image/png','image/webp'])
on conflict (id) do nothing;

drop policy if exists shots_insert on storage.objects;
create policy shots_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'screenshots' and (storage.foldername(name))[1] = auth.uid()::text);
drop policy if exists shots_read on storage.objects;
create policy shots_read on storage.objects for select to authenticated
  using (bucket_id = 'screenshots' and ((storage.foldername(name))[1] = auth.uid()::text or public.is_admin()));
drop policy if exists covers_insert on storage.objects;
create policy covers_insert on storage.objects for insert to authenticated
  with check (bucket_id = 'covers' and public.is_admin());
drop policy if exists covers_update on storage.objects;
create policy covers_update on storage.objects for update to authenticated
  using (bucket_id = 'covers' and public.is_admin());
drop policy if exists covers_delete on storage.objects;
create policy covers_delete on storage.objects for delete to authenticated
  using (bucket_id = 'covers' and public.is_admin());
