"use client";
import { useEffect, useRef, useState } from "react";
import type { Stats } from "@/lib/api";
import InfiniteMarquee from "./InfiniteMarquee";

interface Props {
  running: boolean;
  stats: Stats | null;
  onOpenSettings: () => void;
  onDisconnect: () => void;
  onStartBot: () => Promise<void>;
  onStopBot: () => Promise<void>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
      <span style={{ fontWeight: 700, color: "var(--dash-text)" }}>{label}</span>
      <span style={{ color: "var(--dash-text-muted)" }}>{value}</span>
    </div>
  );
}

function MenuButton({ onOpenSettings, onDisconnect }: Pick<Props, "onOpenSettings" | "onDisconnect">) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const item = (label: string, onClick: () => void, danger = false) => (
    <button
      className="menu-item"
      onClick={() => { setOpen(false); onClick(); }}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        background: "transparent",
        border: "none",
        padding: "9px 14px",
        fontSize: 12,
        fontWeight: 600,
        color: danger ? "#F87171" : "var(--dash-text-sub)",
        cursor: "pointer",
        fontFamily: "inherit",
      }}
    >
      {label}
    </button>
  );

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(o => !o)}
        aria-label="Menu"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 26,
          height: 26,
          background: open ? "var(--dash-card-bg-2)" : "transparent",
          border: "1px solid var(--dash-border)",
          borderRadius: 6,
          cursor: "pointer",
          flexShrink: 0,
        }}
      >
        <svg width="14" height="14" fill="none" stroke="var(--dash-text-sub)" strokeWidth="2" strokeLinecap="round" viewBox="0 0 24 24">
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            minWidth: 170,
            background: "var(--dash-card-bg)",
            border: "1px solid var(--dash-border)",
            borderRadius: 8,
            boxShadow: "0 12px 30px -10px rgba(0,0,0,.5)",
            overflow: "hidden",
            zIndex: 20,
          }}
        >
          {item("Settings & Account", onOpenSettings)}
          {item("Disconnect", onDisconnect, true)}
        </div>
      )}
    </div>
  );
}

function TradeToggle({ running, onStartBot, onStopBot }: Pick<Props, "running" | "onStartBot" | "onStopBot">) {
  const [busy, setBusy] = useState(false);

  const handleClick = async () => {
    setBusy(true);
    try {
      await (running ? onStopBot() : onStartBot());
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={busy}
      style={{
        fontSize: 9,
        fontWeight: 800,
        color: running ? "#111827" : "#0B0E11",
        background: running ? "#22C55E" : "#EAB308",
        padding: "3px 9px",
        borderRadius: 4,
        letterSpacing: ".04em",
        border: "none",
        fontFamily: "inherit",
        cursor: busy ? "default" : "pointer",
        opacity: busy ? 0.6 : 1,
      }}
    >
      {busy ? "…" : running ? "LIVE" : "TRADE"}
    </button>
  );
}

export default function TickerBar({ running, stats, onOpenSettings, onDisconnect, onStartBot, onStopBot }: Props) {
  // One fact per uniquely-traded symbol. A name that appears on more than
  // one strategy (same price) only needs one tile here.
  const symbolFacts: { label: string; value: string }[] = [];
  const seen = new Set<string>();
  for (const s of stats?.active_symbols ?? []) {
    if (seen.has(s.symbol)) continue;
    seen.add(s.symbol);
    symbolFacts.push({ label: s.symbol, value: s.price ?? "--" });
  }

  const facts: { label: string; value: string }[] = stats
    ? [
        { label: "BALANCE", value: stats.balance },
        { label: "EQUITY", value: stats.equity },
        { label: "P/L", value: stats.profit },
        ...symbolFacts,
        { label: "SESSION", value: stats.session },
      ]
    : [{ label: "STATUS", value: "Connecting…" }];

  return (
    <div
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        height: 40,
        background: "var(--dash-ticker-bg)",
        borderBottom: "1px solid var(--dash-border)",
        fontSize: 12,
        whiteSpace: "nowrap",
        // This bar is a flex item in Dashboard's column flex container.
        // Flex items default to min-width:auto, which refuses to shrink
        // below their content's intrinsic width — align-items:stretch alone
        // doesn't override that, so the marquee's long unwrapped ticker text
        // was forcing this whole bar (and the page) wider than the viewport.
        minWidth: 0,
        // An explicit percentage width is a much harder constraint than
        // relying on flex-grow math alone — it resolves against the parent
        // regardless of how the marquee child's content-based sizing behaves,
        // where min-width:0 + flex:1 alone was still intermittently losing
        // to it in WebKit.
        width: "100%",
        // No overflow clip on this element itself: per the CSS overflow
        // interop rule, setting overflow-x to anything but visible forces
        // the UA to compute overflow-y as auto too (it can't be "visible on
        // one axis, clipped on the other" on the same box) — and this box
        // also contains the MenuButton dropdown, which must render below
        // the bar's own height uncropped. The horizontal backstop for the
        // marquee's transient over-measurement lives on the marquee's own
        // wrapper below instead, where clipping vertically doesn't matter.
      }}
    >
      {/* Static left labels — solid background so scrolling data passes behind */}
      <div
        className="ticker-static"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 24,
          padding: "0 16px",
          background: "var(--dash-ticker-bg)",
          zIndex: 2,
          flexShrink: 0,
        }}
      >
        <MenuButton onOpenSettings={onOpenSettings} onDisconnect={onDisconnect} />
        <span className="ticker-detail" style={{ color: "var(--dash-text)", fontWeight: 700 }}>
          {stats?.equity ?? "--"}
        </span>
        <span className="ticker-detail" style={{ color: stats?.profit?.startsWith("-") ? "#EF4444" : "#22C55E" }}>
          {stats?.profit ?? "--"}
        </span>
        <TradeToggle running={running} onStartBot={onStartBot} onStopBot={onStopBot} />
      </div>

      {/* Scrolling ticker track in the remaining width. maxWidth is a hard
          backstop: the marquee measures its own width via ResizeObserver and
          can transiently compute a too-wide value (observably flaky in
          WebKit) before settling — clip at this element's own boundary
          (InfiniteMarquee already sets overflow:hidden on its root) so that
          race can never expand the page. Scoped to just the marquee, not the
          whole bar, so it can't clip the MenuButton dropdown next to it. */}
      <InfiniteMarquee
        style={{ flex: 1, minWidth: 0, maxWidth: "100%" }}
        speed={45}
        gap={24}
        items={facts.map((f, i) => (
          <Fact key={`${f.label}-${i}`} label={f.label} value={f.value} />
        ))}
      />
    </div>
  );
}
