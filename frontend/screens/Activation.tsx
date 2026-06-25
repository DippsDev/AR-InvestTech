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
         style={{ background: "#111827", padding: "20px 28px" }}>

      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="activation-card" style={{
        background: "#1F2937",
        border: "1px solid #374151",
        borderRadius: 12,
        maxWidth: 440,
        width: "100%",
        textAlign: "center",
        boxShadow: "0 20px 50px -20px rgba(0,0,0,.6)",
      }}>
        {/* Logo */}
        <div className="flex items-center justify-center gap-2.5" style={{ marginBottom: 24 }}>
          <div style={{ width: 44, height: 44, background: "#FFFFFF", borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="24" height="24" fill="none" stroke="#111827" strokeWidth="2" viewBox="0 0 24 24">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
            </svg>
          </div>
          <div style={{ textAlign: "left" }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: "#FFFFFF" }}>AR-InvestTech</div>
            <div style={{ fontSize: 11, color: "#6B7280", marginTop: 1 }}>US30 Scalping System</div>
          </div>
        </div>

        <h1 style={{ fontSize: 22, fontWeight: 700, color: "#FFFFFF", margin: "0 0 8px" }}>
          Activate Your License
        </h1>
        <p style={{ fontSize: 13, color: "#9CA3AF", margin: "0 0 24px", lineHeight: 1.5 }}>
          Enter the license key you received after purchase to unlock the bot.
        </p>

        <div style={{ textAlign: "left", marginBottom: 14 }}>
          <label style={{ display: "block", fontSize: 11, fontWeight: 600, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 6 }}>
            License Key
          </label>
          <input
            type="text"
            value={key}
            onChange={handleInput}
            onKeyDown={e => e.key === "Enter" && activate()}
            placeholder="ARB-XXXX-XXXX-XXXX"
            maxLength={19}
            style={{
              width: "100%",
              boxSizing: "border-box",
              background: "#111827",
              border: "1px solid #374151",
              borderRadius: 8,
              padding: "11px 14px",
              fontSize: 14,
              color: "#FFFFFF",
              outline: "none",
              fontFamily: "ui-monospace, Consolas, monospace",
              letterSpacing: ".1em",
              textAlign: "center",
            }}
          />
          <div style={{ fontSize: 11, color: "#6B7280", marginTop: 6, textAlign: "center" }}>
            Found in your purchase confirmation email
          </div>
        </div>

        {error && <div style={{ color: "#F87171", fontSize: 12, marginBottom: 8 }}>{error}</div>}

        <button
          onClick={activate}
          disabled={loading}
          className="w-full flex items-center justify-center gap-2"
          style={{
            background: "#FFFFFF",
            color: "#111827",
            border: "none",
            borderRadius: 8,
            padding: "12px 0",
            fontSize: 14,
            fontWeight: 700,
            cursor: loading ? "not-allowed" : "pointer",
            fontFamily: "inherit",
            marginTop: 4,
            opacity: loading ? 0.7 : 1,
          }}
        >
          {loading ? (
            <>
              <span className="spinner" style={{ width: 14, height: 14, border: "2px solid #111827", borderTopColor: "transparent", borderRadius: "50%", display: "inline-block" }} />
              Verifying license…
            </>
          ) : "Activate & Continue"}
        </button>

        <div className="flex items-center gap-3" style={{ margin: "18px 0", color: "#374151", fontSize: 11 }}>
          <span style={{ flex: 1, height: 1, background: "#374151" }} />
          or
          <span style={{ flex: 1, height: 1, background: "#374151" }} />
        </div>

        <div style={{ fontSize: 12, color: "#6B7280" }}>
          Need a key?{" "}
          <a href="#" style={{ color: "#9CA3AF", fontWeight: 600, textDecoration: "none" }}>
            Purchase a license →
          </a>
        </div>
        <div style={{ marginTop: 18, fontSize: 11, color: "#4B5563", letterSpacing: ".04em" }}>
          Developed by DippsDev
        </div>
      </div>
      </div>

      <div style={{ fontSize: 10, color: "#374151", paddingTop: 8 }}>v1.0.0</div>
    </div>
  );
}
