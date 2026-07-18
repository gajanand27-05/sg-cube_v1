import { useLayoutEffect, useMemo, useState } from "react";
import { mulberry32 } from "@/lib/random";

// Pulse waves start after the ring assembly finishes (~1.75s) with a small buffer.
const RING_SETTLE = 2.1;

// Grid alignment for that clean PCB rail look
const GRID = 6;

// Trace count — dense enough to feel like a PCB backdrop, but not so busy
// it competes with the panels sitting on top of it.
const N_TRACES = 75;

// Background dots scattered outside the cube's clear zone
const N_DOTS = 180;

// 8-way direction table (N, NE, E, SE, S, SW, W, NW). Diagonals unlock the
// scattered circuit-board feel.
const DIR8: [number, number][] = [
  [0, -1],
  [1, -1],
  [1, 0],
  [1, 1],
  [0, 1],
  [-1, 1],
  [-1, 0],
  [-1, -1],
];

type Layout = { cx: number; cy: number; r: number; vw: number; vh: number };
const FALLBACK: Layout = { cx: 720, cy: 450, r: 110, vw: 1440, vh: 900 };

type Trace = {
  d: string;
  start: [number, number];
  bends: [number, number][];
  end: [number, number];
  opacity: number;
  strokeW: number;
};

type Dot = { x: number; y: number; r: number; opacity: number };

function snap(v: number) {
  return Math.round(v / GRID) * GRID;
}

// Convert an SVG angle in degrees to the nearest DIR8 index (outward direction).
// SVG angle 0 = +x (right) = DIR8 index 2 (E). Each step is 45°.
function angleToDirIdx(deg: number): number {
  const norm = ((deg % 360) + 360) % 360;
  return (Math.round(norm / 45) + 2) % 8;
}

function generateTraces(layout: Layout): Trace[] {
  const rand = mulberry32(20260723);
  const arr: Trace[] = [];

  for (let i = 0; i < N_TRACES; i++) {
    // Scattered angles around the ring shell — no forced even spacing
    const angleDeg = rand() * 360;
    const rad = (angleDeg * Math.PI) / 180;
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);

    // Start exactly on the ring's outer shell with a tiny radial jitter
    const startR = layout.r + 1 + rand() * 5;
    const sx = snap(layout.cx + cos * startR);
    const sy = snap(layout.cy + sin * startR);

    // Initial direction: whichever DIR8 slot points outward from the cube
    // (with a small ±45° jitter so not every trace runs perfectly radial)
    const baseDir = angleToDirIdx(angleDeg);
    let dirIdx = (baseDir + (Math.floor(rand() * 3) - 1) + 8) % 8;

    const points: [number, number][] = [[sx, sy]];
    let x = sx;
    let y = sy;

    // Multi-segment staircase: 3–6 segments, first is the main run outward,
    // later ones are shorter branch/bend legs
    const numSegments = 3 + Math.floor(rand() * 4);
    for (let s = 0; s < numSegments; s++) {
      const [dx, dy] = DIR8[dirIdx];
      const base = s === 0 ? 70 + rand() * 160 : 20 + rand() * 90;
      const segLen = Math.max(GRID, snap(base));
      x += dx * segLen;
      y += dy * segLen;
      points.push([x, y]);

      // Turn ±45° or stay straight — biased slightly toward staying outward
      const turn = rand() < 0.55 ? 0 : rand() < 0.5 ? -1 : 1;
      dirIdx = (dirIdx + turn + 8) % 8;
    }

    const bends = points.slice(1, -1) as [number, number][];
    const end = points[points.length - 1];

    const d =
      `M ${sx} ${sy} ` +
      points
        .slice(1)
        .map((p) => `L ${p[0]} ${p[1]}`)
        .join(" ");

    arr.push({
      d,
      start: [sx, sy],
      bends,
      end,
      opacity: 0.55 + rand() * 0.4,
      strokeW: 0.9 + rand() * 0.9,
    });
  }
  return arr;
}

function generateDots(layout: Layout): Dot[] {
  const rand = mulberry32(19998);
  const arr: Dot[] = [];
  const clearR2 = (layout.r + 40) ** 2;
  for (let i = 0; i < N_DOTS; i++) {
    const x = rand() * layout.vw;
    const y = rand() * layout.vh;
    const dx = x - layout.cx;
    const dy = y - layout.cy;
    if (dx * dx + dy * dy < clearR2) continue;
    arr.push({
      x,
      y,
      r: 0.7 + rand() * 1.4,
      opacity: 0.25 + rand() * 0.5,
    });
  }
  return arr;
}

export function AppBackground() {
  const [layout, setLayout] = useState<Layout>(FALLBACK);

  useLayoutEffect(() => {
    function measure() {
      const el = document.getElementById("sg-cube-anchor");
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const min = Math.min(rect.width, rect.height);
      setLayout({
        cx: rect.left + rect.width / 2,
        cy: rect.top + rect.height / 2,
        r: (min / 400) * 190,
        vw: window.innerWidth,
        vh: window.innerHeight,
      });
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const traces = useMemo(() => generateTraces(layout), [layout]);
  const dots = useMemo(() => generateDots(layout), [layout]);
  const maxReach = Math.hypot(layout.vw, layout.vh);

  return (
    <div className="fixed inset-0 pointer-events-none z-0">
      <svg
        className="circuit-fade-in w-full h-full"
        viewBox={`0 0 ${layout.vw} ${layout.vh}`}
        preserveAspectRatio="none"
      >
        {/* Scattered background dots (outside the cube clear zone) */}
        <g fill="#67e8f9">
          {dots.map((d, i) => (
            <circle key={i} cx={d.x} cy={d.y} r={d.r} opacity={d.opacity} />
          ))}
        </g>

        {/* Circuit traces — all rooted at the ring outer shell, radiating out */}
        <g fill="none">
          {traces.map((t, i) => (
            <g key={i} opacity={t.opacity}>
              {/* Soft halo */}
              <path
                d={t.d}
                stroke="#22d3ee"
                strokeWidth={t.strokeW + 2.5}
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={0.12}
              />
              {/* Main trace */}
              <path
                d={t.d}
                stroke="#22d3ee"
                strokeWidth={t.strokeW}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              {/* Current pulses — bright dashes travelling outward on each trace.
                  pathLength=1 keeps every trace in the same normalized cycle so
                  wavefronts stay coherent regardless of actual trace length. */}
              <path
                d={t.d}
                pathLength="1"
                stroke="#e0f8ff"
                strokeWidth={t.strokeW + 0.8}
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeDasharray="0.04 0.25"
                className="wave-pulse"
              />
              {/* Connector node at the ring shell */}
              <circle
                cx={t.start[0]}
                cy={t.start[1]}
                r={2.5}
                fill="#67e8f9"
                stroke="#22d3ee"
                strokeWidth={0.5}
              />
              {/* Bend dots */}
              {t.bends.map(([bx, by], j) => (
                <circle key={j} cx={bx} cy={by} r={1.5} fill="#22d3ee" />
              ))}
              {/* Endpoint terminal */}
              <rect
                x={t.end[0] - 2.5}
                y={t.end[1] - 2.5}
                width={5}
                height={5}
                fill="#67e8f9"
              />
            </g>
          ))}
        </g>

        {/* Water-wave ripples emanating from the ring — sweep across everything */}
        <g fill="none" stroke="#67e8f9">
          {[0, 1.4, 2.8].map((delay, i) => (
            <circle
              key={i}
              cx={layout.cx}
              cy={layout.cy}
              r={layout.r + 4}
              opacity={0}
              strokeWidth={2.5}
            >
              <animate
                attributeName="r"
                from={layout.r + 4}
                to={maxReach * 0.9}
                dur="4.2s"
                begin={`${RING_SETTLE + delay}s`}
                repeatCount="indefinite"
              />
              <animate
                attributeName="opacity"
                values="0;0.32;0"
                dur="4.2s"
                begin={`${RING_SETTLE + delay}s`}
                repeatCount="indefinite"
              />
              <animate
                attributeName="stroke-width"
                from={2.5}
                to={0.4}
                dur="4.2s"
                begin={`${RING_SETTLE + delay}s`}
                repeatCount="indefinite"
              />
            </circle>
          ))}
        </g>
      </svg>
    </div>
  );
}
