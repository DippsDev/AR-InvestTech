"use client";
import type { LogEntry } from "@/lib/api";
import { personaFor } from "@/lib/personas";
import { withReactions } from "@/lib/reactions";
import PixelAvatar from "./PixelAvatar";

interface Props {
  log: LogEntry[];
  running: boolean;
}

export default function BotLog({ log, running }: Props) {
  return (
    <div
      className="dash-card"
      style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        display: "flex",
        flexDirection: "column",
        flex: 1,
        minHeight: 0,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "12px 14px",
          borderBottom: "1px solid var(--dash-border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 700, color: "var(--dash-text)", letterSpacing: ".04em" }}>
          Bot Activity
        </span>
      </div>
      <div
        className="dark-scroll"
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "12px 14px",
          display: "flex",
          flexDirection: "column",
          gap: 10,
        }}
      >
        {log.length === 0 ? (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <span style={{ fontSize: 12, color: "var(--dash-text-dim)" }}>No activity yet.</span>
          </div>
        ) : (
          withReactions(log).map((entry, i) => {
            const persona = personaFor(entry.speaker);
            const synthetic = entry.synthetic === true;
            return (
              <div
                key={i}
                style={{
                  display: "flex",
                  gap: 8,
                  marginLeft: synthetic ? 20 : 0,
                  opacity: synthetic ? 0.8 : 1,
                  background: "rgba(255,255,255,0.03)",
                  borderLeft: `3px solid ${persona.color}`,
                  borderRadius: 6,
                  padding: "8px 10px",
                }}
              >
                <PixelAvatar persona={persona} size={synthetic ? 24 : 32} active={running} />
                <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0, flex: 1 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: persona.color }}>{persona.name}</span>
                      {synthetic ? (
                        <span style={{ fontSize: 9, fontWeight: 700, color: "var(--dash-text-dim)" }}>↳ reply</span>
                      ) : (
                        <span
                          style={{
                            fontSize: 8,
                            fontWeight: 800,
                            color: "var(--dash-text-dim)",
                            border: "1px solid var(--dash-border)",
                            padding: "1px 5px",
                            borderRadius: 3,
                            letterSpacing: ".03em",
                          }}
                        >
                          {entry.tag}
                        </span>
                      )}
                    </div>
                    {!synthetic && (
                      <span style={{ fontSize: 9, color: "var(--dash-text-dim)", whiteSpace: "nowrap" }}>{entry.t}</span>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--dash-text-sub)", lineHeight: 1.45 }}>{entry.x}</div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
