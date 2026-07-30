"""
FastAPI REST backend for the AR-InvestTech Next.js frontend.
Run with:  python server.py
Frontend:  cd frontend && npm run dev

Every route is guarded by the X-API-Token header whenever config.API_TOKEN is
set (see `_require_token`). These endpoints can start and stop live trading,
read the MT5 login, and overwrite the MT5 password, so the token is mandatory
for any deployment reachable from outside the machine.
"""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from bridge import BotBridge

# Reachable without a token: the supervisor and the tunnel's health check
# need to know the process is alive before they have any credentials, and
# neither response reveals anything sensitive.
_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

# Reachable without credentials ONLY while this machine has no activated
# license. See _require_token for why that condition is load-bearing.
_BOOTSTRAP_PATHS = {"/license/validate"}


def _require_token(request: Request, x_api_token: str | None = Header(default=None)) -> None:
    """Reject any request that doesn't carry an accepted credential.

    Registered as an app-wide dependency rather than per-route so a newly
    added endpoint is protected by default — forgetting to decorate a route
    here would expose live trading controls, so the safe direction is
    opt-out, not opt-in.

    Two credentials are accepted, either of which is sufficient:

      1. config.API_TOKEN — the shared secret from .env.
      2. The activated license key — the value the operator already types on
         the Activation screen. Accepting it means a single-user install needs
         no second secret pasted out of .env, which is the whole point; the
         key is ARB- plus 12 alphanumerics, so it is not meaningfully weaker
         than the token it stands in for.

    The bootstrap exemption is deliberately conditional on NO license being
    stored yet. Making /license/validate unconditionally public would be a
    privilege-escalation hole: anyone holding any valid license key could POST
    it to an already-activated backend, overwrite the stored key, and thereby
    mint themselves a credential that passes this very check. Once a key is
    stored, changing it requires already holding a valid credential.
    """
    if not config.API_TOKEN:
        return  # not configured — local-only mode, see config.API_TOKEN

    path = request.url.path
    if path in _PUBLIC_PATHS:
        return

    license_key = bridge.activated_license_key()

    # First run: there is no credential the operator could possibly send yet.
    # /license/validate authenticates its own input against Supabase, so an
    # invalid key is still rejected there — this only lets the request reach it.
    if path in _BOOTSTRAP_PATHS and not license_key:
        return

    # Constant-time compare: a plain == leaks the secret's prefix through
    # response timing to anyone who can call this endpoint in a loop.
    if x_api_token:
        if secrets.compare_digest(x_api_token, config.API_TOKEN):
            return
        if license_key and secrets.compare_digest(x_api_token, license_key):
            return

    raise HTTPException(status_code=401, detail="Invalid or missing API token.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Bring the machine back to its intended state on process start.

    Without this, a VPS reboot or a service restart leaves the bot stopped
    and MT5 disconnected until somebody happens to open the dashboard and
    press the buttons again — which defeats the point of hosting it off the
    laptop in the first place.
    """
    bridge.resume_on_startup()
    try:
        yield
    finally:
        bridge.shutdown()


app = FastAPI(title="AR-InvestTech API", lifespan=lifespan, dependencies=[Depends(_require_token)])

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

bridge = BotBridge()


# ── Health ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Unauthenticated liveness probe for the supervisor and tunnel."""
    return {"ok": True, "running": bridge._is_running(), "mt5": bridge._mt5_ok}


# ── License ────────────────────────────────────────────────────────────

@app.get("/license")
def check_license():
    return bridge.check_license()


class LicenseBody(BaseModel):
    key: str

@app.post("/license/validate")
def validate_license(body: LicenseBody):
    return bridge.validate_license(body.key)


# ── MT5 ────────────────────────────────────────────────────────────────

@app.post("/mt5/connect")
def connect_mt5():
    return bridge.connect_mt5()


# ── Bot ────────────────────────────────────────────────────────────────

@app.post("/bot/start")
def start_bot():
    if bridge._is_running():
        return {"running": True}
    bridge._start_bot()
    return {"running": True}


@app.post("/bot/stop")
def stop_bot():
    if not bridge._bot_running:
        bridge.set_desired_running(False)
        return {"running": False}
    bridge._stop_bot()
    return {"running": False}


@app.post("/bot/restart")
def restart_bot():
    bridge._restart_bot()
    return {"running": bridge._is_running()}


# ── Live data ──────────────────────────────────────────────────────────

@app.get("/stats")
def get_stats():
    return bridge.get_stats()


@app.get("/log")
def get_log():
    return bridge.get_log()


@app.get("/trades")
def get_trades():
    return bridge.get_trades()


@app.get("/calendar")
def get_calendar():
    return bridge.get_calendar()


@app.get("/market")
def get_market():
    return bridge.get_market_snapshot()


# ── Settings ───────────────────────────────────────────────────────────

@app.get("/settings")
def get_settings():
    return bridge.get_settings()


class SettingsBody(BaseModel):
    login: str = ""
    server: str = ""
    risk_pct: str = "1.0"
    daily_loss_limit_usd: str = "3.0"
    max_trades_per_day: str = "2"
    max_drawdown_pct: str = "50.0"
    aggressive: bool = False
    off_hours:  bool = False
    news:       bool = True
    password:   str = ""  # write-only: blank means "leave the current password alone"

@app.post("/settings")
def save_settings(body: SettingsBody):
    return bridge.save_settings(body.model_dump())


if __name__ == "__main__":
    if not config.API_TOKEN and config.BIND_HOST != "127.0.0.1":
        # Binding beyond loopback with no token hands anyone who can reach
        # the port full control of a live trading account.
        raise SystemExit(
            f"Refusing to bind {config.BIND_HOST} with no API_TOKEN set.\n"
            "Set API_TOKEN in .env, or bind 127.0.0.1 and front it with a tunnel."
        )
    # reload=False deliberately: the reloader restarts the process on any file
    # touch, which would abandon a running bot thread mid-trade and can leave
    # two overlapping MT5 order loops on the same account.
    uvicorn.run(app, host=config.BIND_HOST, port=config.BIND_PORT, reload=False)
