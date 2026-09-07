"use client";
import { useEffect, useState } from "react";

const WHATSAPP_DISPLAY = "+267 75362329";
const WHATSAPP_LINK =
  "https://wa.me/26775362329"
  + "?text=" + encodeURIComponent("Hi, I would like to purchase an ARI_Sniper_EA license.");

const EMAIL_DISPLAY = "dippsinbox@gmail.com";
const EMAIL_LINK =
  "mailto:dippsinbox@gmail.com"
  + "?subject=" + encodeURIComponent("ARI_Sniper_EA license request")
  + "&body=" + encodeURIComponent(
    "Hi,\n\nI would like to purchase an ARI_Sniper_EA license.\n\n"
    + "Name:\nWhatsApp:\nBroker (optional):\n\nThank you.",
  );

const contactBtnStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "flex-start",
  gap: 4,
  width: "100%",
  boxSizing: "border-box",
  background: "var(--dash-card-bg-2)",
  border: "1px solid var(--dash-border)",
  borderRadius: 8,
  padding: "12px 14px",
  textDecoration: "none",
  textAlign: "left",
  fontFamily: "inherit",
  cursor: "pointer",
  transition: "border-color 0.15s ease, background 0.15s ease",
};

export default function Purchase() {
  const [promptOpen, setPromptOpen] = useState(false);

  useEffect(() => {
    if (!promptOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPromptOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [promptOpen]);

  return (
    <div
      className="activation-screen flex-1 flex flex-col animate-fade"
      style={{ background: "var(--dash-bg)", padding: "20px 28px" }}
    >
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div
          className="activation-card"
          style={{
            background: "var(--dash-card-bg)",
            border: "1px solid var(--dash-border)",
            borderRadius: 12,
            maxWidth: 440,
            width: "100%",
            textAlign: "center",
            boxShadow: "0 20px 50px -20px rgba(0,0,0,.6)",
          }}
        >
          <div className="flex items-center justify-center gap-2.5" style={{ marginBottom: 24 }}>
            <div
              style={{
                width: 56,
                height: 56,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                overflow: "hidden",
                flexShrink: 0,
              }}
            >
              <img src="/favicon.ico" alt="ARI_Sniper_EA" width={44} height={44} style={{ objectFit: "contain" }} />
            </div>
            <div style={{ textAlign: "left" }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: "var(--dash-text)" }}>ARI_Sniper_EA</div>
              <div style={{ fontSize: 11, color: "var(--dash-text-dim)", marginTop: 1 }}>
                Silver Bullet · Trendline · Multi-Symbol
              </div>
            </div>
          </div>

          <h1 style={{ fontSize: 22, fontWeight: 700, color: "var(--dash-text)", margin: "0 0 8px" }}>
            Purchase Your License
          </h1>
          <p style={{ fontSize: 13, color: "var(--dash-text-muted)", margin: "0 0 24px", lineHeight: 1.5 }}>
            Request a license key to unlock the bot.
          </p>

          <button
            type="button"
            onClick={() => setPromptOpen(true)}
            className="w-full flex items-center justify-center gap-2"
            style={{
              display: "flex",
              width: "100%",
              background: "#22C55E",
              color: "#0B0E11",
              border: "none",
              borderRadius: 8,
              padding: "12px 0",
              fontSize: 14,
              fontWeight: 700,
              cursor: "pointer",
              fontFamily: "inherit",
              transition: "background 0.2s ease, color 0.2s ease, opacity 0.15s ease",
            }}
          >
            REQUEST TO BUY
          </button>

          <div className="flex items-center gap-3" style={{ margin: "18px 0", color: "var(--dash-border)", fontSize: 11 }}>
            <span style={{ flex: 1, height: 1, background: "var(--dash-border)" }} />
            or
            <span style={{ flex: 1, height: 1, background: "var(--dash-border)" }} />
          </div>

          <div style={{ fontSize: 12, color: "var(--dash-text-dim)" }}>
            Already have a key?{" "}
            <a href="/" style={{ color: "var(--dash-text-sub)", fontWeight: 600, textDecoration: "none" }}>
              Activate →
            </a>
          </div>
          <div style={{ marginTop: 18, fontSize: 11, color: "var(--dash-text-dim)", letterSpacing: ".04em" }}>
            Developed by DippsDev
          </div>
        </div>
      </div>

      <div className="activation-version" style={{ fontSize: 10, color: "var(--dash-border-light)" }}>v1.0.0</div>

      {promptOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="purchase-prompt-title"
          onClick={() => setPromptOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 50,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 20,
            background: "rgba(0,0,0,.55)",
          }}
        >
          <div
            className="activation-card"
            onClick={e => e.stopPropagation()}
            style={{
              background: "var(--dash-card-bg)",
              border: "1px solid var(--dash-border)",
              borderRadius: 12,
              maxWidth: 400,
              width: "100%",
              textAlign: "left",
              boxShadow: "0 20px 50px -20px rgba(0,0,0,.6)",
              padding: "28px 24px",
            }}
          >
            <h2
              id="purchase-prompt-title"
              style={{ fontSize: 18, fontWeight: 700, color: "var(--dash-text)", margin: "0 0 8px" }}
            >
              How to purchase
            </h2>
            <p style={{ fontSize: 13, color: "var(--dash-text-muted)", margin: "0 0 18px", lineHeight: 1.5 }}>
              Message us on WhatsApp or email to get details on how to purchase your license.
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <a href={WHATSAPP_LINK} target="_blank" rel="noopener noreferrer" style={contactBtnStyle}>
                <span style={{ fontSize: 11, fontWeight: 700, color: "#22C55E", letterSpacing: ".06em" }}>
                  WHATSAPP
                </span>
                <span style={{ fontSize: 14, fontWeight: 700, color: "var(--dash-text)" }}>
                  {WHATSAPP_DISPLAY}
                </span>
              </a>

              <a href={EMAIL_LINK} style={contactBtnStyle}>
                <span style={{ fontSize: 11, fontWeight: 700, color: "#3B82F6", letterSpacing: ".06em" }}>
                  EMAIL
                </span>
                <span style={{ fontSize: 14, fontWeight: 700, color: "var(--dash-text)" }}>
                  {EMAIL_DISPLAY}
                </span>
              </a>
            </div>

            <button
              type="button"
              onClick={() => setPromptOpen(false)}
              style={{
                display: "block",
                width: "100%",
                marginTop: 16,
                background: "transparent",
                border: "1px solid var(--dash-border)",
                borderRadius: 8,
                padding: "10px 0",
                fontSize: 13,
                fontWeight: 600,
                color: "var(--dash-text-muted)",
                cursor: "pointer",
                fontFamily: "inherit",
              }}
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
