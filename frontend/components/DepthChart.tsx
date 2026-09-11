"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { BookDetail } from "@/lib/types";
import { cents, qty } from "@/lib/format";
import { Empty } from "./Panel";

const WIDTH = 560;
const HEIGHT = 200;
const PAD = { top: 10, right: 10, bottom: 20, left: 40 };

type Mode = "depth" | "cost";

export function DepthChart({
  venue,
  marketId,
}: {
  venue: string | null;
  marketId: string | null;
}) {
  const [book, setBook] = useState<BookDetail | null>(null);
  const [mode, setMode] = useState<Mode>("depth");

  useEffect(() => {
    if (!venue || !marketId) {
      setBook(null);
      return;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const result = await api.book(venue, marketId);
        if (!cancelled) setBook(result);
      } catch {
        if (!cancelled) setBook(null);
      }
    };
    load();
    const timer = setInterval(load, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [venue, marketId]);

  if (!venue || !marketId) return <Empty message="Select a row to inspect its book." />;
  if (!book) return <Empty message="Loading book..." />;

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-terminal-line px-3 py-1.5 text-[10px]">
        <div className="flex gap-3">
          <span className="text-terminal-muted uppercase tracking-wider">
            {book.venue} · yes
          </span>
          <span className="num text-terminal-long">
            bid {cents(book.yes.bestBid)}
          </span>
          <span className="num text-terminal-short">
            ask {cents(book.yes.bestAsk)}
          </span>
          <span className="num text-terminal-muted">
            spread {book.yes.spread != null ? `${(book.yes.spread * 100).toFixed(1)}c` : "--"}
          </span>
        </div>
        <div className="flex gap-1">
          {(["depth", "cost"] as Mode[]).map((option) => (
            <button
              key={option}
              onClick={() => setMode(option)}
              className={`rounded px-1.5 py-0.5 uppercase tracking-wider transition-colors ${
                mode === option
                  ? "bg-terminal-raised text-terminal-text"
                  : "text-terminal-muted hover:text-terminal-text"
              }`}
            >
              {option === "depth" ? "depth" : "cost of size"}
            </button>
          ))}
        </div>
      </div>

      {mode === "depth" ? <Depth book={book} /> : <CostCurve book={book} />}
    </div>
  );
}

function Depth({ book }: { book: BookDetail }) {
  const bids = book.yes.bids;
  const asks = book.yes.asks;
  if (!bids.length && !asks.length) return <Empty message="Book is empty." />;

  const prices = [...bids, ...asks].map((row) => row.price);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const spanPrice = Math.max(0.01, maxPrice - minPrice);
  const maxSize = Math.max(
    ...bids.map((row) => row.cumulative),
    ...asks.map((row) => row.cumulative),
    1,
  );

  const innerWidth = WIDTH - PAD.left - PAD.right;
  const innerHeight = HEIGHT - PAD.top - PAD.bottom;
  const x = (price: number) =>
    PAD.left + ((price - minPrice) / spanPrice) * innerWidth;
  const y = (size: number) => PAD.top + innerHeight - (size / maxSize) * innerHeight;

  // Resting liquidity is a step function, not a curve: size is constant
  // between levels and jumps at each price.
  const steps = (rows: typeof bids, descending: boolean) => {
    if (!rows.length) return "";
    const ordered = descending ? [...rows].reverse() : rows;
    const parts: string[] = [`M ${x(ordered[0].price).toFixed(1)} ${y(0).toFixed(1)}`];
    let previous = 0;
    for (const row of ordered) {
      parts.push(`L ${x(row.price).toFixed(1)} ${y(previous).toFixed(1)}`);
      parts.push(`L ${x(row.price).toFixed(1)} ${y(row.cumulative).toFixed(1)}`);
      previous = row.cumulative;
    }
    const last = ordered[ordered.length - 1];
    parts.push(`L ${x(last.price).toFixed(1)} ${y(0).toFixed(1)}`);
    parts.push("Z");
    return parts.join(" ");
  };

  return (
    <div className="min-h-0 flex-1">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-full w-full" preserveAspectRatio="none">
        {[0, 0.5, 1].map((fraction) => (
          <g key={fraction}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={y(maxSize * fraction)}
              y2={y(maxSize * fraction)}
              stroke="var(--color-terminal-line)"
            />
            <text
              x={PAD.left - 5}
              y={y(maxSize * fraction) + 3}
              textAnchor="end"
              fill="var(--color-terminal-muted)"
              fontSize={8}
              className="num"
            >
              {qty(maxSize * fraction)}
            </text>
          </g>
        ))}

        <path d={steps(bids, true)} fill="var(--color-terminal-long)" opacity={0.3} />
        <path
          d={steps(bids, true)}
          fill="none"
          stroke="var(--color-terminal-long)"
          strokeWidth={1.4}
        />
        <path d={steps(asks, false)} fill="var(--color-terminal-short)" opacity={0.3} />
        <path
          d={steps(asks, false)}
          fill="none"
          stroke="var(--color-terminal-short)"
          strokeWidth={1.4}
        />

        {book.yes.mid != null && (
          <line
            x1={x(book.yes.mid)}
            x2={x(book.yes.mid)}
            y1={PAD.top}
            y2={HEIGHT - PAD.bottom}
            stroke="var(--color-terminal-muted)"
            strokeDasharray="3 3"
          />
        )}

        {[minPrice, (minPrice + maxPrice) / 2, maxPrice].map((price) => (
          <text
            key={price}
            x={x(price)}
            y={HEIGHT - 6}
            textAnchor="middle"
            fill="var(--color-terminal-muted)"
            fontSize={8}
            className="num"
          >
            {cents(price)}
          </text>
        ))}
      </svg>
    </div>
  );
}

function CostCurve({ book }: { book: BookDetail }) {
  const curve = book.costCurve.yesBuy;
  if (curve.length < 2) return <Empty message="Not enough depth to price a clip." />;

  const maxSizeValue = Math.max(...curve.map((point) => point.size));
  const maxSlip = Math.max(...curve.map((point) => point.slippageBps), 1);
  const innerWidth = WIDTH - PAD.left - PAD.right;
  const innerHeight = HEIGHT - PAD.top - PAD.bottom;
  const x = (size: number) => PAD.left + (size / maxSizeValue) * innerWidth;
  const y = (slip: number) => PAD.top + innerHeight - (slip / maxSlip) * innerHeight;

  const path = curve
    .map(
      (point, index) =>
        `${index === 0 ? "M" : "L"} ${x(point.size).toFixed(1)} ${y(
          point.slippageBps,
        ).toFixed(1)}`,
    )
    .join(" ");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full flex-1" preserveAspectRatio="none">
        {[0, 0.5, 1].map((fraction) => (
          <g key={fraction}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={y(maxSlip * fraction)}
              y2={y(maxSlip * fraction)}
              stroke="var(--color-terminal-line)"
            />
            <text
              x={PAD.left - 5}
              y={y(maxSlip * fraction) + 3}
              textAnchor="end"
              fill="var(--color-terminal-muted)"
              fontSize={8}
              className="num"
            >
              {(maxSlip * fraction).toFixed(0)}
            </text>
          </g>
        ))}
        <path d={path} fill="none" stroke="var(--color-terminal-warn)" strokeWidth={1.6} />
        {curve.map((point) => (
          <circle
            key={point.size}
            cx={x(point.size)}
            cy={y(point.slippageBps)}
            r={1.8}
            fill="var(--color-terminal-warn)"
          />
        ))}
        <text
          x={WIDTH / 2}
          y={HEIGHT - 6}
          textAnchor="middle"
          fill="var(--color-terminal-muted)"
          fontSize={8}
        >
          slippage vs touch (bps) by clip size (contracts)
        </text>
      </svg>
    </div>
  );
}
