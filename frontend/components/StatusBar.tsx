"use client";

import type { ConnectionState } from "@/lib/useStream";
import type { Snapshot } from "@/lib/types";
import { BAND_COLOR, VENUE_COLOR, edgeBand, usd } from "@/lib/format";

const STATE_COLOR: Record<ConnectionState, string> = {
  live: "var(--color-terminal-long)",
  connecting: "var(--color-terminal-warn)",
  retrying: "var(--color-terminal-warn)",
  offline: "var(--color-terminal-short)",
};

export function StatusBar({
  snapshot,
  state,
}: {
  snapshot: Snapshot | null;
  state: ConnectionState;
}) {
  const best = snapshot?.opportunities[0];
  const band = edgeBand(best?.netEdgeBps ?? 0);

  return (
    <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-terminal-line bg-terminal-panel px-4 py-2.5">
      <div className="flex items-center gap-2">
        <span
          className={`h-2 w-2 rounded-full ${state === "live" ? "pulse" : ""}`}
          style={{ background: STATE_COLOR[state] }}
        />
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em]">
          Arb Engine
        </span>
        <span className="text-[10px] uppercase tracking-wider text-terminal-muted">
          {snapshot?.config.feedMode ?? "--"} feed
        </span>
      </div>

      <div className="flex items-center gap-4">
        {(snapshot?.feeds ?? []).map((feed) => (
          <div key={feed.venue} className="flex items-center gap-1.5" title={feed.error ?? ""}>
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{
                background: feed.connected
                  ? VENUE_COLOR[feed.venue]
                  : "var(--color-terminal-short)",
              }}
            />
            <span className="text-[10px] uppercase tracking-wider text-terminal-muted">
              {feed.venue}
            </span>
            <span className="num text-[10px] text-terminal-muted">
              {feed.markets} mkt
            </span>
          </div>
        ))}
      </div>

      <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-1 text-[10px]">
        <Stat label="live edges" value={String(snapshot?.opportunities.length ?? 0)} />
        <Stat
          label="best net"
          value={best ? `${best.netEdgeBps.toFixed(0)} bps` : "--"}
          color={BAND_COLOR[band]}
        />
        <Stat
          label="deployable"
          value={usd(
            (snapshot?.opportunities ?? []).reduce((sum, o) => sum + o.kelly.stake, 0),
            0,
          )}
        />
        <Stat label="bankroll" value={usd(snapshot?.config.bankroll ?? 0, 0)} />
        <Stat
          label="scan"
          value={`${(snapshot?.stats.lastScanMs ?? 0).toFixed(1)} ms`}
        />
        <Stat label="scans" value={String(snapshot?.stats.scans ?? 0)} />
      </div>
    </header>
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
    <div className="flex items-baseline gap-1.5">
      <span className="uppercase tracking-[0.12em] text-terminal-muted">{label}</span>
      <span className="num text-[12px]" style={color ? { color } : undefined}>
        {value}
      </span>
    </div>
  );
}
