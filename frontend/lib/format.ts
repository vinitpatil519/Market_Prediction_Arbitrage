/** Formatting helpers. Prices are dollars per $1 contract, so they read as
 *  cents; edges are basis points of the $1 payout. */

export const cents = (value: number | null | undefined, digits = 1): string =>
  value === null || value === undefined ? "--" : `${(value * 100).toFixed(digits)}c`;

export const bps = (value: number | null | undefined, digits = 0): string =>
  value === null || value === undefined ? "--" : `${value.toFixed(digits)}`;

export const usd = (value: number | null | undefined, digits = 2): string =>
  value === null || value === undefined
    ? "--"
    : `$${value.toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      })}`;

export const qty = (value: number | null | undefined): string =>
  value === null || value === undefined
    ? "--"
    : Math.round(value).toLocaleString("en-US");

export const pct = (value: number | null | undefined, digits = 1): string =>
  value === null || value === undefined ? "--" : `${(value * 100).toFixed(digits)}%`;

export const clock = (ts: number): string =>
  new Date(ts * 1000).toLocaleTimeString("en-US", { hour12: false });

export const VENUE_COLOR: Record<string, string> = {
  polymarket: "var(--color-polymarket)",
  kalshi: "var(--color-kalshi)",
};

export const ARB_LABEL: Record<string, string> = {
  same_venue_under: "SAME · UNDER $1",
  same_venue_over: "SAME · OVER $1",
  cross_venue: "CROSS VENUE",
};

export const CONSTRAINT_LABEL: Record<string, string> = {
  kelly: "Kelly optimum",
  depth: "capped by book depth",
  cap: "capped by per-trade limit",
  risk: "rejected: edge < break risk",
  none: "no capital allocated",
};

/** Edge quality band, used consistently by the gauge and the table. */
export function edgeBand(netEdgeBps: number): "none" | "thin" | "good" | "rich" {
  if (netEdgeBps <= 0) return "none";
  if (netEdgeBps < 50) return "thin";
  if (netEdgeBps < 150) return "good";
  return "rich";
}

export const BAND_COLOR: Record<string, string> = {
  none: "var(--color-terminal-muted)",
  thin: "var(--color-terminal-warn)",
  good: "var(--color-terminal-accent)",
  rich: "var(--color-terminal-long)",
};
