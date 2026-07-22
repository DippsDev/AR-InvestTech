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

// Loading-state placeholder — mirrors the backend's real top-3-per-strategy
// target list (see multi_symbol_targets.py) so the skeleton doesn't promise
// tiles that won't actually show up once data loads.
const PLACEHOLDER_SYMBOLS = ["DE30m", "EURUSDm", "GBPUSDm", "USDJPYm", "USTECm"];

export default function MarketHeatmap({ readings }: Props) {
  const source: MarketReading[] =
    readings.length > 0 ? readings : PLACEHOLDER_SYMBOLS.map(label => (
      { label, price: null, change_pct: null }
    ));

  return (
    <div
      className="dash-card"
      style={{
        display: "flex",
        // Wrap instead of forcing every tile into one unbreakable row — with
        // 5+ symbols (vs. the old fixed US30/GOLD pair) a single row has no
        // way to stay legible on a phone-width screen; each tile keeps a
        // sane minimum width and wraps onto additional rows once it runs out
        // of horizontal room, at any viewport size.
        flexWrap: "wrap",
        gap: 2,
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        overflow: "hidden",
        minHeight: 150,
        width: "100%",
      }}
    >
      {source.map(r => (
        <div
          key={r.label}
          style={{
            flex: "1 1 110px",
            minWidth: 90,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
            background: tileColor(r.change_pct),
            padding: "10px 6px",
            transition: "background 0.6s ease",
          }}
        >
          <span
            style={{
              fontSize: 15,
              fontWeight: 800,
              color: "#F9FAFB",
              letterSpacing: ".02em",
              maxWidth: "100%",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
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
