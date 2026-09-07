"use client";

const BUY_MAIL =
  "mailto:dippsinbox@gmail.com"
  + "?subject=" + encodeURIComponent("ARI_Sniper_EA license request")
  + "&body=" + encodeURIComponent(
    "Hi,\n\nI would like to purchase an ARI_Sniper_EA license.\n\n"
    + "Name:\nWhatsApp:\nBroker (optional):\n\nThank you.",
  );

export default function Purchase() {
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

          <a
            href={BUY_MAIL}
            className="w-full flex items-center justify-center gap-2"
            style={{
              display: "flex",
              background: "#22C55E",
              color: "#0B0E11",
              border: "none",
              borderRadius: 8,
              padding: "12px 0",
              fontSize: 14,
              fontWeight: 700,
              cursor: "pointer",
              fontFamily: "inherit",
              textDecoration: "none",
              transition: "background 0.2s ease, color 0.2s ease, opacity 0.15s ease",
            }}
          >
            REQUEST TO BUY
          </a>

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
    </div>
  );
}
