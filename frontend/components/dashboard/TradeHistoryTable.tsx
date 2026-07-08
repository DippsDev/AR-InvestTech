"use client";
import type { Trade } from "@/lib/api";

interface Props {
  trades: Trade[];
}

const COLS = ["Date", "Side", "Lots", "Entry", "Exit", "Pips", "P/L"];

export default function TradeHistoryTable({ trades }: Props) {
  return (
    <div
      className="dash-card"
      style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        padding: 12,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        height: "100%",
        minHeight: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#F97316" }} />
        <span style={{ fontSize: 10, fontWeight: 800, color: "#F97316", letterSpacing: ".06em" }}>
          TRADE HISTORY · LAST 30 DAYS
        </span>
      </div>

      <div className="dark-scroll" style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {trades.length === 0 ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
            <span style={{ fontSize: 12, color: "var(--dash-text-dim)" }}>No closed trades in the last 30 days.</span>
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                {COLS.map((c) => (
                  <th
                    key={c}
                    style={{
                      textAlign: c === "Date" || c === "Side" ? "left" : "right",
                      padding: "4px 8px",
                      fontSize: 10,
                      fontWeight: 700,
                      color: "var(--dash-text-muted)",
                      letterSpacing: ".04em",
                      borderBottom: "1px solid var(--dash-border)",
                    }}
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id} style={{ borderLeft: `3px solid ${t.win ? "#22C55E" : "#EF4444"}` }}>
                  <td style={{ padding: "6px 8px", color: "var(--dash-text)" }}>{t.date}</td>
                  <td style={{ padding: "6px 8px", color: t.side === "BUY" ? "#22C55E" : "#EF4444", fontWeight: 700 }}>
                    {t.side}
                  </td>
                  <td style={{ padding: "6px 8px", textAlign: "right", color: "var(--dash-text-sub)" }}>{t.lots}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right", color: "var(--dash-text-sub)" }}>{t.entry}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right", color: "var(--dash-text-sub)" }}>{t.exit}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right", color: "var(--dash-text-sub)" }}>{t.pips}</td>
                  <td
                    style={{
                      padding: "6px 8px",
                      textAlign: "right",
                      fontWeight: 700,
                      color: t.win ? "#22C55E" : "#EF4444",
                    }}
                  >
                    {t.pnl_text ?? t.pnl}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
