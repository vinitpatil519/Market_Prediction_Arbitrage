"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { EngineConfig } from "@/lib/types";

/**
 * Live engine parameters. These are assumptions, not display preferences:
 * raising assumed latency thins the book the detector is allowed to trust, so
 * the opportunity table re-prices on the next scan.
 */
export function ControlPanel({ config }: { config: EngineConfig | null }) {
  const [minEdgeBps, setMinEdgeBps] = useState(20);
  const [latency, setLatency] = useState(250);
  const [kelly, setKelly] = useState(0.25);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!config) return;
    setMinEdgeBps(Math.round(config.minNetEdge * 10_000));
    setLatency(config.slippage.latencyMs);
    setKelly(config.kellyMultiplier);
  }, [config?.minNetEdge, config?.slippage.latencyMs, config?.kellyMultiplier]);

  const push = async (updates: Record<string, number>) => {
    setPending(true);
    try {
      await api.patchConfig(updates);
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="grid grid-cols-3 gap-2 border-t border-terminal-line px-3 py-2">
      <Control
        label="min edge"
        value={minEdgeBps}
        display={`${minEdgeBps} bps`}
        min={0}
        max={200}
        step={5}
        onDraft={setMinEdgeBps}
        onCommit={(value) => push({ minNetEdge: value / 10_000 })}
      />
      <Control
        label="latency"
        value={latency}
        display={`${latency} ms`}
        min={0}
        max={1_500}
        step={25}
        onDraft={setLatency}
        onCommit={(value) => push({ latencyMs: value })}
      />
      <Control
        label="kelly ×"
        value={kelly}
        display={`${kelly.toFixed(2)}x`}
        min={0.05}
        max={1}
        step={0.05}
        onDraft={setKelly}
        onCommit={(value) => push({ kellyMultiplier: value })}
      />
      <div className="col-span-3 flex justify-between text-[9px] text-terminal-muted">
        <span>
          cache: {config?.cacheBackend ?? "--"} · feed: {config?.feedMode ?? "--"}
        </span>
        <span className={pending ? "text-terminal-warn" : ""}>
          {pending ? "applying..." : "synced"}
        </span>
      </div>
    </div>
  );
}

function Control({
  label,
  value,
  display,
  min,
  max,
  step,
  onDraft,
  onCommit,
}: {
  label: string;
  value: number;
  display: string;
  min: number;
  max: number;
  step: number;
  onDraft: (value: number) => void;
  onCommit: (value: number) => void;
}) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="flex items-baseline justify-between text-[9px] uppercase tracking-[0.1em] text-terminal-muted">
        {label}
        <span className="num text-[10px] text-terminal-text">{display}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onDraft(Number(event.target.value))}
        onMouseUp={() => onCommit(value)}
        onTouchEnd={() => onCommit(value)}
        onKeyUp={() => onCommit(value)}
        className="h-1 w-full cursor-pointer appearance-none rounded bg-terminal-line accent-[var(--color-terminal-accent)]"
      />
    </label>
  );
}
