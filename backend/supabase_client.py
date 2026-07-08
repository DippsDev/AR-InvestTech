"""Lazy Supabase client for license activation.

The service key is loaded from config (backend .env) and must never be sent to
frontend code. If Supabase is not configured, the client remains None and the
bridge falls back to the original local-only validation behavior.
"""
from __future__ import annotations

from typing import Optional

import config

_supabase: Optional[object] = None


def get_supabase() -> Optional[object]:
    """Return the shared Supabase client, or None if not configured."""
    global _supabase
    if _supabase is not None:
        return _supabase

    url = config.SUPABASE_URL
    key = config.SUPABASE_SERVICE_KEY
    if not url or not key:
        return None

    try:
        from supabase import create_client
    except ImportError:  # pragma: no cover - supabase package missing
        return None

    _supabase = create_client(url, key)
    return _supabase


def is_configured() -> bool:
    """Return True when Supabase credentials are present."""
    return bool(config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY)
