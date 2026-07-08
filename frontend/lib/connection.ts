// Where the dashboard finds its backend. The frontend is a static export
// (see next.config.ts: output "export") deployed once and shared by every
// user, so the backend URL/token can't be a build-time constant — each
// browser stores its own, entered once on the Activation screen.
const KEY = "ar-invest-connection";

export interface Connection {
  baseUrl: string;
  token: string;
}

const EMPTY: Connection = { baseUrl: "", token: "" };

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
    const baseUrl = parsed.baseUrl ?? "";
    return { baseUrl: isValidBaseUrl(baseUrl) ? baseUrl : "", token: parsed.token ?? "" };
  } catch {
    return EMPTY;
  }
}

export function saveConnection(baseUrl: string, token: string): void {
  if (typeof window === "undefined") return;
  const clean: Connection = { baseUrl: baseUrl.trim().replace(/\/+$/, ""), token: token.trim() };
  window.localStorage.setItem(KEY, JSON.stringify(clean));
}

// Token is optional: server.py doesn't currently enforce X-API-Token on any
// route, so only a reachable baseUrl is required for the app to function.
export function hasConnection(): boolean {
  return Boolean(getConnection().baseUrl);
}

export function clearConnection(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
}
