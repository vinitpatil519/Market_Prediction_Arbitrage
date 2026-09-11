"use client";

import { useEffect, useMemo, useState } from "react";
import { useStream } from "@/lib/useStream";
import type { Opportunity } from "@/lib/types";
import { ControlPanel } from "./ControlPanel";
import { DepthChart } from "./DepthChart";
import { DivergenceChart } from "./DivergenceChart";
import { EdgeGauge } from "./EdgeGauge";
import { OpportunityDetail } from "./OpportunityDetail";
import { Panel } from "./Panel";
import { PnlSimulator } from "./PnlSimulator";
import { SpreadTable } from "./SpreadTable";
import { StatusBar } from "./StatusBar";

export function Dashboard() {
  const { snapshot, state } = useStream();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pinnedEvent, setPinnedEvent] = useState<string | null>(null);
  const [pinnedMarket, setPinnedMarket] = useState<{ venue: string; marketId: string } | null>(
    null,
  );

  const opportunities = snapshot?.opportunities ?? [];

  // Opportunity ids are stable per basket, so a selection survives re-scans
  // as long as the same trade is still on the screen.
  const selected = useMemo<Opportunity | null>(
    () => opportunities.find((o) => o.id === selectedId) ?? null,
    [opportunities, selectedId],
  );

  // Keep the charts pointed at the last selected event even after its edge
  // closes; otherwise the panels blank out exactly when you want to see why.
  useEffect(() => {
    if (selected) {
      setPinnedEvent(selected.eventKey);
      setPinnedMarket({
        venue: selected.legs[0].venue,
        marketId: selected.legs[0].marketId,
      });
    }
  }, [selected?.id]);

  useEffect(() => {
    if (!pinnedEvent && snapshot?.divergence.length) {
      setPinnedEvent(snapshot.divergence[0].eventKey);
    }
    if (!pinnedMarket && snapshot?.books.length) {
      const book = snapshot.books[0];
      setPinnedMarket({ venue: book.venue, marketId: book.marketId });
    }
  }, [snapshot, pinnedEvent, pinnedMarket]);

  const best = opportunities[0] ?? null;
  const detail = selected ?? best;

  return (
    <main className="flex min-h-screen flex-col">
      <StatusBar snapshot={snapshot} state={state} />

      {state === "offline" && (
        <div className="border-b border-terminal-short/40 bg-terminal-short/10 px-4 py-2 text-[11px] text-terminal-short">
          Backend unreachable. Start it with{" "}
          <code className="rounded bg-terminal-raised px-1">
            uvicorn backend.app.main:app --reload
          </code>{" "}
          from the repository root.
        </div>
      )}

      <div className="grid flex-1 grid-cols-12 gap-2 p-2">
        <Panel
          title="Live spread table"
          subtitle={`${opportunities.length} priced net of fees and depth`}
          className="col-span-12 h-[44vh] xl:col-span-8"
          bodyClassName="overflow-hidden"
        >
          <SpreadTable
            opportunities={opportunities}
            selectedId={selected?.id ?? null}
            onSelect={(opportunity) => setSelectedId(opportunity.id)}
          />
        </Panel>

        <Panel
          title="Edge gauge"
          subtitle="gross vs net"
          className="col-span-12 h-[44vh] md:col-span-6 xl:col-span-4"
          bodyClassName="flex flex-col"
        >
          <div className="min-h-0 flex-1">
            <EdgeGauge best={detail} />
          </div>
          <ControlPanel config={snapshot?.config ?? null} />
        </Panel>

        <Panel
          title="Order book depth"
          subtitle={pinnedMarket?.marketId ?? ""}
          className="col-span-12 h-[36vh] xl:col-span-5"
          bodyClassName="overflow-hidden"
        >
          <DepthChart
            venue={pinnedMarket?.venue ?? null}
            marketId={pinnedMarket?.marketId ?? null}
          />
        </Panel>

        <Panel
          title="Divergence"
          subtitle="venue mids"
          className="col-span-12 h-[36vh] md:col-span-6 xl:col-span-3"
          bodyClassName="overflow-hidden"
        >
          <DivergenceChart eventKey={pinnedEvent} />
        </Panel>

        <Panel
          title="Basket breakdown"
          subtitle={detail ? detail.id : ""}
          className="col-span-12 h-[36vh] md:col-span-6 xl:col-span-4"
          bodyClassName="overflow-hidden"
        >
          <OpportunityDetail opportunity={detail} />
        </Panel>

        <Panel
          title="PnL simulator"
          subtitle="Kelly-sized paths over repeated trades"
          className="col-span-12 h-[40vh]"
          bodyClassName="overflow-hidden"
        >
          <PnlSimulator selected={detail} />
        </Panel>
      </div>
    </main>
  );
}
