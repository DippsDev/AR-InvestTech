"use client";
import { useState } from "react";
import type { LogEntry } from "@/lib/api";

interface Props {
  running: boolean;
  log: LogEntry[];
  tick: number;
  floatPnl: string;
  nextRefresh: string;
}

function Card({ label, value, note, noteGreen }: { label: string; value: string; note?: string; noteGreen?: boolean }) {
  return (
    <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, padding: "14px 16px" }}>
      <div style={{ fontSize: 10, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: "#111827", lineHeight: 1 }}>{value}</div>
      {note && <div style={{ fontSize: 10, color: noteGreen ? "#16A34A" : "#9CA3AF", marginTop: 4 }}>{note}</div>}
    </div>
  );
}

function tagColor(k: LogEntry["k"]) {
  if (k === "win") return "#22C55E";
  if (k === "sig") return "#60A5FA";
  return "#9CA3AF";
}

function ExpandIcon() {
  return (
    <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
      <polyline points="15 3 21 3 21 9" />
      <polyline points="9 21 3 21 3 15" />
      <line x1="21" y1="3" x2="14" y2="10" />
      <line x1="3" y1="21" x2="10" y2="14" />
    </svg>
  );
}

function CompressIcon() {
  return (
    <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
      <polyline points="4 14 10 14 10 20" />
      <polyline points="20 10 14 10 14 4" />
      <line x1="10" y1="14" x2="3" y2="21" />
      <line x1="14" y1="10" x2="21" y2="3" />
    </svg>
  );
}

export default function Dashboard({ running, log, tick, floatPnl, nextRefresh }: Props) {
  const [logExpanded, setLogExpanded] = useState(false);

  const now = new Date().toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  const clock = new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const logReversed = [...log].reverse();

  const equity = running
    ? `$4,2${(37 + (tick % 12)).toString()}.00`
    : "$4,208.60";

  const openPillStyle = running
    ? { color: "#16A34A", background: "#DCFCE7", padding: "2px 8px", borderRadius: 4 }
    : { color: "#6B7280", background: "#F3F4F6", padding: "2px 8px", borderRadius: 4 };

  const logCardStyle: React.CSSProperties = logExpanded
    ? {
        position: "absolute",
        top: 0, left: 0, right: 0, bottom: 0,
        zIndex: 20,
        borderRadius: 0,
        background: "#FFFFFF",
        border: "none",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }
    : {
        background: "#FFFFFF",
        border: "1px solid #E5E7EB",
        borderRadius: 8,
        overflow: "hidden",
        flex: 1,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
      };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, minHeight: "calc(100svh - 80px)" }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#111827" }}>Dashboard</div>
          <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>{now} — London Session Active</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#6B7280" }}>
          <span style={{ background: "#111827", color: "#FFFFFF", padding: "3px 10px", borderRadius: 4, fontSize: 11, fontWeight: 700, letterSpacing: ".05em" }}>US30</span>
          <span className="mob-hide-inline">MT5 Connected · {clock}</span>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid-4">
        <Card label="Balance"     value="$4,208.60" note={`Equity ${equity}`} />
        <Card label="Today P&L"   value="+$84.50"   note="▲ +2.01%" noteGreen />
        <Card label="Win Rate"    value="68%"        note="Last 30 days" />
        <Card label="Open Trades" value={running ? "1" : "0"} note="Max 2 allowed" />
      </div>

      {/* Active trade + Session info */}
      <div className="grid-2">

        {/* Active trade */}
        <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid #E5E7EB", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#111827", textTransform: "uppercase", letterSpacing: ".05em" }}>Active Trade</span>
            <span style={{ fontSize: 11, fontWeight: 600, ...openPillStyle }}>{running ? "OPEN" : "FLAT"}</span>
          </div>
          <div style={{ padding: "14px 16px" }}>
            {running ? (
              <>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 10px", fontSize: 12 }}>
                  <div>
                    <div style={{ color: "#9CA3AF", fontSize: 10, textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 2 }}>Symbol / Side</div>
                    <div style={{ fontWeight: 600, color: "#111827" }}>US30 · <span style={{ color: "#16A34A" }}>BUY</span></div>
                  </div>
                  <div>
                    <div style={{ color: "#9CA3AF", fontSize: 10, textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 2 }}>Float P&L</div>
                    <div style={{ fontWeight: 700, color: "#16A34A" }}>{floatPnl}</div>
                  </div>
                  <div>
                    <div style={{ color: "#9CA3AF", fontSize: 10, textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 2 }}>Entry</div>
                    <div style={{ fontWeight: 600, color: "#111827" }}>42,318.4</div>
                  </div>
                  <div>
                    <div style={{ color: "#9CA3AF", fontSize: 10, textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 2 }}>Stop / Target</div>
                    <div style={{ fontWeight: 600 }}>
                      <span style={{ color: "#DC2626" }}>42,288.4</span> / <span style={{ color: "#16A34A" }}>42,368.4</span>
                    </div>
                  </div>
                </div>
                <div style={{ marginTop: 12, fontSize: 11, color: "#6B7280", display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#FBBF24", display: "inline-block" }} />
                  Breakeven set · Trailing active · Lot 0.08 · US30
                </div>
              </>
            ) : (
              <div style={{ textAlign: "center", padding: "18px 0", color: "#9CA3AF" }}>
                <svg width="28" height="28" fill="none" stroke="#D1D5DB" strokeWidth="1.6" viewBox="0 0 24 24" style={{ marginBottom: 8, display: "block", margin: "0 auto 8px" }}>
                  <circle cx="12" cy="12" r="9" /><path d="M12 8v4l2.5 1.5" />
                </svg>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#6B7280" }}>No open positions</div>
                <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 2 }}>Start the bot to begin scanning for signals</div>
              </div>
            )}
          </div>
        </div>

        {/* Session info */}
        <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid #E5E7EB" }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#111827", textTransform: "uppercase", letterSpacing: ".05em" }}>Session Info</span>
          </div>
          <div style={{ padding: "14px 16px" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, fontSize: 12 }}>
              {([
                ["Session",        "London",          ""],
                ["Timeframes",     "M5 / H1",         ""],
                ["AI Signal",      "BULLISH",         "#16A34A"],
                ["Daily Cap Used", "1.01% / 3%",      ""],
                ["Risk / Trade",   "1%",              ""],
                ["Next AI Refresh", nextRefresh,      ""],
              ] as [string, string, string][]).map(([lbl, val, color]) => (
                <div key={lbl}>
                  <div style={{ color: "#9CA3AF", fontSize: 10, textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 2 }}>{lbl}</div>
                  <div style={{ fontWeight: 600, color: color || "#111827" }}>{val}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Live log */}
      <div className={logExpanded ? "log-expand-anim" : undefined} style={logCardStyle}>
        {/* Header — clicking anywhere here toggles expand */}
        <div
          onClick={() => setLogExpanded(e => !e)}
          style={{
            padding: "12px 16px",
            borderBottom: "1px solid #E5E7EB",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            cursor: "pointer",
            userSelect: "none",
            flexShrink: 0,
          }}
        >
          <span style={{ fontSize: 12, fontWeight: 600, color: "#111827", textTransform: "uppercase", letterSpacing: ".05em" }}>Live Log</span>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 11, color: "#9CA3AF" }}>{running ? "streaming · live" : "paused"}</span>
            <span style={{ color: "#9CA3AF", display: "flex" }}>
              {logExpanded ? <CompressIcon /> : <ExpandIcon />}
            </span>
          </div>
        </div>

        {/* Log content — fills remaining height */}
        <div className="dark-scroll" style={{
          fontFamily: "ui-monospace, Consolas, monospace",
          fontSize: 11,
          background: "#111827",
          color: "#D1D5DB",
          padding: "12px 14px",
          flex: 1,
          overflowY: "auto",
          lineHeight: 1.7,
          minHeight: 0,
        }}>
          {logReversed.map((e, i) => (
            <div key={i} className="animate-row-in">
              <span style={{ color: "#6B7280" }}>{e.t}</span>{" "}
              <span style={{ fontWeight: 600, color: tagColor(e.k) }}>{e.tag}</span>{" "}
              {e.x}
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
