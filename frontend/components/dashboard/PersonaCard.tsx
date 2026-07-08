"use client";
import type { Persona } from "@/lib/personas";
import PixelAvatar from "./PixelAvatar";

interface Props {
  persona: Persona;
  badge?: { text: string; color: string };
  note: string;
  time?: string;
  active?: boolean;
}

export default function PersonaCard({ persona, badge, note, time, active }: Props) {
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
        alignItems: "center",
        gap: 10,
        textAlign: "center",
        minWidth: 0,
      }}
    >
      <div className="persona-avatar-box">
        <PixelAvatar persona={persona} size={128} active={active} />
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: "var(--dash-text)" }}>{persona.name}</span>
        {badge && (
          <span
            style={{
              fontSize: 9,
              fontWeight: 800,
              color: "#0B0E11",
              background: badge.color,
              padding: "2px 7px",
              borderRadius: 4,
              letterSpacing: ".03em",
              whiteSpace: "nowrap",
            }}
          >
            {badge.text}
          </span>
        )}
      </div>
      <div style={{ fontSize: 10, color: "var(--dash-text-dim)" }}>{persona.role}</div>

      <div
        style={{
          width: "100%",
          background: "var(--dash-card-bg-2)",
          border: "1px solid var(--dash-border)",
          borderRadius: 6,
          padding: "8px 10px",
          textAlign: "left",
        }}
      >
        {time && <div style={{ fontSize: 9, color: "var(--dash-text-dim)", marginBottom: 4 }}>{time}</div>}
        <div style={{ fontSize: 11, color: "var(--dash-text-sub)", lineHeight: 1.45 }}>{note}</div>
      </div>
    </div>
  );
}
