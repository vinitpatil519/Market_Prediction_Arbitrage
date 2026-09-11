"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Opportunity, SimulatedTrade } from "@/lib/types";
import {
  ARB_LABEL,
  CONSTRAINT_LABEL,
  VENUE_COLOR,
  cents,
  pct,
  qty,
  usd,
} from "@/lib/format";
import { Empty } from "./Panel";

export function OpportunityDetail({ opportunity }: { opportunity: Opportunity | null }) {
  const [size, setSize] = useState<number>(0);
  const [breakLeg, setBreakLeg] = useState(false);
  const [trade, setTrade] = useState<SimulatedTrade | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setTrade(null);
    setError(null);
    if (opportunity) {
      setSize(Math.max(1, Math.round(opportunity.kelly.contracts || opportunity.maxSize)));
    }
  }, [opportunity?.id]);

  if (!opportunity) {
    return <Empty message="Select a row to price the basket leg by leg." />;
  }

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.execute(
        opportunity.id,
        size,
        breakLeg ? [opportunity.legs.length - 1] : [],
      );
      setTrade(result.trade);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "simulation failed");
      setTrade(null);
    } finally {
      setBusy(false);
    }
  };

  const totalFees = opportunity.legs.reduce((sum, leg) => sum + leg.fee, 0);
  const totalSlip = opportunity.legs.reduce(
    (sum, leg) => sum + leg.slippage * leg.size,
    0,
  );

  return (
    <div className="flex h-full flex-col gap-2 overflow-auto p-3 text-[11px]">
      <div>
        <div className="text-[9px] uppercase tracking-[0.14em] text-terminal-accent">
          {ARB_LABEL[opportunity.arbType]}
        </div>
        <div className="mt-0.5 leading-snug text-terminal-text">{opportunity.title}</div>
      </div>

      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-terminal-line text-[9px] uppercase tracking-[0.1em] text-terminal-muted">
            <th className="py-1 text-left">leg</th>
            <th className="py-1 text-right">touch</th>
            <th className="py-1 text-right">avg fill</th>
            <th className="py-1 text-right">slip</th>
            <th className="py-1 text-right">fee</th>
            <th className="py-1 text-right">cash out</th>
          </tr>
        </thead>
        <tbody>
          {opportunity.legs.map((leg, index) => (
            <tr key={index} className="border-b border-terminal-line/50">
              <td className="py-1 text-left">
                <span style={{ color: VENUE_COLOR[leg.venue] }}>{leg.venue}</span>{" "}
                <span
                  className={
                    leg.action === "buy" ? "text-terminal-long" : "text-terminal-short"
                  }
                >
                  {leg.action}
                </span>{" "}
                <span className="text-terminal-muted">{leg.side.toUpperCase()}</span>
                <span className="num ml-1 text-terminal-muted">
                  ×{qty(leg.size)}
                </span>
              </td>
              <td className="num py-1 text-right text-terminal-muted">
                {cents(leg.touchPrice)}
              </td>
              <td className="num py-1 text-right">{cents(leg.avgPrice, 2)}</td>
              <td className="num py-1 text-right text-terminal-warn">
                {(leg.slippage * 10_000).toFixed(0)}
              </td>
              <td className="num py-1 text-right text-terminal-short">
                {usd(leg.fee)}
              </td>
              <td className="num py-1 text-right">
                {usd(
                  leg.action === "buy"
                    ? leg.avgPrice * leg.size + leg.fee
                    : (1 - leg.avgPrice) * leg.size + leg.fee,
                  0,
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="grid grid-cols-4 gap-2">
        <Cell label="gross edge" value={`${(opportunity.grossEdge * 10_000).toFixed(0)} bps`} />
        <Cell
          label="fees"
          value={usd(totalFees)}
          color="var(--color-terminal-short)"
        />
        <Cell
          label="slippage"
          value={usd(totalSlip)}
          color="var(--color-terminal-warn)"
        />
        <Cell
          label="net edge"
          value={`${opportunity.netEdgeBps.toFixed(0)} bps`}
          color="var(--color-terminal-long)"
        />
      </div>

      <div className="rounded border border-terminal-line bg-terminal-raised p-2">
        <div className="mb-1 text-[9px] uppercase tracking-[0.14em] text-terminal-muted">
          Kelly sizing · {CONSTRAINT_LABEL[opportunity.kelly.bindingConstraint]}
        </div>
        <div className="grid grid-cols-4 gap-2">
          <Cell label="full f*" value={pct(opportunity.kelly.fullFraction, 1)} />
          <Cell label="applied f" value={pct(opportunity.kelly.appliedFraction, 2)} />
          <Cell label="stake" value={usd(opportunity.kelly.stake, 0)} />
          <Cell label="contracts" value={qty(opportunity.kelly.contracts)} />
        </div>
        <div className="mt-1.5 text-[10px] leading-relaxed text-terminal-muted">
          Win {pct(opportunity.kelly.winProb, 2)} of the time for{" "}
          {pct(opportunity.kelly.winPayoff, 2)} on stake; a broken hedge costs{" "}
          {pct(opportunity.kelly.lossFraction, 0)}. Expected value{" "}
          <span className="num text-terminal-long">
            {usd(opportunity.kelly.expectedValue)}
          </span>
          .
        </div>
      </div>

      <div className="mt-auto rounded border border-terminal-line bg-terminal-raised p-2">
        <div className="mb-1.5 flex items-center gap-2">
          <label className="text-[9px] uppercase tracking-[0.14em] text-terminal-muted">
            size
          </label>
          <input
            type="number"
            min={1}
            value={size}
            onChange={(event) => setSize(Math.max(1, Number(event.target.value)))}
            className="num w-24 rounded border border-terminal-line bg-terminal-bg px-1.5 py-0.5 text-right outline-none focus:border-terminal-accent"
          />
          <label className="flex cursor-pointer items-center gap-1 text-[10px] text-terminal-muted">
            <input
              type="checkbox"
              checked={breakLeg}
              onChange={(event) => setBreakLeg(event.target.checked)}
              className="accent-[var(--color-terminal-short)]"
            />
            break a leg
          </label>
          <button
            onClick={run}
            disabled={busy}
            className="ml-auto rounded border border-terminal-accent px-2 py-0.5 text-[10px] uppercase tracking-wider text-terminal-accent transition-colors hover:bg-terminal-accent hover:text-terminal-bg disabled:opacity-40"
          >
            {busy ? "..." : "simulate fill"}
          </button>
        </div>

        {error && <div className="text-[10px] text-terminal-short">{error}</div>}

        {trade && (
          <div className="space-y-1">
            <div className="grid grid-cols-4 gap-2">
              <Cell label="capital" value={usd(trade.capitalDeployed, 0)} />
              <Cell
                label="pnl if yes"
                value={usd(trade.pnlIfYes)}
                color={
                  trade.pnlIfYes >= 0
                    ? "var(--color-terminal-long)"
                    : "var(--color-terminal-short)"
                }
              />
              <Cell
                label="pnl if no"
                value={usd(trade.pnlIfNo)}
                color={
                  trade.pnlIfNo >= 0
                    ? "var(--color-terminal-long)"
                    : "var(--color-terminal-short)"
                }
              />
              <Cell
                label="hedged"
                value={trade.hedged ? "yes" : "NO"}
                color={
                  trade.hedged
                    ? "var(--color-terminal-long)"
                    : "var(--color-terminal-short)"
                }
              />
            </div>
            <p className="text-[10px] leading-relaxed text-terminal-muted">
              {trade.hedged
                ? "Both legs filled in full: the basket pays $1.00 whichever way the event resolves, so the two PnL figures are identical and locked."
                : "One leg is missing, so the position is directional. The two PnL figures now straddle zero and the difference is the risk the screen was hiding."}
            </p>
            {trade.notes.map((note, index) => (
              <div key={index} className="text-[10px] text-terminal-warn">
                {note}
              </div>
            ))}
          </div>
        )}
      </div>
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
