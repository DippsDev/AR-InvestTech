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
  const loopRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const [repeat, setRepeat] = useState(1);
  const loopWidthRef = useRef(0);
  const posRef = useRef(0);

  // Figure out how many copies of `items` are needed so one loop (the
  // content between wrap points) always fills or overflows the visible
  // track — otherwise the scroll runs out of content before the loop point.
  useEffect(() => {
    const recompute = () => {
      const outer = outerRef.current;
      const sample = sampleRef.current;
      if (!outer || !sample || items.length === 0) return;
      const containerWidth = outer.offsetWidth;
      const baseWidth = sample.scrollWidth;
      if (baseWidth === 0) return;
      setRepeat(Math.max(1, Math.ceil(containerWidth / baseWidth) + 1));
    };
    recompute();
    const ro = new ResizeObserver(recompute);
    if (outerRef.current) ro.observe(outerRef.current);
    if (sampleRef.current) ro.observe(sampleRef.current);
    return () => ro.disconnect();
  }, [items]);

  // Track the rendered width of one loop directly (not estimated), so the
  // rAF driver below always wraps at the true content boundary.
  useEffect(() => {
    const loop = loopRef.current;
    if (!loop) return;
    const ro = new ResizeObserver(([entry]) => {
      loopWidthRef.current = entry.contentRect.width;
    });
    ro.observe(loop);
    loopWidthRef.current = loop.offsetWidth;
    return () => ro.disconnect();
  });

  // Drive the scroll with requestAnimationFrame instead of a CSS animation
  // whose duration is recomputed from measured widths: changing
  // animation-duration on an already-running CSS animation makes browsers
  // jump/restart it mid-loop — which is exactly the stutter this caused,
  // firing every time the marquee's content changed width by even a pixel
  // (e.g. a ticker value re-rendering on every price/equity poll). Position
  // accumulates in a ref and wraps modulo the loop's current width, so
  // content or size changes are picked up smoothly next frame instead of
  // resetting progress. This effect itself never re-runs on content
  // changes — only if `speed` changes — so the loop is never torn down.
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const track = trackRef.current;
      const loopWidth = loopWidthRef.current;
      if (track && loopWidth > 0) {
        posRef.current = (posRef.current + speed * dt) % loopWidth;
        track.style.transform = `translateX(-${posRef.current}px)`;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [speed]);

  const loop = Array.from({ length: repeat }, () => items).flat();

  // position:relative below is load-bearing, not cosmetic. The measuring copy
  // is position:absolute, so without a positioned ancestor here its containing
  // block resolves all the way up to the initial containing block — which means
  // this element's own overflow:hidden does NOT clip it, and neither does any of
  // the overflow-x:hidden chain in globals.css, because none of those boxes are
  // in its containing block chain either. visibility:hidden still contributes to
  // scrollable overflow, so a measuring copy several thousand pixels wide (one
  // EventCard is 320px) made the whole document horizontally scrollable.
  return (
    <div ref={outerRef} className={className} style={{ position: "relative", overflow: "hidden", minWidth: 0, ...style }}>
      {/* Invisible, unrepeated copy used only to measure one set's natural width. */}
      <div
        ref={sampleRef}
        aria-hidden
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          // Now that the containing block is the (narrow) outer box, an
          // auto-width absolute element would shrink-to-fit against it and
          // report a container-sized measurement instead of the content's
          // natural width. max-content pins it to the real thing; it stays
          // clipped by the outer overflow:hidden, so it costs no layout.
          width: "max-content",
          visibility: "hidden",
          display: "flex",
          gap,
          whiteSpace: "nowrap",
          pointerEvents: "none",
        }}
      >
        {items}
      </div>
      <div ref={trackRef} style={{ display: "flex", gap, whiteSpace: "nowrap", willChange: "transform" }}>
        <div ref={loopRef} style={{ display: "flex", gap, flexShrink: 0 }}>
          {loop.map((node, i) => (
            <div key={`a-${i}`} style={{ display: "flex", flexShrink: 0 }}>
              {node}
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap, flexShrink: 0 }}>
          {loop.map((node, i) => (
            <div key={`b-${i}`} style={{ display: "flex", flexShrink: 0 }}>
              {node}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
