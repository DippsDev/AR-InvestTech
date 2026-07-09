"use client";
import { useState, useEffect } from "react";
import type { Settings as S } from "@/lib/api";
import { getConnection, isValidBaseUrl, saveConnection } from "@/lib/connection";

interface Props {
  onSave: (data: S) => Promise<void>;
  doLoad: () => Promise<S>;
  connected: boolean;
  server: string;
  pingMs: number | null;
}

const DEFAULTS: S = {
  login: "", server: "", symbol: "US30", risk_pct: "1.0",
  daily_loss_limit_usd: "3.0", max_trades_per_day: "2", max_drawdown_pct: "50.0",
  aggressive: false, off_hours: false, news: true, password: "",
};

function Toggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <div onClick={onToggle} style={{
      width: 38, height: 22, borderRadius: 11,
      background: on ? "#22C55E" : "var(--dash-border-light)",
      position: "relative", cursor: "pointer",
      transition: "background .18s", flexShrink: 0,
    }}>
      <div style={{
        position: "absolute", top: 2,
        left: on ? 18 : 2, width: 18, height: 18,
        borderRadius: "50%", background: "#FFFFFF",
        transition: "left .18s", boxShadow: "0 1px 2px rgba(0,0,0,.35)",
      }} />
    </div>
  );
}

function SectionHeader({ label, color }: { label: string; color: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "12px 16px", borderBottom: "1px solid var(--dash-border)" }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: color }} />
      <span style={{ fontSize: 10, fontWeight: 800, color, letterSpacing: ".06em" }}>{label}</span>
    </div>
  );
}

export default function Settings({ onSave, doLoad, connected, server, pingMs }: Props) {
  const [form,   setForm]   = useState<S>(DEFAULTS);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveOk,    setSaveOk]    = useState(false);

  const [backendUrl, setBackendUrl]   = useState(() => getConnection().baseUrl);
  const [apiToken,   setApiToken]     = useState(() => getConnection().token);
  const [connError,  setConnError]   = useState("");
  const [connSaved,  setConnSaved]   = useState(false);

  const saveConn = () => {
    if (backendUrl && !isValidBaseUrl(backendUrl)) {
      setConnError("Enter a valid backend URL, e.g. http://192.168.1.50:8000");
      setConnSaved(false);
      return;
    }
    setConnError("");
    saveConnection(backendUrl, apiToken);
    setConnSaved(true);
    setTimeout(() => setConnSaved(false), 2000);
  };

  // Load once on mount only — `doLoad` is a fresh closure on every parent
  // render (page.tsx re-renders every 5s from stats/log polling even while
  // this screen is open), so depending on it here would silently overwrite
  // in-progress edits with stale server values as the user types.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { doLoad().then(setForm).catch(() => {}); }, []);

  const set = (k: keyof S, v: string | boolean) => setForm(f => ({ ...f, [k]: v }));

  const save = async () => {
    setSaving(true);
    setSaveError("");
    setSaveOk(false);
    try {
      await onSave(form);
      // Re-fetch from the server instead of trusting local state as "saved" —
      // this is the only way to confirm the save actually took effect
      // server-side rather than just looking like it did in the form.
      try {
        const fresh = await doLoad();
        // Password is write-only — never keep it sitting in memory/DOM
        // longer than the single save that used it, and the server never
        // returns it anyway.
        setForm({ ...fresh, password: "" });
      } catch {
        // The save itself already succeeded (onSave didn't throw); a failed
        // confirmation re-fetch shouldn't be reported as a save failure.
        setForm(f => ({ ...f, password: "" }));
      }
      setSaveOk(true);
      setTimeout(() => setSaveOk(false), 2000);
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : "Save failed — check the Backend URL in Connection below."
      );
    } finally { setSaving(false); }
  };

  const fld = (id: keyof S, label: string, placeholder?: string, type: string = "text") => (
    <div>
      <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--dash-text-muted)", marginBottom: 5 }}>{label}</label>
      <input
        type={type}
        value={(form[id] as string) ?? ""}
        onChange={e => set(id, e.target.value)}
        placeholder={placeholder}
        autoComplete={type === "password" ? "new-password" : undefined}
        style={{
          width: "100%", boxSizing: "border-box",
          border: "1px solid var(--dash-border)", borderRadius: 6,
          padding: "9px 12px", fontSize: 13, color: "var(--dash-text)",
          outline: "none", fontFamily: "inherit",
          background: "var(--dash-card-bg-2)",
        }}
      />
    </div>
  );

  const tog = (k: "aggressive" | "off_hours" | "news", label: string, sub: string, last = false) => (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "12px 0", borderBottom: last ? "none" : "1px solid var(--dash-border)",
    }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "var(--dash-text)" }}>{label}</div>
        <div style={{ fontSize: 11, color: "var(--dash-text-dim)", marginTop: 2 }}>{sub}</div>
      </div>
      <Toggle on={form[k] as boolean} onToggle={() => set(k, !form[k])} />
    </div>
  );

  const cardStyle: React.CSSProperties = {
    background: "var(--dash-card-bg)", border: "1px solid var(--dash-border)", borderRadius: 8, overflow: "hidden",
  };

  return (
    <>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "var(--dash-text)" }}>Settings</div>
          <div style={{ fontSize: 12, color: "var(--dash-text-muted)", marginTop: 2 }}>Connection &amp; risk parameters</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {saveOk && <span style={{ fontSize: 12, color: "#22C55E" }}>Saved</span>}
          {saveError && <span style={{ fontSize: 12, color: "#F87171", maxWidth: 260 }}>{saveError}</span>}
          <button onClick={save} disabled={saving} style={{
            background: "#22C55E", color: "#0B0E11", border: "none",
            borderRadius: 6, padding: "9px 18px", fontSize: 12, fontWeight: 700,
            cursor: saving ? "not-allowed" : "pointer", fontFamily: "inherit",
            opacity: saving ? 0.6 : 1,
          }}>
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>

      {/* Backend Connection */}
      <div style={cardStyle}>
        <SectionHeader label="Backend Connection" color="var(--dash-accent-green, #22C55E)" />
        <div style={{ padding: 16 }}>
          <div className="grid-mt5">
            <div>
              <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--dash-text-muted)", marginBottom: 5 }}>Backend URL</label>
              <input
                type="text"
                value={backendUrl}
                onChange={e => { setBackendUrl(e.target.value); setConnError(""); }}
                placeholder="http://192.168.1.50:8000"
                style={{
                  width: "100%", boxSizing: "border-box",
                  border: "1px solid var(--dash-border)", borderRadius: 6,
                  padding: "9px 12px", fontSize: 13, color: "var(--dash-text)",
                  outline: "none", fontFamily: "inherit",
                  background: "var(--dash-card-bg-2)",
                }}
              />
            </div>
            <div>
              <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--dash-text-muted)", marginBottom: 5 }}>API Token (optional)</label>
              <input
                type="text"
                value={apiToken}
                onChange={e => setApiToken(e.target.value)}
                placeholder="leave blank if unset"
                style={{
                  width: "100%", boxSizing: "border-box",
                  border: "1px solid var(--dash-border)", borderRadius: 6,
                  padding: "9px 12px", fontSize: 13, color: "var(--dash-text)",
                  outline: "none", fontFamily: "inherit",
                  background: "var(--dash-card-bg-2)",
                }}
              />
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 12 }}>
            <button onClick={saveConn} style={{
              background: "var(--dash-card-bg-2)", color: "var(--dash-text)", border: "1px solid var(--dash-border)",
              borderRadius: 6, padding: "7px 14px", fontSize: 12, fontWeight: 700,
              cursor: "pointer", fontFamily: "inherit",
            }}>
              Save Connection
            </button>
            {connSaved && <span style={{ fontSize: 12, color: "#22C55E" }}>Saved</span>}
            {connError && <span style={{ fontSize: 12, color: "#F87171" }}>{connError}</span>}
          </div>
        </div>
      </div>

      {/* MT5 Connection */}
      <div style={cardStyle}>
        <SectionHeader label="MT5 Connection" color="var(--dash-accent-blue)" />
        <div style={{ padding: 16 }}>
          <div className="grid-mt5">
            {fld("login",    "Account Login", "e.g. 295971388")}
            {fld("server",   "Server",        "e.g. Exness-MT5Real27")}
            {fld("symbol",   "Symbol",        "e.g. US30m")}
            {fld("password", "Password",      "leave blank to keep current", "password")}
          </div>
          <div style={{ gridColumn: "span 2", display: "flex", alignItems: "center", gap: 8, fontSize: 12, marginTop: 12 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: connected ? "#22C55E" : "var(--dash-border-light)", display: "inline-block" }} />
            <span style={{ color: connected ? "#22C55E" : "var(--dash-text-muted)", fontWeight: connected ? 600 : 400 }}>
              {connected
                ? (pingMs != null ? `Connected · ${server || "MT5"} · ping ${pingMs}ms` : `Connected${server ? ` · ${server}` : ""}`)
                : "Not connected"}
            </span>
          </div>
        </div>
      </div>

      {/* Risk Parameters */}
      <div style={cardStyle}>
        <SectionHeader label="Risk Parameters" color="var(--dash-accent-orange)" />
        <div className="grid-3" style={{ padding: 16 }}>
          {fld("risk_pct",             "Risk per Trade (%)")}
          {fld("daily_loss_limit_usd", "Daily Loss Limit ($)")}
          {fld("max_trades_per_day",   "Max Trades / Day")}
          {fld("max_drawdown_pct",     "Max Drawdown (%)")}
        </div>
      </div>

      {/* Strategy Toggles */}
      <div style={cardStyle}>
        <SectionHeader label="Strategy Toggles" color="var(--dash-accent-purple)" />
        <div style={{ padding: "6px 16px" }}>
          {tog("aggressive", "Aggressive Mode",   "2–3 trades/day: lower filters + London session · restart bot to apply")}
          {tog("off_hours",  "Off-Hours Trading", "Trade outside session windows · max 3 fills/day · closes 17:00 ET · restart bot to apply")}
          {tog("news",       "Skip News Days",    "Pause all entries on NFP/FOMC/CPI/GDP release days · restart bot to apply", true)}
        </div>
      </div>
    </>
  );
}
