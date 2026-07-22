"use client";
import type { Trade } from "@/lib/api";

interface Props {
  trades: Trade[];
}

const COLS = ["Date", "Symbol", "Side", "Lots", "Entry", "Exit", "Pips", "P/L"];

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
        flex: 1,
        minHeight: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#F97316" }} />
        <span style={{ fontSize: 10, fontWeight: 800, color: "#F97316", letterSpacing: ".06em" }}>
          TRADE HISTORY · LAST 30 DAYS
        </span>
      </div>

      <div className="dark-scroll" style={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "auto" }}>
        {trades.length === 0 ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
            <span style={{ fontSize: 12, color: "var(--dash-text-dim)" }}>No closed trades in the last 30 days.</span>
          </div>
        ) : (
          <>
            {/* Mobile cards (≤768px) — a 7-column table has no room to
                compress on a phone; swap to one row of key facts per trade
                instead of forcing a tiny horizontally-scrolling grid. */}
            <div className="trade-cards">
              {trades.map((t) => (
                <div
                  key={`card-${t.id}`}
                  style={{
                    background: "var(--dash-card-bg-2)",
                    border: "1px solid var(--dash-border)",
                    borderLeft: `3px solid ${t.win ? "#22C55E" : "#EF4444"}`,
                    borderRadius: 6,
                    padding: "8px 10px",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: t.side === "BUY" ? "#22C55E" : "#EF4444" }}>
                        {t.side}
                      </span>
                      {t.symbol && (
                        <span style={{ fontSize: 11, fontWeight: 700, color: "var(--dash-text)" }}>{t.symbol}</span>
                      )}
                      <span style={{ fontSize: 11, color: "var(--dash-text-dim)" }}>{t.date}</span>
                    </div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: t.win ? "#22C55E" : "#EF4444" }}>
                      {t.pnl_text ?? t.pnl}
                    </div>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      marginTop: 6,
                      paddingTop: 6,
                      borderTop: "1px solid var(--dash-border)",
                      fontSize: 11,
                      color: "var(--dash-text-sub)",
                    }}
                  >
                    <span>{t.lots} lots</span>
                    <span>{t.entry} → {t.exit}</span>
                    <span style={{ marginLeft: "auto", color: t.win ? "#22C55E" : "#EF4444" }}>{t.pips} pips</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Desktop table (>768px). A 7-column table with width:100%
                still overflows its container on narrow screens — table
                auto-layout won't compress cell content below its natural
                size — so .tbl-wrap keeps that scroll self-contained (swipe
                to see more columns) instead of leaking out and dragging the
                whole page sideways on the odd viewport where it does show. */}
            <div className="tbl-wrap">
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr>
                    {COLS.map((c) => (
                      <th
                        key={c}
                        style={{
                          textAlign: c === "Date" || c === "Symbol" || c === "Side" ? "left" : "right",
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
                      <td style={{ padding: "6px 8px", color: "var(--dash-text)", fontWeight: 600 }}>{t.symbol ?? "—"}</td>
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
            </div>
          </>
        )}
      </div>
    </div>
  );
}
