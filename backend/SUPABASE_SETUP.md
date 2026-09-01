# Supabase Activation Setup

This backend now validates license keys against a Supabase project.

## 1. Create a Supabase project

1. Go to [supabase.com](https://supabase.com) and create a project.
2. Once ready, open **Project Settings > API**.
3. Copy:
   - **Project URL** → `SUPABASE_URL`
   - **service_role secret** → `SUPABASE_SERVICE_KEY`

## 2. Create the tables

Open the Supabase **SQL Editor** and run:

```sql
-- License keys table
CREATE TABLE licenses (
  key TEXT PRIMARY KEY,
  is_active BOOLEAN DEFAULT TRUE,
  expires_at TIMESTAMPTZ,
  max_activations INT DEFAULT 1,
  activation_count INT DEFAULT 0,
  owner_email TEXT,
  backend_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Per-machine activations
CREATE TABLE license_activations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  license_key TEXT REFERENCES licenses(key) ON DELETE CASCADE,
  machine_id TEXT NOT NULL,
  activated_at TIMESTAMPTZ DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ DEFAULT NOW(),
  ip_address TEXT,
  UNIQUE (license_key, machine_id)
);

-- Disable public access; only the backend service key will read/write
ALTER TABLE licenses ENABLE ROW LEVEL SECURITY;
ALTER TABLE license_activations ENABLE ROW LEVEL SECURITY;

-- No anon access policies (service key bypasses RLS)
```

## 3. Insert a license key

Your own box (the gateway VPS) — leave `backend_url` empty so the dashboard
handles it locally:

```sql
INSERT INTO licenses (key, is_active, max_activations, owner_email)
VALUES ('MOJALEFA-5336', TRUE, 1, 'you@example.com');
```

A second customer on their own VPS — they still open
https://www.ar-investech.uk/ and type only their key. Set `backend_url` to
that VPS's reachable API (usually `http://THEIR_PUBLIC_IP:8000`). No second
Cloudflare hostname is required; the gateway VPS proxies to this URL.

```sql
INSERT INTO licenses (key, is_active, max_activations, owner_email, backend_url)
VALUES ('MOJALEFA-XXXX', TRUE, 1, 'customer@example.com', 'http://THEIR_PUBLIC_IP:8000');
```

If the `licenses` table already exists without `backend_url`:

```sql
ALTER TABLE licenses ADD COLUMN IF NOT EXISTS backend_url TEXT;
```

## 4. Configure the backend

Add the credentials to `backend/.env`:

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
```

If the placeholders are already there, just fill them in.

## 5. Install the dependency

```bash
pip install "supabase>=2.0,<3.0"
```

Already added to `backend/requirements.txt`.

## 6. Test

1. Start the backend: `python server.py`
2. Open https://www.ar-investech.uk/ (or `http://localhost:3000` in dev).
3. Enter a license key from Supabase.
4. Press **Activate**.
5. Check that a row appears in `license_activations` on **that key's** VPS
   (the gateway VPS if `backend_url` is empty; the customer's VPS otherwise).

## Notes

- `SUPABASE_SERVICE_KEY` is secret. Never expose it in frontend code or Git.
- MT5 passwords are still stored only in `backend/.env`, not in Supabase.
- If Supabase credentials are missing, the backend falls back to the original local-only validation.
- `backend_url` is only read by the gateway VPS. Customers never type it.
