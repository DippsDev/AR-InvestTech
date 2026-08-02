"use client";
import { useState, useCallback } from "react";
import { saveConnection } from "@/lib/connection";

interface Props {
  onActivated:  () => void;
  doValidate:   (key: string) => Promise<{ ok: boolean; error?: string }>;
}

function fmtKey(raw: string) {
  const stripped = raw.replace(/[^A-Z0-9]/gi, "").toUpperCase();
  const prefix = "MOJALEFA";
  let body = stripped.startsWith(prefix) ? stripped.slice(prefix.length) : stripped;
  body = body.replace(/[^0-9]/g, "").slice(0, 4);
  return `${prefix}-${body}`;
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  background: "var(--dash-card-bg-2)",
  border: "1px solid var(--dash-border)",
  borderRadius: 8,
  padding: "11px 14px",
  fontSize: 14,
  color: "var(--dash-text)",
  outline: "none",
  fontFamily: "ui-monospace, Consolas, monospace",
  letterSpacing: ".05em",
  textAlign: "center",
  transition: "background 0.2s ease, border-color 0.2s ease, color 0.2s ease",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: 600,
  color: "var(--dash-text-muted)",
  textTransform: "uppercase",
  letterSpacing: ".05em",
  marginBottom: 6,
};

export default function Activation({ onActivated, doValidate }: Props) {
  const [key,     setKey]     = useState("");
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(false);

  const handleKey = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setKey(fmtKey(e.target.value));
    setError("");
  }, []);

  const activate = useCallback(async () => {
    if (loading) return;
    if (!key) { setError("License key is required."); return; }
    setLoading(true);
    setError("");
    // The license key itself becomes the credential: server.py's _require_token
    // accepts either the API_TOKEN from .env or the activated license key.
    saveConnection("", key);
    try {
      const res = await doValidate(key);
      if (res.ok) onActivated();
      else setError(res.error ?? "Invalid license key.");
    } finally {
      setLoading(false);
    }
  }, [key, loading, doValidate, onActivated]);

  return (
    <div className="flex-1 flex flex-col animate-fade"
         style={{ height: "100%", background: "var(--dash-bg)", padding: "20px 28px" }}>

      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="activation-card" style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 12,
        maxWidth: 440,
        width: "100%",
        textAlign: "center",
        boxShadow: "0 20px 50px -20px rgba(0,0,0,.6)",
      }}>
        {/* Logo — favicon.ico used as the brand mark. */}
        <div className="flex items-center justify-center gap-2.5" style={{ marginBottom: 24 }}>
          <div style={{
            width: 56, height: 56,
            display: "flex", alignItems: "center", justifyContent: "center",
            overflow: "hidden",
            flexShrink: 0,
          }}>
            <img src="/favicon.ico" alt="ARI_Sniper_EA" width={44} height={44} style={{ objectFit: "contain" }} />
          </div>
          <div style={{ textAlign: "left" }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--dash-text)" }}>ARI_Sniper_EA</div>
            <div style={{ fontSize: 11, color: "var(--dash-text-dim)", marginTop: 1 }}>Silver Bullet · Trendline · Multi-Symbol</div>
          </div>
        </div>

        <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--dash-text)", margin: "0 0 8px" }}>
          Activate Your License
        </h1>
        <p style={{ fontSize: 13, color: "var(--dash-text-muted)", margin: "0 0 24px", lineHeight: 1.5 }}>
          Enter your license key to unlock the bot.
        </p>

        {/* License key */}
        <div style={{ textAlign: "left", marginBottom: 20 }}>
          <label style={labelStyle}>License Key</label>
          <input
            type="text"
            value={key}
            onChange={handleKey}
            onKeyDown={e => e.key === "Enter" && activate()}
            placeholder="MOJALEFA-XXXX"
            maxLength={13}
            inputMode="text"
            autoCapitalize="characters"
            autoCorrect="off"
            className="act-input"
            style={inputStyle}
          />
          {error && <div style={{ color: "#F87171", fontSize: 12, marginTop: 5 }}>{error}</div>}
        </div>

        <button
          onClick={activate}
          disabled={loading || !key}
          className="w-full flex items-center justify-center gap-2"
          style={{
            background: "#22C55E",
            color: "#0B0E11",
            border: "none",
            borderRadius: 8,
            padding: "12px 0",
            fontSize: 14,
            fontWeight: 700,
            cursor: (loading || !key) ? "not-allowed" : "pointer",
            fontFamily: "inherit",
            opacity: (loading || !key) ? 0.45 : 1,
            transition: "background 0.2s ease, color 0.2s ease, opacity 0.15s ease",
          }}
        >
          {loading ? (
            <>
              <span className="spinner" style={{ width: 14, height: 14, border: "2px solid #0B0E11", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block" }} />
              Verifying…
            </>
          ) : "Activate & Continue"}
        </button>

        <div className="flex items-center gap-3" style={{ margin: "18px 0", color: "var(--dash-border)", fontSize: 11 }}>
          <span style={{ flex: 1, height: 1, background: "var(--dash-border)" }} />
          or
          <span style={{ flex: 1, height: 1, background: "var(--dash-border)" }} />
        </div>

        <div style={{ fontSize: 12, color: "var(--dash-text-dim)" }}>
          Need a license?{" "}
          <a href="#" style={{ color: "var(--dash-text-sub)", fontWeight: 600, textDecoration: "none" }}>
            Purchase →
          </a>
        </div>
        <div style={{ marginTop: 18, fontSize: 11, color: "var(--dash-text-dim)", letterSpacing: ".04em" }}>
          Developed by DippsDev
        </div>
      </div>
      </div>

      <div style={{ fontSize: 10, color: "var(--dash-border-light)", paddingTop: 8 }}>v1.0.0</div>
    </div>
  );
}
