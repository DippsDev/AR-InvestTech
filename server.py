"""
FastAPI REST backend for the AR-InvestTech Next.js frontend.
Run with:  python server.py
Frontend:  cd frontend && npm run dev
"""
from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from bridge import BotBridge

app = FastAPI(title="AR-InvestTech API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

bridge = BotBridge()


# ── License ────────────────────────────────────────────────────────

@app.get("/license")
def check_license():
    return bridge.check_license()


class LicenseBody(BaseModel):
    key: str

@app.post("/license/validate")
def validate_license(body: LicenseBody):
    return bridge.validate_license(body.key)


# ── MT5 ────────────────────────────────────────────────────────────

@app.post("/mt5/connect")
def connect_mt5():
    return bridge.connect_mt5()


# ── Bot ────────────────────────────────────────────────────────────

@app.post("/bot/start")
def start_bot():
    if bridge._bot_running:
        return {"running": True}
    bridge._start_bot()
    return {"running": True}


@app.post("/bot/stop")
def stop_bot():
    if not bridge._bot_running:
        return {"running": False}
    bridge._stop_bot()
    return {"running": False}


# ── Live data ──────────────────────────────────────────────────────

@app.get("/stats")
def get_stats():
    return bridge.get_stats()


@app.get("/log")
def get_log():
    return bridge.get_log()


@app.get("/trades")
def get_trades():
    return bridge.get_trades()


# ── Settings ───────────────────────────────────────────────────────

@app.get("/settings")
def get_settings():
    return bridge.get_settings()


class SettingsBody(BaseModel):
    login: str = ""
    server: str = ""
    risk_pct: str = "1.0"
    daily_cap: str = "3.0"
    max_trades: str = "1"
    trail: bool = True
    bias: bool = False
    news: bool = False

@app.post("/settings")
def save_settings(body: SettingsBody):
    return bridge.save_settings(body.model_dump())


if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
