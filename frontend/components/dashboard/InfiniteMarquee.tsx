"use client";
import { useEffect, useRef, useState } from "react";

interface Props {
  items: React.ReactNode[];
  speed?: number; // px/sec
  gap?: number;
  className?: string;
  style?: React.CSSProperties;
}

// Classic "duplicate + translateX(-50%)" marquees only stay seamless while
// one copy of the content is at least as wide as the visible track — once
// the track gets wider than the content (a bigger monitor, fewer live
// items), the animation runs out of pixels before the loop point and you
// see a blank gap: the scroll appears to stop, then jump back and repeat.
// This measures both widths and repeats `items` as many times as needed so
// a single copy always fills (or overflows) the track, however wide it is.
export default function InfiniteMarquee({ items, speed = 40, gap = 24, className, style }: Props) {
  const outerRef = useRef<HTMLDivElement>(null);
  const sampleRef = useRef<HTMLDivElement>(null);
  const [repeat, setRepeat] = useState(1);
  const [duration, setDuration] = useState(30);

  useEffect(() => {
    const recompute = () => {
      const outer = outerRef.current;
      const sample = sampleRef.current;
      if (!outer || !sample || items.length === 0) return;
      const containerWidth = outer.offsetWidth;
      const baseWidth = sample.scrollWidth;
      if (baseWidth === 0) return;
      const copies = Math.max(1, Math.ceil(containerWidth / baseWidth) + 1);
      setRepeat(copies);
      setDuration((copies * baseWidth) / speed);
    };
    recompute();
    const ro = new ResizeObserver(recompute);
    if (outerRef.current) ro.observe(outerRef.current);
    if (sampleRef.current) ro.observe(sampleRef.current);
    return () => ro.disconnect();
  }, [items, speed]);

  const track = Array.from({ length: repeat }, () => items).flat();
  const full = [...track, ...track];

  return (
    <div ref={outerRef} className={className} style={{ overflow: "hidden", minWidth: 0, ...style }}>
      {/* Invisible, unrepeated copy used only to measure one set's natural width. */}
      <div
        ref={sampleRef}
        aria-hidden
        style={{ position: "absolute", visibility: "hidden", display: "flex", gap, whiteSpace: "nowrap", pointerEvents: "none" }}
      >
        {items}
      </div>
      <div
        className="infinite-marquee-track"
        style={{ display: "flex", gap, whiteSpace: "nowrap", animationDuration: `${duration}s` }}
      >
        {full.map((node, i) => (
          <div key={i} style={{ display: "flex", flexShrink: 0 }}>
            {node}
          </div>
        ))}
      </div>
    </div>
  );
}
