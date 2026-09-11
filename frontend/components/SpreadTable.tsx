"use client";

import { useEffect, useRef, useState } from "react";
import type { Opportunity } from "@/lib/types";
import {
  ARB_LABEL,
  BAND_COLOR,
  CONSTRAINT_LABEL,
  VENUE_COLOR,
  cents,
  edgeBand,
  pct,
  qty,
  usd,
} from "@/lib/format";
import { Empty } from "./Panel";

const VENUE_TAG: Record<string, string> = { polymarket: "PM", kalshi: "KX" };

export function SpreadTable({
  opportunities,
  selectedId,
  onSelect,
}: {
  opportunities: Opportunity[];
  selectedId: string | null;
  onSelect: (opportunity: Opportunity) => void;
}) {
  const seen = useRef<Set<string>>(new Set());
  const [fresh, setFresh] = useState<Set<string>>(new Set());

  useEffect(() => {
    const incoming = opportunities.filter((o) => !seen.current.has(o.id)).map((o) => o.id);
    if (incoming.length) {
      incoming.forEach((id) => seen.current.add(id));
      setFresh(new Set(incoming));
      const timer = setTimeout(() => setFresh(new Set()), 700);
      return () => clearTimeout(timer);
    }
  }, [opportunities]);

  if (!opportunities.length) {
    return (
      <Empty message="Screen is flat. Every book is priced inside the cost of trading it." />
    );
  }

  return (
    <div className="h-full overflow-auto">
      <table className="w-full border-collapse text-[11px]">
        <thead className="sticky top-0 z-10 bg-terminal-panel">
          <tr className="border-b border-terminal-line text-[9px] uppercase tracking-[0.1em] text-terminal-muted">
            <Th className="text-left">type</Th>
            <Th className="text-left">event</Th>
            <Th className="text-left">legs</Th>
            <Th>gross</Th>
            <Th>net bps</Th>
            <Th>size</Th>
            <Th>capital</Th>
            <Th>profit</Th>
            <Th>roc</Th>
            <Th>kelly</Th>
            <Th>p(fill)</Th>
          </tr>
        </thead>
        <tbody>
          {opportunities.map((opportunity) => {
            const band = edgeBand(opportunity.netEdgeBps);
            const selected = opportunity.id === selectedId;
            const tradeable = opportunity.kelly.stake > 0;
            return (
              <tr
                key={opportunity.id}
                onClick={() => onSelect(opportunity)}
                className={`cursor-pointer border-b border-terminal-line/60 transition-colors hover:bg-terminal-raised ${
                  selected ? "bg-terminal-raised" : ""
                } ${fresh.has(opportunity.id) ? "flash" : ""}`}
              >
                <Td className="text-left">
                  <span
                    className="rounded-sm px-1 py-0.5 text-[9px] tracking-wide"
                    style={{
                      background: "var(--color-terminal-raised)",
                      color:
                        opportunity.arbType === "cross_venue"
                          ? "var(--color-terminal-accent)"
                          : "var(--color-terminal-muted)",
                    }}
                  >
                    {ARB_LABEL[opportunity.arbType]}
                  </span>
                </Td>
                <Td className="max-w-[240px] truncate text-left text-terminal-text">
                  {opportunity.title}
                </Td>
                <Td className="text-left">
                  <div className="flex flex-wrap gap-x-2 gap-y-0.5">
                    {opportunity.legs.map((leg, index) => (
                      <span key={index} className="whitespace-nowrap">
                        <span style={{ color: VENUE_COLOR[leg.venue] }}>
                          {VENUE_TAG[leg.venue]}
                        </span>
                        <span
                          className={
                            leg.action === "buy"
                              ? "text-terminal-long"
                              : "text-terminal-short"
                          }
                        >
                          {" "}
                          {leg.action === "buy" ? "B" : "S"}
                        </span>
                        <span className="text-terminal-muted"> {leg.side.toUpperCase()} </span>
                        <span className="num">{cents(leg.avgPrice)}</span>
                      </span>
                    ))}
                  </div>
                </Td>
                <Td className="num text-terminal-muted">
                  {(opportunity.grossEdge * 10_000).toFixed(0)}
                </Td>
                <Td className="num font-semibold" style={{ color: BAND_COLOR[band] }}>
                  {opportunity.netEdgeBps.toFixed(0)}
                </Td>
                <Td className="num">{qty(opportunity.maxSize)}</Td>
                <Td className="num text-terminal-muted">
                  {usd(opportunity.capitalRequired, 0)}
                </Td>
                <Td className="num text-terminal-long">
                  {usd(opportunity.expectedProfit)}
                </Td>
                <Td className="num text-terminal-muted">
                  {pct(opportunity.returnOnCapital, 2)}
                </Td>
                <Td
                  className="num"
                  title={CONSTRAINT_LABEL[opportunity.kelly.bindingConstraint]}
                  style={{
                    color: tradeable
                      ? "var(--color-terminal-text)"
                      : "var(--color-terminal-short)",
                  }}
                >
                  {tradeable ? usd(opportunity.kelly.stake, 0) : "reject"}
                </Td>
                <Td className="num text-terminal-muted">
                  {pct(opportunity.fillProbability, 1)}
                </Td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Th({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <th className={`px-2 py-1.5 text-right font-medium ${className}`}>{children}</th>
  );
}

function Td({
  children,
  className = "",
  ...rest
}: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td className={`px-2 py-1.5 text-right align-top ${className}`} {...rest}>
      {children}
    </td>
  );
}
