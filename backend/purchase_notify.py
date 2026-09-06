"""Send a license-request notification to the operator inbox."""
from __future__ import annotations

import logging
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import httpx

import config
from src import paths

log = logging.getLogger(__name__)

_WHATSAPP_DIGITS = re.compile(r"\d+")


def digits_only(whatsapp: str) -> str:
    return "".join(_WHATSAPP_DIGITS.findall(whatsapp or ""))


def build_message(name: str, email: str, whatsapp: str, broker: str, notes: str) -> tuple[str, str]:
    subject = f"ARI_Sniper_EA license request — {name} — WhatsApp {whatsapp}"
    body = (
        "New ARI_Sniper_EA license request\n"
        "\n"
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"WhatsApp: {whatsapp}\n"
        f"Broker: {broker or '—'}\n"
        f"Notes: {notes or '—'}\n"
        "\n"
        "Quoted to client: P1,500 setup + P300 minimum deposit ≈ P1,800 to get a key.\n"
    )
    return subject, body


def log_request(name: str, email: str, whatsapp: str, broker: str, notes: str) -> None:
    line = (
        f"{datetime.now(timezone.utc).isoformat()} | {name} | {email} | "
        f"{whatsapp} | {broker or '-'} | {notes or '-'}\n"
    )
    path: Path = paths.app_data_dir() / "purchase_requests.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


def _send_smtp(subject: str, body: str, reply_to: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM
    msg["To"] = config.PURCHASE_NOTIFY_EMAIL
    msg["Reply-To"] = reply_to
    msg.set_content(body)
    if config.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)


def _send_formsubmit(subject: str, body: str, name: str, email: str, whatsapp: str) -> None:
    dest = quote(config.PURCHASE_NOTIFY_EMAIL, safe="@")
    r = httpx.post(
        f"https://formsubmit.co/ajax/{dest}",
        json={
            "name": name,
            "email": email,
            "whatsapp": whatsapp,
            "_subject": subject,
            "message": body,
            "_template": "box",
        },
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=20,
    )
    r.raise_for_status()


def send_purchase_notification(name: str, email: str, whatsapp: str, broker: str, notes: str) -> None:
    subject, body = build_message(name, email, whatsapp, broker, notes)
    log_request(name, email, whatsapp, broker, notes)
    if config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD:
        _send_smtp(subject, body, email)
        return
    _send_formsubmit(subject, body, name, email, whatsapp)
