"use client";
import { useMemo, useState } from "react";
import SvgAreaChart from "./SvgAreaChart";
import type { Book } from "@/lib/dashboardData";

interface Props {
  book: Book;
}

const PERIODS = ["1D", "1W", "1M", "1Y"] as const;

// Seeded pseudo-random so SSR and client render identical data for the same inputs.
function mulberry32(seed: number) {
  return function () {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function generateSeries(base: number, period: (typeof PERIODS)[number], label: string) {
  const counts = { "1D": 24, "1W": 7, "1M": 30, "1Y": 52 };
  const count = counts[period];
  const volatility = period === "1D" ? 0.002 : period === "1W" ? 0.008 : period === "1M" ? 0.015 : 0.04;
  const seed = label.split("").reduce((acc, c) => acc + c.charCodeAt(0), 0) + period.length * 997;
  const rand = mulberry32(seed);
  const out: number[] = [];
  let current = base;
  for (let i = 0; i < count; i++) {
    const change = (rand() - 0.48) * current * volatility;
    current += change;
    out.push(current);
  }
  return out;
}

export default function BookCard({ book }: Props) {
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("1D");
  const isUp = book.todayChange >= 0;

  const data = useMemo(() => generateSeries(book.value, period, book.label), [book.value, period, book.label]);

  return (
    <div
      className="dash-card"
      style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", rowGap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: "var(--dash-text-muted)", letterSpacing: ".08em" }}>
            {book.label}
          </span>
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: "#111827",
              background: "#F3F4F6",
              padding: "2px 8px",
              borderRadius: 4,
            }}
          >
            CASH ${book.cash.toLocaleString()}
          </span>
        </div>
        <div className="book-periods" style={{ display: "flex", gap: 4 }}>
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              style={{
                fontSize: 10,
                fontWeight: 700,
                padding: "3px 8px",
                borderRadius: 4,
                border: "none",
                cursor: "pointer",
                background: period === p ? "var(--dash-text-muted)" : "transparent",
                color: period === p ? "#111827" : "var(--dash-text-dim)",
                transition: "background 0.15s, color 0.15s",
              }}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span style={{ fontSize: 28, fontWeight: 800, color: "var(--dash-text)" }}>
          ${book.value.toLocaleString()}
        </span>
        <span style={{ fontSize: 12, fontWeight: 600, color: isUp ? "#22C55E" : "#EF4444" }}>
          {isUp ? "+" : ""}${book.todayChange.toFixed(2)} ({isUp ? "+" : ""}
          {book.todayChangePct.toFixed(2)}%) today
        </span>
      </div>

      <div style={{ marginTop: "auto" }}>
        <SvgAreaChart data={data} color={book.color} />
      </div>
    </div>
  );
}
