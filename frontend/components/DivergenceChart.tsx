"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { HistoryPoint } from "@/lib/types";
import { VENUE_COLOR, cents } from "@/lib/format";
import { Empty } from "./Panel";

const WIDTH = 640;
const HEIGHT = 190;
const PAD = { top: 12, right: 46, bottom: 18, left: 8 };
const VENUES = ["polymarket", "kalshi"] as const;

/**
 * Both venues' implied probability for one event, with the gap between them
 * shaded. The shaded area is the raw signal; it only becomes an opportunity
 * once it is wider than the combined spread plus fees, which is why the table
 * often stays empty while this chart shows visible separation.
 */
export function DivergenceChart({ eventKey }: { eventKey: string | null }) {
  const [points, setPoints] = useState<HistoryPoint[]>([]);

  useEffect(() => {
    if (!eventKey) {
      setPoints([]);
      return;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const result = await api.history(eventKey);
        if (!cancelled) setPoints(result.points);
      } catch {
        if (!cancelled) setPoints([]);
      }
    };
    load();
    const timer = setInterval(load, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [eventKey]);

  if (!eventKey) return <Empty message="Select a row to chart its cross-venue divergence." />;
  if (points.length < 2) return <Empty message="Collecting price history..." />;

  const values = points.flatMap((point) =>
    VENUES.map((venue) => point[venue]).filter((value): value is number => value != null),
  );
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(0.005, max - min);
  const lo = min - span * 0.15;
  const hi = max + span * 0.15;

  const innerWidth = WIDTH - PAD.left - PAD.right;
  const innerHeight = HEIGHT - PAD.top - PAD.bottom;
  const x = (index: number) =>
    PAD.left + (index / Math.max(1, points.length - 1)) * innerWidth;
  const y = (value: number) =>
    PAD.top + innerHeight - ((value - lo) / (hi - lo)) * innerHeight;

  const line = (venue: string) =>
    points
      .map((point, index) => {
        const value = point[venue];
        if (value == null) return null;
        return `${index === 0 ? "M" : "L"} ${x(index).toFixed(1)} ${y(value).toFixed(1)}`;
      })
      .filter(Boolean)
      .join(" ");

  // Forward along one venue, back along the other: the enclosed area is the
  // live divergence.
  const band = [
    ...points.map(
      (point, index) =>
        `${index === 0 ? "M" : "L"} ${x(index).toFixed(1)} ${y(
          point[VENUES[0]] ?? lo,
        ).toFixed(1)}`,
    ),
    ...points
      .map((_, index) => points.length - 1 - index)
      .map(
        (index) =>
          `L ${x(index).toFixed(1)} ${y(points[index][VENUES[1]] ?? lo).toFixed(1)}`,
      ),
    "Z",
  ].join(" ");

  const latest = points[points.length - 1];
  const gap = Math.abs((latest[VENUES[0]] ?? 0) - (latest[VENUES[1]] ?? 0));

  return (
    <div className="flex h-full flex-col">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full flex-1" preserveAspectRatio="none">
        {[0, 0.5, 1].map((fraction) => {
          const value = lo + (hi - lo) * fraction;
          return (
            <g key={fraction}>
              <line
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={y(value)}
                y2={y(value)}
                stroke="var(--color-terminal-line)"
                strokeWidth={1}
              />
              <text
                x={WIDTH - PAD.right + 6}
                y={y(value) + 3}
                fill="var(--color-terminal-muted)"
                fontSize={9}
                className="num"
              >
                {cents(value)}
              </text>
            </g>
          );
        })}

        <path d={band} fill="var(--color-terminal-accent)" opacity={0.12} />

        {VENUES.map((venue) => (
          <path
            key={venue}
            d={line(venue)}
            fill="none"
            stroke={VENUE_COLOR[venue]}
            strokeWidth={1.6}
            strokeLinejoin="round"
          />
        ))}

        {VENUES.map((venue) => {
          const value = latest[venue];
          if (value == null) return null;
          return (
            <circle
              key={venue}
              cx={x(points.length - 1)}
              cy={y(value)}
              r={2.6}
              fill={VENUE_COLOR[venue]}
            />
          );
        })}
      </svg>

      <div className="flex shrink-0 items-center justify-between border-t border-terminal-line px-3 py-1.5 text-[10px]">
        <div className="flex gap-4">
          {VENUES.map((venue) => (
            <span key={venue} className="flex items-center gap-1.5">
              <span
                className="h-0.5 w-4"
                style={{ background: VENUE_COLOR[venue] }}
              />
              <span className="text-terminal-muted uppercase tracking-wider">{venue}</span>
              <span className="num">{cents(latest[venue])}</span>
            </span>
          ))}
        </div>
        <span className="flex items-center gap-1.5">
          <span className="uppercase tracking-wider text-terminal-muted">gap</span>
          <span className="num text-terminal-accent">{(gap * 10_000).toFixed(0)} bps</span>
        </span>
      </div>
    </div>
  );
}
