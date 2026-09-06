"use client";
import { useState, type FormEvent } from "react";
import { apiClient } from "@/lib/api";

const FEATURES = [
  {
    title: "Silver Bullet",
    detail: "ICT sweep → FVG entries on DE30, EURUSD, GBPUSD, and XAUUSD.",
  },
  {
    title: "Trendline + Mutanabby",
    detail: "Independent H1 adapters with their own risk budgets and magic numbers.",
  },
  {
    title: "Live dashboard",
    detail: "Equity, open trades, heatmap, bot log, and start/stop from any browser.",
  },
];

const INCLUDES = [
  "All three strategy engines on one license",
  "Per-strategy risk caps and daily circuit breakers",
  "One machine activation",
  "Remote validation — key works at ar-investech.uk",
  "Setup fee is non-refundable",
];

const STEPS = [
  { n: "1", title: "Send your details", text: "Name, email, and WhatsApp so we can reach you." },
  { n: "2", title: "Pay and fund", text: "P1,500 setup + at least P300 into the bot (about P1,800)." },
  { n: "3", title: "Get your key", text: "We WhatsApp you, then email a MOJALEFA-XXXX key to activate." },
];

const fieldStyle: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  background: "var(--dash-card-bg-2)",
  border: "1px solid var(--dash-border)",
  borderRadius: 8,
  padding: "11px 14px",
  fontSize: 14,
  color: "var(--dash-text)",
  outline: "none",
  fontFamily: "inherit",
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

function PriceTile({ amount, label, accent }: { amount: string; label: string; accent?: boolean }) {
  return (
    <div
      className="dash-card"
      style={{
        background: accent ? "var(--dash-card-bg-2)" : "var(--dash-card-bg)",
        border: accent ? "1px solid #22C55E" : "1px solid var(--dash-border)",
        borderRadius: 8,
        padding: 16,
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 700, color: accent ? "#22C55E" : "var(--dash-text-muted)", letterSpacing: ".08em" }}>
        {label}
      </div>
      <div style={{ fontSize: 26, fontWeight: 800, color: "var(--dash-text)", marginTop: 6 }}>{amount}</div>
    </div>
  );
}

export default function Purchase() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [whatsapp, setWhatsapp] = useState("");
  const [broker, setBroker] = useState("");
  const [notes, setNotes] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (loading) return;
    const digits = whatsapp.replace(/\D/g, "");
    if (!name.trim() || !email.trim() || !whatsapp.trim()) {
      setError("Name, email, and WhatsApp number are required.");
      return;
    }
    if (digits.length < 7) {
      setError("Enter a WhatsApp number we can reach you on.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await apiClient.requestLicense({
        name: name.trim(),
        email: email.trim(),
        whatsapp: whatsapp.trim(),
        broker: broker.trim(),
        notes: notes.trim(),
      });
      if (res.ok) setSent(true);
      else setError(res.error ?? "Could not send the request. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="purchase-screen">
      <div className="purchase-wrap">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 28 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <img src="/favicon.ico" alt="" width={36} height={36} style={{ objectFit: "contain" }} />
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: "var(--dash-text)" }}>ARI_Sniper_EA</div>
              <div style={{ fontSize: 11, color: "var(--dash-text-dim)" }}>Silver Bullet · Trendline · Multi-Symbol</div>
            </div>
          </div>
          <a href="/" style={{ fontSize: 12, fontWeight: 600, color: "var(--dash-text-muted)", textDecoration: "none" }}>
            ← Already have a key? Activate
          </a>
        </div>

        <div style={{ marginBottom: 22 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#EAB308", letterSpacing: ".08em", marginBottom: 8 }}>
            LICENSE
          </div>
          <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--dash-text)", margin: "0 0 8px", lineHeight: 1.2 }}>
            Purchase ARI_Sniper_EA
          </h1>
          <p style={{ fontSize: 14, color: "var(--dash-text-muted)", margin: 0, lineHeight: 1.55, maxWidth: 620 }}>
            Setup is <strong style={{ color: "var(--dash-text-sub)" }}>P1,500</strong>. The bot also needs a{" "}
            <strong style={{ color: "var(--dash-text-sub)" }}>P300 minimum deposit</strong>. Budget about{" "}
            <strong style={{ color: "var(--dash-text-sub)" }}>P1,800</strong> to get a license key. After you request, we WhatsApp you to arrange payment.
          </p>
        </div>

        <div className="purchase-pricing">
          <PriceTile amount="P 1,500" label="SETUP FEE" />
          <PriceTile amount="P 300" label="MINIMUM DEPOSIT" />
          <PriceTile amount="≈ P 1,800" label="TOTAL TO GET A KEY" accent />
        </div>
        <p style={{ fontSize: 12, color: "var(--dash-text-dim)", margin: "-4px 0 16px", lineHeight: 1.5 }}>
          The P1,500 setup fee is non-refundable once paid.
        </p>

        <div className="purchase-features">
          {FEATURES.map(f => (
            <div key={f.title} className="dash-card" style={{
              background: "var(--dash-card-bg)",
              border: "1px solid var(--dash-border)",
              borderRadius: 8,
              padding: 16,
            }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--dash-text)", marginBottom: 6 }}>{f.title}</div>
              <div style={{ fontSize: 12, color: "var(--dash-text-muted)", lineHeight: 1.5 }}>{f.detail}</div>
            </div>
          ))}
        </div>

        <div className="purchase-body">
          <div className="dash-card" style={{
            background: "var(--dash-card-bg)",
            border: "1px solid var(--dash-border)",
            borderRadius: 10,
            padding: 20,
          }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: "var(--dash-text-muted)", letterSpacing: ".08em", marginBottom: 10 }}>
              WHAT YOU GET
            </div>
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 10 }}>
              {INCLUDES.map(item => (
                <li key={item} style={{ display: "flex", gap: 10, fontSize: 13, color: "var(--dash-text-sub)", lineHeight: 1.45 }}>
                  <span style={{ color: "#22C55E", fontWeight: 800, flexShrink: 0 }}>✓</span>
                  {item}
                </li>
              ))}
            </ul>
            <div className="purchase-steps" style={{ marginTop: 18, display: "flex", flexWrap: "wrap", gap: 10 }}>
              {STEPS.map(s => (
                <div key={s.n} style={{ flex: "1 1 140px", minWidth: 0 }}>
                  <div style={{ fontSize: 11, fontWeight: 800, color: "#22C55E", marginBottom: 4 }}>{s.n}. {s.title}</div>
                  <div style={{ fontSize: 11, color: "var(--dash-text-dim)", lineHeight: 1.4 }}>{s.text}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="dash-card" style={{
            background: "var(--dash-card-bg)",
            border: "1px solid var(--dash-border)",
            borderRadius: 10,
            padding: 20,
          }}>
            {sent ? (
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: "var(--dash-text)", marginBottom: 8 }}>Request sent</div>
                <p style={{ fontSize: 13, color: "var(--dash-text-muted)", lineHeight: 1.55, margin: "0 0 16px" }}>
                  We will WhatsApp you on <strong style={{ color: "var(--dash-text-sub)" }}>{whatsapp}</strong> to arrange the P1,500 setup and P300 minimum deposit. Your MOJALEFA-XXXX key follows after that.
                </p>
                <a
                  href="/"
                  style={{
                    display: "inline-flex",
                    background: "#22C55E",
                    color: "#0B0E11",
                    borderRadius: 8,
                    padding: "11px 16px",
                    fontSize: 13,
                    fontWeight: 700,
                    textDecoration: "none",
                  }}
                >
                  Go to Activation
                </a>
              </div>
            ) : (
              <form onSubmit={submit}>
                <div style={{ fontSize: 10, fontWeight: 700, color: "var(--dash-text-muted)", letterSpacing: ".08em", marginBottom: 14 }}>
                  REQUEST A LICENSE
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div>
                    <label style={labelStyle}>Full name</label>
                    <input className="act-input" value={name} onChange={e => { setName(e.target.value); setError(""); }} style={fieldStyle} autoComplete="name" />
                  </div>
                  <div>
                    <label style={labelStyle}>Email</label>
                    <input className="act-input" type="email" value={email} onChange={e => { setEmail(e.target.value); setError(""); }} style={fieldStyle} autoComplete="email" />
                  </div>
                  <div>
                    <label style={labelStyle}>WhatsApp number</label>
                    <input
                      className="act-input"
                      type="tel"
                      value={whatsapp}
                      onChange={e => { setWhatsapp(e.target.value); setError(""); }}
                      style={fieldStyle}
                      autoComplete="tel"
                      placeholder="+267 7X XXX XXX"
                    />
                  </div>
                  <div>
                    <label style={labelStyle}>MT5 broker <span style={{ fontWeight: 500, letterSpacing: 0, textTransform: "none" }}>(optional)</span></label>
                    <input className="act-input" value={broker} onChange={e => setBroker(e.target.value)} style={fieldStyle} />
                  </div>
                  <div>
                    <label style={labelStyle}>Notes <span style={{ fontWeight: 500, letterSpacing: 0, textTransform: "none" }}>(optional)</span></label>
                    <textarea
                      className="act-input"
                      value={notes}
                      onChange={e => setNotes(e.target.value)}
                      rows={3}
                      style={{ ...fieldStyle, resize: "vertical", minHeight: 72 }}
                    />
                  </div>
                </div>
                {error && <div style={{ color: "#F87171", fontSize: 12, marginTop: 10 }}>{error}</div>}
                <button
                  type="submit"
                  disabled={loading}
                  style={{
                    width: "100%",
                    marginTop: 16,
                    background: "#22C55E",
                    color: "#0B0E11",
                    border: "none",
                    borderRadius: 8,
                    padding: "12px 0",
                    fontSize: 14,
                    fontWeight: 700,
                    cursor: loading ? "default" : "pointer",
                    fontFamily: "inherit",
                    opacity: loading ? 0.6 : 1,
                  }}
                >
                  {loading ? "Sending…" : "Request license"}
                </button>
                <div style={{ marginTop: 10, fontSize: 11, color: "var(--dash-text-dim)", textAlign: "center", lineHeight: 1.45 }}>
                  Sends your details — including WhatsApp — to dippsinbox@gmail.com
                </div>
              </form>
            )}
          </div>
        </div>

        <div style={{ marginTop: 28, fontSize: 11, color: "var(--dash-text-dim)", letterSpacing: ".04em" }}>
          Developed by DippsDev
        </div>
      </div>
    </div>
  );
}
