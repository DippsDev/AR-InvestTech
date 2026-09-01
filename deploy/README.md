# VPS Deployment Runbook

Getting the bot running unattended on a Windows VPS, so the dashboard works
with your laptop closed.

Do these in order — several steps genuinely depend on the previous one.
Budget about two hours for the first run, most of it waiting on installers.

---

## The one constraint that shapes everything

MetaTrader 5 is a **GUI application**. The Python SDK drives it over a Windows
named pipe, and the terminal only exists inside an interactive desktop
session. Three consequences that surprise people:

- You **cannot** run MT5 as a Windows service, and a service running as
  `LocalSystem` in session 0 generally cannot reach a terminal in session 1.
- The VPS must therefore **auto-logon to a desktop at boot**, or a reboot
  leaves it at the lock screen with nothing trading.
- After connecting over RDP, always **disconnect** (close the window).
  Choosing **"Sign out" destroys the session and kills MT5.** This is the most
  common way a VPS-hosted bot silently dies.

---

## Step 1 — Provision and harden the box

Windows Server 2022, 8 GB RAM, 4 vCPU, London region (closest to Exness).

Before anything else:

- [ ] Change the default Administrator password
- [ ] Create a **dedicated non-admin user** to run the bot — auto-logon stores
      this account's password in plaintext, so it must not be an account you
      use elsewhere
- [ ] Restrict RDP (3389) in the provider's firewall to your own IP if you have
      a static one. An open RDP port is scanned within minutes of going live.
- [ ] Windows Update → install everything → reboot → set active hours so it
      never reboots during a session window

## Step 2 — Install the runtime

Install **Python 3.11+** from python.org, ticking **"Add python.exe to PATH"**.

Get the code onto the box (`git clone`, or copy the folder — exclude `.venv`
and `node_modules`), then from the repo root in an elevated PowerShell:

```powershell
.\deploy\setup_vps.ps1
```

This creates the venv, installs `backend/requirements.txt`, verifies the
MetaTrader5 wheel imports, installs `cloudflared`, and writes a `.env` with a
freshly generated `API_TOKEN`. It never overwrites an existing `.env`.

## Step 3 — Install and configure MT5

Download the terminal from Exness (broker-specific build) and log in.

Then, in the terminal:

- [ ] **Tools → Options → Expert Advisors → "Allow algorithmic trading"** ✔
- [ ] The **AutoTrading** toolbar button is pressed and **green**
- [ ] Save the password so it reconnects on restart
- [ ] **Tools → Options → Charts →** reduce "Max bars in chart" to ~5,000
- [ ] Close every chart you don't need, and remove unused symbols from Market
      Watch. Each chart costs RAM, and RAM is what caps your customer count.

Fill in `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` in `backend\.env`.

Sanity check the pipe works at all:

```powershell
.\.venv\Scripts\python.exe backend\debug_mt5.py
```

## Step 4 — Prove it trades, manually

Before automating anything, run the bot by hand and watch it:

```powershell
cd backend
..\.venv\Scripts\python.exe server.py
```

From another shell on the VPS:

```powershell
curl.exe -H "X-API-Token: <your token>" http://127.0.0.1:8000/stats
```

Do not proceed until this returns real balance and symbol data. Debugging a
broken pipe is far harder once a tunnel and scheduled tasks are layered on top.

## Step 5 — Named Cloudflare tunnel

You need a **fixed** hostname. The quick tunnel in `backend/start_tunnel.py`
mints a new random URL on every restart, and the dashboard pins its backend
URL in browser localStorage — so every restart would break every user.

Requires a domain with its nameservers pointed at Cloudflare (free plan is
fine).

```powershell
cloudflared tunnel login
cloudflared tunnel create ar-invest
cloudflared tunnel route dns ar-invest bot.yourdomain.com
```

Note the tunnel UUID it prints, then create
`C:\Users\<user>\.cloudflared\config.yml`:

```yaml
tunnel: <UUID>
credentials-file: C:\Users\<user>\.cloudflared\<UUID>.json

ingress:
  - hostname: bot.yourdomain.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Install it as a service so it survives reboots — this one *can* be a service,
because unlike MT5 it needs no desktop session:

```powershell
cloudflared service install
Start-Service cloudflared
```

Verify from your laptop: `https://bot.yourdomain.com/health` should return
JSON.

## Step 6 — Autostart

```powershell
.\deploy\install_autostart.ps1 -EnableAutoLogon
```

Registers two logon-triggered scheduled tasks — MT5 at +30s, the backend at
+2min (the delay matters: `resume_on_startup()` connects to MT5 immediately and
fails if the terminal is still logging in). Read the plaintext-password
warning in the script before using `-EnableAutoLogon`.

## Step 7 — Verify end to end

```powershell
.\.venv\Scripts\python.exe deploy\verify_vps.py --tunnel https://bot.yourdomain.com
```

Checks the API token is actually *enforced* (not just configured), that
AutoTrading is on, that all nine symbols in `multi_symbol_targets.py` resolve
and tick, that the run-state file is writable, and that the tunnel is live.
It places no trades.

**Then reboot the VPS and run it again.** This is the step that actually
proves the thing you're paying for — if it passes with nobody logged in, your
laptop is genuinely out of the loop.

## Step 8 — Point the dashboard at it

On the Vercel dashboard's Activation screen:

- **Backend URL** — `https://bot.yourdomain.com`
- **API Token** — the `API_TOKEN` from `backend\.env`
- **License Key** — as normal

Press **Trade**. Close your laptop. Check the dashboard from your phone in an
hour: the bot should still be running, with fresh log entries.

## Step 9 — Soak test before real money

Leave it on **demo for at least one full trading week**, and confirm:

- [ ] It survives an unattended reboot (schedule one deliberately)
- [ ] Trades appear during session windows
- [ ] `backend\logs\trades.log` has no repeating errors
- [ ] Memory is stable in Task Manager (a slow climb means a leak that will
      bite in month two)

Only then switch `MT5_SERVER` to the live server.

---

## Adding a second customer (same website, own VPS)

Customers only ever open https://www.ar-investech.uk/ and type a license key.
Do **not** create a second Cloudflare hostname. Their bot runs on a second
Windows VPS; your existing tunnelled box is the gateway.

1. Provision their VPS the same way as this runbook (MT5 logged into **their**
   account, `setup_vps.ps1`, autostart). On that box set `AR_BIND_HOST=0.0.0.0`
   in `.env` so your gateway can reach port 8000.
2. Firewall their port 8000 to **your gateway VPS public IP only**. Anyone
   else hitting that port would be talking to a live trading API.
3. Insert their key in Supabase with `backend_url` pointing at their VPS
   (`http://THEIR_PUBLIC_IP:8000`). Leave your own license's `backend_url`
   empty. See `backend/SUPABASE_SETUP.md`.
4. Redeploy the dashboard (Vercel) so `/bot-api` rewrites stay on
   www.ar-investech.uk, and restart **your** gateway backend so it picks up
   `httpx` / the new proxy.
5. They activate with their key on https://www.ar-investech.uk/. First request
   hits your gateway, which proxies to their VPS; their machine records the
   activation.

They never see `bot.ar-investech.uk` or their VPS IP.

---

## Operational notes

**Watch out for:**

| Symptom | Cause |
|---|---|
| Bot "running" but never trades | AutoTrading button off — `verify_vps.py` catches this |
| Everything dies after you leave | You signed out of RDP instead of disconnecting |
| Dashboard 401s | Token mismatch between `.env` and the Activation screen |
| Dead after reboot | Auto-logon not configured, or MT5 didn't save its password |
| IPC timeout in logs | MT5 wasn't up before the backend started — increase the task delay |

**Saving settings closes open positions.** `POST /settings` triggers a bot
restart, and the shutdown path closes every open position and cancels pending
orders (`live_adapter.shutdown`). The dashboard now warns in the activity feed,
but avoid changing settings mid-trade.

**What survives what:**

| Event | Recovery |
|---|---|
| Bot thread crashes | Supervisor restarts it within 30s, backing off 30s→300s |
| MT5 disconnects | Reconnected in place — deliberately *not* a bot restart, which would close positions |
| Backend crashes | Scheduled task restarts it, up to 5x |
| VPS reboots | Auto-logon → MT5 → backend → `resume_on_startup()` reads `bot_state.json` and resumes if it was trading |
| Cloudflare tunnel drops | `cloudflared` service auto-restarts |

**Backups.** `backend\.env` (credentials), `backend\.license`, and
`bot_tickets.json` (ticket history that trade attribution depends on when the
broker zeroes `magic`). Keep `.env` somewhere off the VPS — losing the box
means re-entering everything.
