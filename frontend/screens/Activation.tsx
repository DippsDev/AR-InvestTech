"use client";
import { useState, useCallback } from "react";
import { getConnection, isValidBaseUrl, saveConnection } from "@/lib/connection";
import { PERSONAS } from "@/lib/personas";
import PixelAvatar from "@/components/dashboard/PixelAvatar";

interface Props {
  onActivated:  () => void;
  doValidate:   (key: string) => Promise<{ ok: boolean; error?: string }>;
}

function fmtKey(raw: string) {
  const stripped = raw.replace(/[^A-Z0-9]/gi, "").toUpperCase();
  const withoutPrefix = stripped.startsWith("ARB") ? stripped.slice(3) : stripped;
  const v = withoutPrefix.slice(0, 12);
  const parts = ["ARB", v.slice(0, 4), v.slice(4, 8), v.slice(8, 12)].filter(p => p.length > 0);
  return parts.join("-");
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
  const [key,        setKey]        = useState("");
  const [backendUrl, setBackendUrl] = useState(() => getConnection().baseUrl);
  const [apiToken,   setApiToken]   = useState(() => getConnection().token);
  const [error,      setError]      = useState("");
  const [loading,    setLoading]    = useState(false);

  const handleKey = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setKey(fmtKey(e.target.value));
    setError("");
  }, []);

  const activate = useCallback(async () => {
    if (loading) return;
    if (!backendUrl) { setError("Backend URL is required."); return; }
    if (!isValidBaseUrl(backendUrl)) { setError("Enter a valid backend URL, e.g. http://192.168.1.50:8000"); return; }
    if (!key) { setError("License key is required."); return; }
    setLoading(true);
    setError("");
    saveConnection(backendUrl, apiToken);
    try {
      const res = await doValidate(key);
      if (res.ok) onActivated();
      else setError(res.error ?? "Invalid license key.");
    } finally {
      setLoading(false);
    }
  }, [key, backendUrl, apiToken, loading, doValidate, onActivated]);

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
        {/* Logo — Trader's pixel-office avatar stands in for the brand mark,
            talking to give the screen some life before there's any real
            backend activity to show. */}
        <div className="flex items-center justify-center gap-2.5" style={{ marginBottom: 24 }}>
          <div style={{
            width: 56, height: 56,
            background: "var(--dash-card-bg-2)",
            border: "1px solid var(--dash-border)",
            borderRadius: 10,
            display: "flex", alignItems: "center", justifyContent: "center",
            overflow: "hidden",
            flexShrink: 0,
          }}>
            <PixelAvatar persona={PERSONAS.Trader} size={44} talking />
          </div>
          <div style={{ textAlign: "left" }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--dash-text)" }}>ARI_Sniper_EA</div>
            <div style={{ fontSize: 11, color: "var(--dash-text-dim)", marginTop: 1 }}>Silver Bullet · US30</div>
          </div>
        </div>

        <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--dash-text)", margin: "0 0 8px" }}>
          Activate Your License
        </h1>
        <p style={{ fontSize: 13, color: "var(--dash-text-muted)", margin: "0 0 24px", lineHeight: 1.5 }}>
          Connect to your backend and enter your license key to unlock the bot.
        </p>

        {/* Backend connection */}
        <div style={{ textAlign: "left", marginBottom: 14 }}>
          <label style={labelStyle}>Backend URL</label>
          <input
            type="text"
            value={backendUrl}
            onChange={e => { setBackendUrl(e.target.value); setError(""); }}
            onKeyDown={e => e.key === "Enter" && activate()}
            placeholder="http://192.168.1.50:8000"
            inputMode="url"
            autoCapitalize="none"
            autoCorrect="off"
            className="act-input"
            style={{ ...inputStyle, textAlign: "left", letterSpacing: "normal" }}
          />
        </div>

        <div style={{ textAlign: "left", marginBottom: 20 }}>
          <label style={labelStyle}>API Token <span style={{ textTransform: "none", fontWeight: 400 }}>(optional)</span></label>
          <input
            type="text"
            value={apiToken}
            onChange={e => setApiToken(e.target.value)}
            onKeyDown={e => e.key === "Enter" && activate()}
            placeholder="leave blank if unset"
            autoCapitalize="none"
            autoCorrect="off"
            className="act-input"
            style={{ ...inputStyle, textAlign: "left", letterSpacing: "normal" }}
          />
        </div>

        {/* Key */}
        <div style={{ textAlign: "left", marginBottom: 20 }}>
          <label style={labelStyle}>License Key</label>
          <input
            type="text"
            value={key}
            onChange={handleKey}
            onKeyDown={e => e.key === "Enter" && activate()}
            placeholder="ARB-XXXX-XXXX-XXXX"
            maxLength={19}
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
          disabled={loading || !key || !backendUrl}
          className="w-full flex items-center justify-center gap-2"
          style={{
            background: "#22C55E",
            color: "#0B0E11",
            border: "none",
            borderRadius: 8,
            padding: "12px 0",
            fontSize: 14,
            fontWeight: 700,
            cursor: (loading || !key || !backendUrl) ? "not-allowed" : "pointer",
            fontFamily: "inherit",
            opacity: (loading || !key || !backendUrl) ? 0.45 : 1,
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
