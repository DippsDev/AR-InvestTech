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

```sql
INSERT INTO licenses (key, is_active, max_activations, owner_email)
VALUES ('ARB-ABCD-1234-EFGH', TRUE, 2, 'user@example.com');
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
2. Open the frontend activation screen.
3. Enter the backend URL and a license key from Supabase.
4. Press **Activate**.
5. Check that a row appears in `license_activations`.

## Notes

- `SUPABASE_SERVICE_KEY` is secret. Never expose it in frontend code or Git.
- MT5 passwords are still stored only in `backend/.env`, not in Supabase.
- If Supabase credentials are missing, the backend falls back to the original local-only validation.
