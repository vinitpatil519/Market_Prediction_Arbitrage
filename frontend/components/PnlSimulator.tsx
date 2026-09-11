"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { MonteCarloResult, Opportunity } from "@/lib/types";
import { pct, usd } from "@/lib/format";
import { Empty } from "./Panel";

const WIDTH = 560;
const HEIGHT = 180;
const PAD = { top: 10, right: 8, bottom: 16, left: 46 };

interface Params {
  bankroll: number;
  trades: number;
  costPerPair: number;
  fillProbability: number;
  kellyMultiplier: number;
  lossFraction: number;
}

const DEFAULTS: Params = {
  bankroll: 10_000,
  trades: 250,
  costPerPair: 0.985,
  fillProbability: 0.985,
  kellyMultiplier: 0.25,
  lossFraction: 0.5,
};

/**
 * Compounds one repeated edge. The point is not the expected value - a
 * positive edge always has one - but the shape of the paths: how deep the
 * drawdown gets, and how quickly raising the Kelly multiplier turns a steady
 * curve into one that can halve.
 */
export function PnlSimulator({ selected }: { selected: Opportunity | null }) {
  const [params, setParams] = useState<Params>(DEFAULTS);
  const [result, setResult] = useState<MonteCarloResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (next: Params) => {
    setBusy(true);
    try {
      setResult(await api.monteCarlo({ ...next, paths: 400, seed: 7 }));
    } catch {
      setResult(null);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    run(params);
    // Re-running on every keystroke would hammer the backend; the controls
    // trigger their own runs on commit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load the selected opportunity's real economics into the model.
  useEffect(() => {
    if (!selected || selected.maxSize <= 0) return;
    const costPerPair = Math.min(
      0.999,
      Math.max(0.5, selected.capitalRequired / selected.maxSize),
    );
    const next = {
      ...params,
      costPerPair: Number(costPerPair.toFixed(4)),
      fillProbability: Number(selected.fillProbability.toFixed(4)),
    };
    setParams(next);
    run(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected?.id]);

  const update = (key: keyof Params, value: number) => {
    const next = { ...params, [key]: value };
    setParams(next);
    run(next);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="grid shrink-0 grid-cols-3 gap-x-3 gap-y-1.5 border-b border-terminal-line px-3 py-2 sm:grid-cols-6">
        <Slider
          label="bankroll"
          value={params.bankroll}
          min={1_000}
          max={250_000}
          step={1_000}
          format={(value) => usd(value, 0)}
          onChange={(value) => update("bankroll", value)}
        />
        <Slider
          label="trades"
          value={params.trades}
          min={25}
          max={1_000}
          step={25}
          format={String}
          onChange={(value) => update("trades", value)}
        />
        <Slider
          label="basket cost"
          value={params.costPerPair}
          min={0.9}
          max={0.999}
          step={0.001}
          format={(value) => `${(value * 100).toFixed(1)}c`}
          onChange={(value) => update("costPerPair", value)}
        />
        <Slider
          label="p(hedge holds)"
          value={params.fillProbability}
          min={0.9}
          max={1}
          step={0.001}
          format={(value) => pct(value, 1)}
          onChange={(value) => update("fillProbability", value)}
        />
        <Slider
          label="kelly ×"
          value={params.kellyMultiplier}
          min={0.05}
          max={1}
          step={0.05}
          format={(value) => `${value.toFixed(2)}x`}
          onChange={(value) => update("kellyMultiplier", value)}
        />
        <Slider
          label="loss on break"
          value={params.lossFraction}
          min={0.1}
          max={1}
          step={0.05}
          format={(value) => pct(value, 0)}
          onChange={(value) => update("lossFraction", value)}
        />
      </div>

      {!result ? (
        <Empty message={busy ? "Running paths..." : "Simulation unavailable."} />
      ) : (
        <>
          <Fan result={result} />
          <div className="grid shrink-0 grid-cols-3 gap-2 border-t border-terminal-line px-3 py-2 sm:grid-cols-6">
            <Stat label="median end" value={usd(result.stats.medianTerminal, 0)} />
            <Stat
              label="median return"
              value={pct(result.stats.medianReturn, 1)}
              color="var(--color-terminal-long)"
            />
            <Stat label="p5 end" value={usd(result.stats.p5Terminal, 0)} />
            <Stat
              label="median drawdown"
              value={pct(result.stats.medianMaxDrawdown, 1)}
              color="var(--color-terminal-warn)"
            />
            <Stat
              label="worst drawdown"
              value={pct(result.stats.worstMaxDrawdown, 1)}
              color="var(--color-terminal-short)"
            />
            <Stat
              label="stake / trade"
              value={pct(result.sizing.appliedFraction, 2)}
            />
          </div>
        </>
      )}
    </div>
  );
}

function Fan({ result }: { result: MonteCarloResult }) {
  const { p5, p25, p50, p75, p95 } = result.curves as Record<string, number[]>;
  if (!p50?.length) return <Empty message="No paths returned." />;

  const all = [...p5, ...p95];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = Math.max(1, hi - lo);
  const innerWidth = WIDTH - PAD.left - PAD.right;
  const innerHeight = HEIGHT - PAD.top - PAD.bottom;
  const x = (index: number) => PAD.left + (index / (p50.length - 1)) * innerWidth;
  const y = (value: number) =>
    PAD.top + innerHeight - ((value - lo) / span) * innerHeight;

  const ribbon = (upper: number[], lower: number[]) =>
    [
      ...upper.map((value, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(1)} ${y(value).toFixed(1)}`),
      ...lower
        .map((_, index) => lower.length - 1 - index)
        .map((index) => `L ${x(index).toFixed(1)} ${y(lower[index]).toFixed(1)}`),
      "Z",
    ].join(" ");

  const line = (series: number[]) =>
    series
      .map((value, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(1)} ${y(value).toFixed(1)}`)
      .join(" ");

  const start = p50[0];

  return (
    <div className="min-h-0 flex-1">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-full w-full" preserveAspectRatio="none">
        {[0, 0.5, 1].map((fraction) => {
          const value = lo + span * fraction;
          return (
            <g key={fraction}>
              <line
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={y(value)}
                y2={y(value)}
                stroke="var(--color-terminal-line)"
              />
              <text
                x={PAD.left - 5}
                y={y(value) + 3}
                textAnchor="end"
                fill="var(--color-terminal-muted)"
                fontSize={8}
                className="num"
              >
                {usd(value, 0)}
              </text>
            </g>
          );
        })}

        <path d={ribbon(p95, p5)} fill="var(--color-terminal-accent)" opacity={0.12} />
        <path d={ribbon(p75, p25)} fill="var(--color-terminal-accent)" opacity={0.2} />
        <path d={line(p50)} fill="none" stroke="var(--color-terminal-accent)" strokeWidth={1.8} />

        <line
          x1={PAD.left}
          x2={WIDTH - PAD.right}
          y1={y(start)}
          y2={y(start)}
          stroke="var(--color-terminal-muted)"
          strokeDasharray="3 3"
        />
      </svg>
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);

  return (
    <label className="flex flex-col gap-0.5">
      <span className="flex items-baseline justify-between text-[9px] uppercase tracking-[0.1em] text-terminal-muted">
        {label}
        <span className="num text-[10px] text-terminal-text">{format(draft)}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={draft}
        onChange={(event) => setDraft(Number(event.target.value))}
        onMouseUp={() => onChange(draft)}
        onTouchEnd={() => onChange(draft)}
        onKeyUp={() => onChange(draft)}
        className="h-1 w-full cursor-pointer appearance-none rounded bg-terminal-line accent-[var(--color-terminal-accent)]"
      />
    </label>
  );
}

function Stat({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color?: string;
}) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-[0.1em] text-terminal-muted">
        {label}
      </div>
      <div className="num text-[12px]" style={color ? { color } : undefined}>
        {value}
      </div>
    </div>
  );
}
