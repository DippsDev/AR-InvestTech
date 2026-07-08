"use client";
import { calendarEvents as defaultEvents } from "@/lib/dashboardData";
import type { CalendarEvent } from "@/lib/dashboardData";
import InfiniteMarquee from "./InfiniteMarquee";

interface Props {
  events?: CalendarEvent[];
}

function EventCard({ evt }: { evt: CalendarEvent }) {
  return (
    <div
      className="dash-card"
      style={{
        flex: "0 0 auto",
        width: 320,
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        padding: 14,
        display: "flex",
        gap: 12,
        minHeight: 110,
      }}
    >
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minWidth: 44,
          background: "var(--dash-card-bg-2)",
          borderRadius: 6,
          padding: "8px 0",
        }}
      >
        <span style={{ fontSize: 9, fontWeight: 800, color: "var(--dash-text-dim)", letterSpacing: ".04em" }}>
          {evt.weekday}
        </span>
        <span style={{ fontSize: 18, fontWeight: 800, color: "var(--dash-text)" }}>{evt.day}</span>
      </div>
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "var(--dash-text)", flex: 1 }}>{evt.title}</span>
          {evt.tag && (
            <span
              style={{
                fontSize: 8,
                fontWeight: 800,
                color: "#FFFFFF",
                background: evt.tagColor || "#374151",
                padding: "2px 5px",
                borderRadius: 3,
                letterSpacing: ".03em",
                whiteSpace: "nowrap",
              }}
            >
              {evt.tag}
            </span>
          )}
        </div>
        <div style={{ fontSize: 11, color: "var(--dash-text-muted)", lineHeight: 1.4, whiteSpace: "pre-line" }}>
          {evt.detail}
        </div>
      </div>
    </div>
  );
}

export default function EventCalendar({ events }: Props) {
  const source = events && events.length > 0 ? events : defaultEvents;

  return (
    <div
      style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        padding: "12px 0 12px 14px",
      }}
    >
      <InfiniteMarquee
        speed={40}
        gap={12}
        items={source.map((evt, i) => (
          <EventCard key={`${evt.title}-${i}`} evt={evt} />
        ))}
      />
    </div>
  );
}
