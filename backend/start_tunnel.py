"""
Starts a free Cloudflare "quick tunnel" pointed at the local API server and
prints (and copies to the clipboard) the public https:// URL to paste into
the dashboard's Settings > Backend URL field.

The Vercel-hosted dashboard is served over HTTPS, and browsers block an
HTTPS page from silently calling a plain http://localhost backend (Chrome's
Private Network Access check). Tunneling through Cloudflare gives the
backend a real https:// address, which sidesteps that restriction entirely
and also makes the dashboard reachable from other devices, not just this
machine.

This is the free, account-less tunnel — no Cloudflare login needed, but the
URL is different every time this script is (re)started. Run this alongside
the backend (`python server.py` or the tray app) whenever you want to reach
the dashboard through Vercel; leave the window open while you use it.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys

BACKEND_URL = "http://localhost:8000"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

# winget installs cloudflared here but doesn't add it to PATH until the next
# fresh shell — fall back to the known install location so this works right
# after a first-time install too.
FALLBACK_PATHS = [
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
]


def find_cloudflared() -> str:
    found = shutil.which("cloudflared")
    if found:
        return found
    for path in FALLBACK_PATHS:
        if shutil.os.path.exists(path):  # type: ignore[attr-defined]
            return path
    print("cloudflared not found. Install it with: winget install --id Cloudflare.cloudflared -e")
    sys.exit(1)


def copy_to_clipboard(text: str) -> bool:
    try:
        subprocess.run(["clip"], input=text, text=True, check=True)
        return True
    except Exception:
        return False


def main() -> None:
    cloudflared = find_cloudflared()
    print(f"Starting tunnel to {BACKEND_URL} ...\n", flush=True)

    proc = subprocess.Popen(
        [cloudflared, "tunnel", "--url", BACKEND_URL],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    found_url = None
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if found_url is None:
                match = URL_RE.search(line)
                if match:
                    found_url = match.group(0)
                    copied = copy_to_clipboard(found_url)
                    print("=" * 70, flush=True)
                    print(f"  Backend URL:  {found_url}", flush=True)
                    print(f"  {'(copied to clipboard — just paste it into Settings)' if copied else '(copy this into Settings > Backend URL)'}", flush=True)
                    print("=" * 70, flush=True)
                    print("\nTunnel is live. Keep this window open. Press Ctrl+C to stop.\n", flush=True)
            elif "ERR" in line or "error" in line.lower():
                print(line, end="", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
