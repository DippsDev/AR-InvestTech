// Where the dashboard finds its backend. The frontend is a static export
// (see next.config.ts: output "export") deployed once and shared by every
// user, so the credential (license key) is stored per-browser, but the backend
// URL is hardcoded so clients never have to enter it.
const KEY = "ar-invest-connection";
export const DEFAULT_BACKEND_URL = "https://bot.ar-investech.uk";

export interface Connection {
  baseUrl: string;
  token: string;
}

const EMPTY: Connection = { baseUrl: DEFAULT_BACKEND_URL, token: "" };

// A baseUrl that isn't a real absolute http(s) URL (e.g. an email typed into
// the wrong field) must never reach fetch() — the browser would silently
// resolve it as a relative path against the frontend's own origin instead of
// throwing, producing a confusing request to the wrong server.
export function isValidBaseUrl(url: string): boolean {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

export function getConnection(): Connection {
  if (typeof window === "undefined") return EMPTY;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw);
    return { baseUrl: DEFAULT_BACKEND_URL, token: parsed.token ?? "" };
  } catch {
    return EMPTY;
  }
}

export function saveConnection(_baseUrl: string, token: string): void {
  if (typeof window === "undefined") return;
  const clean: Connection = { baseUrl: DEFAULT_BACKEND_URL, token: token.trim() };
  window.localStorage.setItem(KEY, JSON.stringify(clean));
}

// Only a baseUrl is required to have "a connection" — deliberately not the
// token, because a backend with no API_TOKEN set in its .env runs in local-only
// mode and needs none (see config.API_TOKEN).
//
// Whether the token is actually required is therefore a property of the
// backend, not something this function can know up front. When the backend
// does set one, every route bar /health and the docs endpoints answers 401
// until a matching token is supplied — api.ts turns that into an actionable
// message rather than failing here.
export function hasConnection(): boolean {
  return Boolean(getConnection().baseUrl);
}

export function clearConnection(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
}
