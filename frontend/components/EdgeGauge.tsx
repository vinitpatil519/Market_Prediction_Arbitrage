"use client";

import type { Opportunity } from "@/lib/types";
import { BAND_COLOR, edgeBand } from "@/lib/format";
import { Empty } from "./Panel";

const MAX_BPS = 300;
const RADIUS = 74;
const CENTER = { x: 100, y: 92 };

function polar(angleDeg: number, radius: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return {
    x: CENTER.x + radius * Math.cos(rad),
    y: CENTER.y + radius * Math.sin(rad),
  };
}

/** Sweep from the left end of the dial to `value`, clamped to the scale. */
function arc(value: number, radius: number) {
  const fraction = Math.max(0, Math.min(1, value / MAX_BPS));
  const start = polar(-90, radius);
  const end = polar(-90 + 180 * fraction, radius);
  const largeArc = fraction > 0.5 ? 1 : 0;
  return `M ${start.x} ${start.y} A ${radius} ${radius} 0 ${largeArc} 1 ${end.x} ${end.y}`;
}

/**
 * Two concentric arcs: what the screen shows before costs, and what survives
 * fees plus depth-walked slippage. The gap between them is the point of the
 * whole engine, so it is drawn rather than described.
 */
export function EdgeGauge({ best }: { best: Opportunity | null }) {
  if (!best) {
    return <Empty message="No edge clears the threshold right now." />;
  }

  const grossBps = best.grossEdge * 10_000;
  const netBps = best.netEdgeBps;
  const band = edgeBand(netBps);
  const color = BAND_COLOR[band];
  const erosion = grossBps > 0 ? 1 - netBps / grossBps : 0;

  return (
    <div className="flex h-full flex-col items-center justify-center gap-1 px-3 py-2">
      <svg viewBox="0 0 200 116" className="w-full max-w-[240px]">
        <path
          d={arc(MAX_BPS, RADIUS)}
          fill="none"
          stroke="var(--color-terminal-line)"
          strokeWidth={10}
          strokeLinecap="round"
        />
        <path
          d={arc(grossBps, RADIUS)}
          fill="none"
          stroke="var(--color-terminal-muted)"
          strokeWidth={10}
          strokeLinecap="round"
          opacity={0.55}
        />
        <path
          d={arc(netBps, RADIUS - 13)}
          fill="none"
          stroke={color}
          strokeWidth={9}
          strokeLinecap="round"
        />
        {[0, 100, 200, 300].map((tick) => {
          const outer = polar(-90 + 180 * (tick / MAX_BPS), RADIUS + 8);
          const inner = polar(-90 + 180 * (tick / MAX_BPS), RADIUS + 3);
          return (
            <line
              key={tick}
              x1={inner.x}
              y1={inner.y}
              x2={outer.x}
              y2={outer.y}
              stroke="var(--color-terminal-muted)"
              strokeWidth={1}
            />
          );
        })}
        <text
          x={CENTER.x}
          y={CENTER.y - 16}
          textAnchor="middle"
          className="num"
          fill={color}
          fontSize={30}
        >
          {netBps.toFixed(0)}
        </text>
        <text
          x={CENTER.x}
          y={CENTER.y + 2}
          textAnchor="middle"
          fill="var(--color-terminal-muted)"
          fontSize={9}
          letterSpacing={1.6}
        >
          BPS NET EDGE
        </text>
      </svg>

      <div className="grid w-full grid-cols-3 gap-2 text-center">
        <Cell label="gross" value={`${grossBps.toFixed(0)}`} />
        <Cell
          label="cost drag"
          value={`${(erosion * 100).toFixed(0)}%`}
          color="var(--color-terminal-short)"
        />
        <Cell label="net" value={`${netBps.toFixed(0)}`} color={color} />
      </div>

      <p className="line-clamp-2 px-1 text-center text-[10px] leading-tight text-terminal-muted">
        {best.title}
      </p>
    </div>
  );
}

function Cell({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div className="rounded border border-terminal-line bg-terminal-raised px-1.5 py-1">
      <div className="text-[9px] uppercase tracking-[0.12em] text-terminal-muted">
        {label}
      </div>
      <div className="num text-[13px]" style={color ? { color } : undefined}>
        {value}
      </div>
    </div>
  );
}
