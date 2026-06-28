insert into public.app_users (
  email,
  username,
  password_hash,
  name,
  role,
  is_active,
  updated_at
)
values (
  'allan@brain.com',
  'allan',
  'pbkdf2_sha256$390000$00C1-TpasbI8vONo7BiZ3g$nfX8KPP59k6PPcaPGg5li9vtJds68jabJXWyG-jnxNI',
  'Allan Brain Admin',
  'admin',
  true,
  now()
)
on conflict (email) do update set
  username = excluded.username,
  password_hash = excluded.password_hash,
  name = excluded.name,
  role = excluded.role,
  is_active = excluded.is_active,
  updated_at = now();
