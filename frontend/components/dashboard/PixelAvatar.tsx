"use client";
import { useEffect, useMemo, useRef } from "react";
import type { Persona } from "@/lib/personas";

interface Props {
  persona: Persona;
  size?: number;
  // Typing only plays while the bot is actually live — a paused/idle bot
  // shouldn't look busy.
  active?: boolean;
  // Mouth-flicker "talking" loop, independent of `active` — used where the
  // avatar stands in for a speaking narrator (e.g. the activation screen)
  // rather than a live trading desk.
  talking?: boolean;
}

const W = 38, H = 21;

// Same seated-officer-at-a-desk illustration for every persona (suit, desk,
// monitor, phone are fixed); only skin, hair, and the tie/chart/power-light
// accent vary per persona. Every region below was verified cell-by-cell
// against a printed ASCII grid during design (see the review artifact) so
// nothing floats or overlaps — resist hand-editing coordinates blind.
function buildGrid(longHair?: boolean): string[][] {
  const grid: string[][] = Array.from({ length: H }, () => Array(W).fill("."));
  const fill = (r0: number, r1: number, c0: number, c1: number, ch: string) => {
    for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) if (r >= 0 && r < H && c >= 0 && c < W) grid[r][c] = ch;
  };
  const set = (r: number, c: number, ch: string) => {
    if (r >= 0 && r < H && c >= 0 && c < W) grid[r][c] = ch;
  };

  // Character (centered on col 16.5)
  fill(0, 1, 14, 19, "h");
  fill(2, 2, 13, 20, "h");
  fill(3, 3, 12, 13, "s"); set(3, 14, "h"); fill(3, 3, 15, 18, "s"); set(3, 19, "h"); fill(3, 3, 20, 21, "s");
  fill(4, 4, 12, 13, "s"); set(4, 14, "h");
  set(4, 15, "b"); set(4, 18, "b");                 // eyebrows
  fill(4, 4, 16, 17, "s"); set(4, 19, "h"); fill(4, 4, 20, 21, "s");
  fill(5, 5, 13, 20, "s");
  set(5, 15, "k"); set(5, 18, "k");                 // eyes (under the brows)
  if (longHair) { set(3, 11, "h"); set(3, 22, "h"); set(4, 11, "h"); set(4, 22, "h"); set(5, 12, "h"); set(5, 21, "h"); }
  fill(6, 7, 14, 19, "s");
  set(7, 16, "l"); set(7, 17, "l");                 // mouth
  fill(8, 8, 12, 21, "j"); fill(8, 8, 15, 18, "w");
  fill(9, 12, 12, 21, "j");
  fill(9, 12, 16, 17, "t");
  fill(13, 13, 12, 21, "j");
  set(13, 16, "m");                                 // jacket button, on the tie centerline
  fill(9, 13, 12, 12, "i"); fill(9, 13, 21, 21, "z"); // jacket highlight/shadow edges
  fill(14, 14, 10, 11, "s"); fill(14, 14, 12, 21, "j"); fill(14, 14, 22, 23, "s");

  // Monitor
  fill(8, 8, 1, 10, "m");
  fill(9, 12, 1, 1, "m"); fill(9, 12, 10, 10, "m");
  fill(9, 12, 2, 9, "f");                           // screen — flashes red/green, see .avatar-screen-flash
  fill(13, 13, 1, 10, "m");
  set(13, 3, "o");                                  // power light — persona color
  fill(14, 14, 4, 6, "m");
  fill(15, 15, 3, 7, "m");

  // Telephone — desk accessory to the character's right
  fill(12, 14, 30, 36, "q");                        // base
  set(13, 31, "r"); set(13, 33, "r"); set(13, 35, "r"); // dial buttons
  fill(9, 10, 31, 35, "q");                         // handset
  set(11, 32, "q"); set(11, 34, "q");               // coiled cord

  // Desk
  fill(16, 16, 0, 37, "e");
  fill(17, 20, 0, 37, "d");
  fill(18, 19, 12, 21, "e"); fill(18, 19, 13, 20, "d"); // drawer outline
  set(18, 16, "m"); set(18, 17, "m");               // drawer pull
  for (const [r, c] of [[17, 5], [17, 9], [18, 3], [19, 7], [17, 26], [18, 29], [19, 24], [17, 34], [19, 33]]) {
    set(r, c, "v");                                 // wood grain
  }

  return grid;
}

const SHARED: Record<string, string> = {
  j: "#1F2937", w: "#F3F4F6", d: "#8B5E34", e: "#C08952",
  m: "#111827", k: "#050709", f: "#22C55E",
  q: "#1F2937", r: "#9CA3AF", l: "#8B4A3E", v: "#6B4423",
  i: "#2E3A4A", z: "#161C24",
};

export default function PixelAvatar({ persona, size = 40, active = false, talking = false }: Props) {
  const grid = useMemo(() => buildGrid(persona.longHair), [persona.longHair]);
  // Every avatar shares the same CSS animation-name, which by default all
  // start on the same clock — every screen would flash in lockstep. A random
  // per-instance --screen-delay decouples them so each one changes on its
  // own schedule. Picking it via React state (even lazily in useState) ran
  // once during SSR and again on the client's first render with a different
  // value, causing a hydration mismatch; setting it as a plain setState call
  // in useEffect trips the "no setState in effect body" lint rule too. A ref
  // + a direct DOM mutation sidesteps both: it never touches the render
  // output SSR/hydration compare, and CSS custom properties inherit, so
  // setting it once on the <svg> root reaches every .avatar-screen-flash
  // rect inside without needing per-rect state at all.
  const svgRef = useRef<SVGSVGElement>(null);
  useEffect(() => {
    svgRef.current?.style.setProperty("--screen-delay", `${(Math.random() * 1.2).toFixed(2)}s`);
  }, []);

  return (
    <svg
      ref={svgRef}
      width={size}
      height={(size * H) / W}
      viewBox={`0 0 ${W} ${H}`}
      shapeRendering="crispEdges"
      style={{ flexShrink: 0, position: "relative", zIndex: 1 }}
    >
      {grid.map((row, r) =>
        row.map((ch, c) => {
          if (ch === ".") return null;
          let color: string;
          if (ch === "t" || ch === "o") color = persona.color;
          else if (ch === "h" || ch === "b") color = persona.hair;
          else if (ch === "s") color = persona.skin;
          else color = SHARED[ch];
          // Row 14, cols 10-11 / 22-23 are the forearms poking out past the
          // jacket cuffs at desk height — the only "hand" pixels in the rig.
          // Animating just these two pairs, out of phase, reads as typing
          // without touching anything else in the illustration.
          const isLeftHand = active && r === 14 && (c === 10 || c === 11);
          const isRightHand = active && r === 14 && (c === 22 || c === 23);
          const isMouth = talking && r === 7 && (c === 16 || c === 17);
          const extraClass = isLeftHand
            ? "avatar-hand avatar-hand-l"
            : isRightHand
            ? "avatar-hand avatar-hand-r"
            : isMouth
            ? "avatar-mouth"
            : ch === "f"
            ? "avatar-screen-flash"
            : undefined;
          return <rect key={`${r}-${c}`} x={c} y={r} width={1} height={1} fill={color} className={extraClass} />;
        })
      )}
    </svg>
  );
}
