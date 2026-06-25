"use client";
import { useState, useCallback } from "react";

interface Props {
  onActivated: () => void;
  doValidate: (key: string) => Promise<{ ok: boolean; error?: string }>;
}

function fmtKey(raw: string) {
  const v = raw.replace(/[^A-Z0-9]/gi, "").toUpperCase().slice(0, 15);
  const parts = [v.slice(0, 3), v.slice(3, 7), v.slice(7, 11), v.slice(11, 15)].filter(Boolean);
  return parts.join("-");
}

export default function Activation({ onActivated, doValidate }: Props) {
  const [key,     setKey]     = useState("");
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(false);

  const handleInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setKey(fmtKey(e.target.value));
    setError("");
  }, []);

  const activate = useCallback(async () => {
    if (loading) return;
    setError("");
    setLoading(true);
    try {
      const res = await doValidate(key);
      if (res.ok) onActivated();
      else setError(res.error ?? "Invalid license key. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [key, loading, doValidate, onActivated]);

  return (
    <div className="flex-1 flex flex-col animate-fade"
         style={{ background: "var(--act-outer-bg)", padding: "20px 28px", transition: "background 0.2s ease" }}>

      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="activation-card" style={{
        background: "var(--act-card-bg)",
        border: "1px solid var(--act-border)",
        borderRadius: 12,
        maxWidth: 440,
        width: "100%",
        textAlign: "center",
        boxShadow: "0 20px 50px -20px rgba(0,0,0,.4)",
        transition: "background 0.2s ease, border-color 0.2s ease",
      }}>
        {/* Logo */}
        <div className="flex items-center justify-center gap-2.5" style={{ marginBottom: 24 }}>
          <div style={{
            width: 44, height: 44,
            background: "var(--nav-start-bg)",
            borderRadius: 10,
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "var(--nav-start-text)",
            transition: "background 0.2s ease",
          }}>
            <svg width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
            </svg>
          </div>
          <div style={{ textAlign: "left" }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--act-text)", transition: "color 0.2s ease" }}>AR-InvestTech</div>
            <div style={{ fontSize: 11, color: "var(--act-text-dim)", marginTop: 1 }}>US30 Scalping System</div>
          </div>
        </div>

        <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--act-text)", margin: "0 0 8px" }}>
          Activate Your License
        </h1>
        <p style={{ fontSize: 13, color: "var(--act-text-sub)", margin: "0 0 24px", lineHeight: 1.5 }}>
          Enter the license key you received after purchase to unlock the bot.
        </p>

        <div style={{ textAlign: "left", marginBottom: 14 }}>
          <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "var(--act-text-sub)", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 6 }}>
            License Key
          </label>
          <input
            type="text"
            value={key}
            onChange={handleInput}
            onKeyDown={e => e.key === "Enter" && activate()}
            placeholder="ARB-XXXX-XXXX-XXXX"
            maxLength={19}
            className="act-input"
            style={{
              width: "100%",
              boxSizing: "border-box",
              background: "var(--act-input-bg)",
              border: "1px solid var(--act-border)",
              borderRadius: 8,
              padding: "11px 14px",
              fontSize: 14,
              color: "var(--act-text)",
              outline: "none",
              fontFamily: "ui-monospace, Consolas, monospace",
              letterSpacing: ".1em",
              textAlign: "center",
              transition: "background 0.2s ease, border-color 0.2s ease, color 0.2s ease",
            }}
          />
          <div style={{ fontSize: 11, color: "var(--act-text-dim)", marginTop: 6, textAlign: "center" }}>
            Found in your purchase confirmation email
          </div>
        </div>

        {error && <div style={{ color: "#F87171", fontSize: 12, marginBottom: 8 }}>{error}</div>}

        <button
          onClick={activate}
          disabled={loading}
          className="w-full flex items-center justify-center gap-2"
          style={{
            background: "var(--nav-start-bg)",
            color: "var(--nav-start-text)",
            border: "none",
            borderRadius: 8,
            padding: "12px 0",
            fontSize: 14,
            fontWeight: 700,
            cursor: loading ? "not-allowed" : "pointer",
            fontFamily: "inherit",
            marginTop: 4,
            opacity: loading ? 0.7 : 1,
            transition: "background 0.2s ease, color 0.2s ease",
          }}
        >
          {loading ? (
            <>
              <span className="spinner" style={{ width: 14, height: 14, border: "2px solid var(--nav-start-text)", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block" }} />
              Verifying license…
            </>
          ) : "Activate & Continue"}
        </button>

        <div className="flex items-center gap-3" style={{ margin: "18px 0", color: "var(--act-divider)", fontSize: 11 }}>
          <span style={{ flex: 1, height: 1, background: "var(--act-divider)" }} />
          or
          <span style={{ flex: 1, height: 1, background: "var(--act-divider)" }} />
        </div>

        <div style={{ fontSize: 12, color: "var(--act-text-dim)" }}>
          Need a key?{" "}
          <a href="#" style={{ color: "var(--act-text-sub)", fontWeight: 600, textDecoration: "none" }}>
            Purchase a license →
          </a>
        </div>
        <div style={{ marginTop: 18, fontSize: 11, color: "var(--act-text-dim)", letterSpacing: ".04em" }}>
          Developed by DippsDev
        </div>
      </div>
      </div>

      <div style={{ fontSize: 10, color: "var(--act-divider)", paddingTop: 8 }}>v1.0.0</div>
    </div>
  );
}
