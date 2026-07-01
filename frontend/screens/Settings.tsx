"use client";
import { useState, useEffect } from "react";
import type { Settings as S } from "@/lib/api";

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
  aggressive: false, off_hours: false,
};

function Toggle({ on, onToggle }: { on: boolean; onToggle: () => void }) {
  return (
    <div onClick={onToggle} style={{
      width: 38, height: 22, borderRadius: 11,
      background: on ? "#111827" : "#D1D5DB",
      position: "relative", cursor: "pointer",
      transition: "background .18s", flexShrink: 0,
    }}>
      <div style={{
        position: "absolute", top: 2,
        left: on ? 18 : 2, width: 18, height: 18,
        borderRadius: "50%", background: "#FFFFFF",
        transition: "left .18s", boxShadow: "0 1px 2px rgba(0,0,0,.2)",
      }} />
    </div>
  );
}

export default function Settings({ onSave, doLoad, connected, server, pingMs }: Props) {
  const [form,   setForm]   = useState<S>(DEFAULTS);
  const [saving, setSaving] = useState(false);

  useEffect(() => { doLoad().then(setForm).catch(() => {}); }, [doLoad]);

  const set = (k: keyof S, v: string | boolean) => setForm(f => ({ ...f, [k]: v }));

  const save = async () => {
    setSaving(true);
    try { await onSave(form); } finally { setSaving(false); }
  };

  const fld = (id: keyof S, label: string, placeholder?: string) => (
    <div>
      <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "#6B7280", marginBottom: 5 }}>{label}</label>
      <input
        value={form[id] as string}
        onChange={e => set(id, e.target.value)}
        placeholder={placeholder}
        style={{
          width: "100%", boxSizing: "border-box",
          border: "1px solid #D1D5DB", borderRadius: 6,
          padding: "9px 12px", fontSize: 13, color: "#111827",
          outline: "none", fontFamily: "inherit",
          background: "#FFFFFF",
        }}
      />
    </div>
  );

  const tog = (k: "aggressive" | "off_hours", label: string, sub: string, last = false) => (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "12px 0", borderBottom: last ? "none" : "1px solid #F3F4F6",
    }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#111827" }}>{label}</div>
        <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 2 }}>{sub}</div>
      </div>
      <Toggle on={form[k] as boolean} onToggle={() => set(k, !form[k])} />
    </div>
  );

  return (
    <>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#111827" }}>Settings</div>
          <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>Connection &amp; risk parameters</div>
        </div>
        <button onClick={save} disabled={saving} style={{
          background: "#111827", color: "#FFFFFF", border: "none",
          borderRadius: 6, padding: "9px 18px", fontSize: 12, fontWeight: 700,
          cursor: saving ? "not-allowed" : "pointer", fontFamily: "inherit",
          opacity: saving ? 0.6 : 1,
        }}>
          {saving ? "Saving…" : "Save Changes"}
        </button>
      </div>

      {/* MT5 Connection */}
      <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #E5E7EB" }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#111827", textTransform: "uppercase", letterSpacing: ".05em" }}>MT5 Connection</span>
        </div>
        <div style={{ padding: 16 }}>
          <div className="grid-mt5">
            {fld("login",  "Account Login", "e.g. 295971388")}
            {fld("server", "Server",        "e.g. Exness-MT5Real27")}
            {fld("symbol", "Symbol",        "e.g. US30m")}
          </div>
          <div style={{ gridColumn: "span 2", display: "flex", alignItems: "center", gap: 8, fontSize: 12, marginTop: 12 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: connected ? "#16A34A" : "#D1D5DB", display: "inline-block" }} />
            <span style={{ color: connected ? "#16A34A" : "#6B7280", fontWeight: connected ? 600 : 400 }}>
              {connected
                ? (pingMs != null ? `Connected · ping ${pingMs}ms` : "Connected")
                : "Not connected"}
            </span>
          </div>
        </div>
      </div>

      {/* Risk Parameters */}
      <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #E5E7EB" }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#111827", textTransform: "uppercase", letterSpacing: ".05em" }}>Risk Parameters</span>
        </div>
        <div className="grid-3" style={{ padding: 16 }}>
          {fld("risk_pct",             "Risk per Trade (%)")}
          {fld("daily_loss_limit_usd", "Daily Loss Limit ($)")}
          {fld("max_trades_per_day",   "Max Trades / Day")}
          {fld("max_drawdown_pct",     "Max Drawdown (%)")}
        </div>
      </div>

      {/* Strategy Toggles */}
      <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #E5E7EB" }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#111827", textTransform: "uppercase", letterSpacing: ".05em" }}>Strategy Toggles</span>
        </div>
        <div style={{ padding: "6px 16px" }}>
          {tog("aggressive", "Aggressive Mode",   "2–3 trades/day: lower filters + London session · restart bot to apply")}
          {tog("off_hours",  "Off-Hours Trading", "Trade outside session windows · max 3 fills/day · closes 17:00 ET · restart bot to apply", true)}
        </div>
      </div>
    </>
  );
}
