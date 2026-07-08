"use client";
import { useEffect, useState } from "react";
import { topStory } from "@/lib/dashboardData";
import type { Stats } from "@/lib/api";

interface Props {
  stats?: Stats | null;
}

export default function TopStoryCard({ stats }: Props) {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    const update = () => setNow(new Date());
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, []);

  const headline = stats?.market_open === false
    ? "Markets are closed — bot on standby until the next session"
    : stats?.market_open === true
    ? `${stats.symbol || "US30"} live — bot scanning for Silver Bullet setups`
    : topStory.headline;

  const sub = stats?.session
    ? `Session: ${stats.session} · ${stats.connected ? "MT5 Connected" : "MT5 Disconnected"}`
    : topStory.sub;

  return (
    <div
      className="dash-card"
      style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 14,
        minHeight: 0,
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 700, color: "#EAB308", letterSpacing: ".08em" }}>BOT STATUS</div>
      <div style={{ fontSize: 26, fontWeight: 800, lineHeight: 1.15, color: "var(--dash-text)" }}>{headline}</div>
      <div style={{ fontSize: 12, color: "var(--dash-text-muted)" }}>{sub}</div>

      <div style={{ display: "flex", gap: 10, marginTop: "auto", flexWrap: "wrap" }}>
        <div
          style={{
            background: "var(--dash-card-bg-2)",
            border: "1px solid var(--dash-border)",
            borderRadius: 6,
            padding: "10px 14px",
            minWidth: 100,
          }}
        >
          <div style={{ fontSize: 10, color: "var(--dash-text-muted)", fontWeight: 600, letterSpacing: ".04em" }}>
            {stats?.symbol || "US30"}
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "var(--dash-text)", marginTop: 2 }}>
            {stats?.price ? stats.price : "--"}
          </div>
        </div>
        <div
          style={{
            background: "var(--dash-card-bg-2)",
            border: "1px solid var(--dash-border)",
            borderRadius: 6,
            padding: "10px 14px",
            minWidth: 100,
          }}
        >
          <div style={{ fontSize: 10, color: "var(--dash-text-muted)", fontWeight: 600, letterSpacing: ".04em" }}>
            {now ? now.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" }).toUpperCase() : ""}
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "var(--dash-text)", marginTop: 2 }}>
            {now ? now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }) : ""}
          </div>
        </div>
        <div
          style={{
            background: "var(--dash-card-bg-2)",
            border: "1px solid var(--dash-border)",
            borderRadius: 6,
            padding: "10px 14px",
            display: "flex",
            alignItems: "center",
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--dash-text-muted)", letterSpacing: ".04em" }}>
            {stats?.market_open === false ? "MARKET CLOSED" : stats?.market_open === true ? "MARKET OPEN" : topStory.marketStatus}
          </div>
        </div>
      </div>
    </div>
  );
}
