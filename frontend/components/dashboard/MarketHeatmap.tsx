"use client";
import type { MarketReading } from "@/lib/api";

interface Props {
  readings: MarketReading[];
}

// Finviz-style treemap tile: color intensity scales with the size of the
// move (capped at +/-3%) rather than being flat green/red, so a +0.1% day
// reads as a muted tile and a +2.5% day reads as a saturated one.
function tileColor(pct: number | null): string {
  if (pct === null) return "rgba(107, 114, 128, 0.28)";
  const magnitude = Math.min(Math.abs(pct), 3) / 3;
  const alpha = 0.38 + magnitude * 0.5;
  return pct >= 0 ? `rgba(34, 197, 94, ${alpha})` : `rgba(239, 68, 68, ${alpha})`;
}

export default function MarketHeatmap({ readings }: Props) {
  const source: MarketReading[] =
    readings.length > 0 ? readings : [
      { label: "US30", price: null, change_pct: null },
      { label: "GOLD", price: null, change_pct: null },
    ];

  return (
    <div
      className="dash-card"
      style={{
        display: "flex",
        gap: 2,
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        overflow: "hidden",
        minHeight: 150,
        height: "100%",
        width: "100%",
      }}
    >
      {source.map(r => (
        <div
          key={r.label}
          style={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
            background: tileColor(r.change_pct),
            padding: 10,
            transition: "background 0.6s ease",
          }}
        >
          <span style={{ fontSize: 16, fontWeight: 800, color: "#F9FAFB", letterSpacing: ".02em" }}>
            {r.label}
          </span>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#F9FAFB" }}>
            {r.change_pct === null ? "--" : `${r.change_pct >= 0 ? "+" : ""}${r.change_pct.toFixed(2)}%`}
          </span>
          {r.price && (
            <span style={{ fontSize: 10, color: "rgba(249,250,251,0.75)" }}>{r.price}</span>
          )}
        </div>
      ))}
    </div>
  );
}
