"use client";
import { useEffect, useState } from "react";

interface Props {
  message: string | null;
  onDone: () => void;
}

export default function Toast({ message, onDone }: Props) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!message) return;
    setVisible(true);
    const t = setTimeout(() => { setVisible(false); setTimeout(onDone, 200); }, 2200);
    return () => clearTimeout(t);
  }, [message, onDone]);

  if (!message) return null;

  return (
    <div style={{
      position: "fixed",
      bottom: "calc(18px + env(safe-area-inset-bottom, 0px))",
      left: 0,
      right: 0,
      display: "flex",
      justifyContent: "center",
      pointerEvents: "none",
      zIndex: 50,
    }}>
      <div style={{
        background: "#111827",
        color: "#FFFFFF",
        fontSize: 12,
        fontWeight: 600,
        padding: "10px 18px",
        borderRadius: 8,
        boxShadow: "0 8px 24px -6px rgba(0,0,0,.4)",
        display: "flex",
        alignItems: "center",
        gap: 8,
        pointerEvents: "auto",
        opacity: visible ? 1 : 0,
        transition: "opacity .2s",
        animation: "arb-fade .3s ease",
        whiteSpace: "nowrap",
      }}>
        <svg width="14" height="14" fill="none" stroke="#22C55E" strokeWidth="2.5" viewBox="0 0 24 24">
          <polyline points="20 6 9 17 4 12" />
        </svg>
        {message}
      </div>
    </div>
  );
}
