export type Venue = "polymarket" | "kalshi";
export type ArbType = "same_venue_under" | "same_venue_over" | "cross_venue";

export interface Leg {
  venue: Venue;
  marketId: string;
  side: "yes" | "no";
  action: "buy" | "sell";
  touchPrice: number;
  avgPrice: number;
  size: number;
  fee: number;
  slippage: number;
  levelsConsumed: number;
  notional: number;
}

export interface Kelly {
  fullFraction: number;
  appliedFraction: number;
  stake: number;
  contracts: number;
  winPayoff: number;
  winProb: number;
  lossFraction: number;
  expectedValue: number;
  expectedLogGrowth: number;
  bindingConstraint: "kelly" | "depth" | "cap" | "risk" | "none";
}

export interface Opportunity {
  id: string;
  arbType: ArbType;
  eventKey: string;
  title: string;
  legs: Leg[];
  grossEdge: number;
  netEdge: number;
  netEdgeBps: number;
  maxSize: number;
  capitalRequired: number;
  expectedProfit: number;
  returnOnCapital: number;
  fillProbability: number;
  venues: Venue[];
  ts: number;
  kelly: Kelly;
}

export interface DivergenceRow {
  eventKey: string;
  title: string;
  mids: Partial<Record<Venue, number>>;
  divergence: number;
  divergenceBps: number;
  richVenue: Venue;
  cheapVenue: Venue;
  ts: number;
}

export interface BookSummary {
  venue: Venue;
  marketId: string;
  eventKey: string;
  title: string;
  mid: number | null;
  ts: number;
  tick: number;
  yes: { bids: [number, number][]; asks: [number, number][] };
  no: { bids: [number, number][]; asks: [number, number][] };
}

export interface FeedStatus {
  venue: string;
  connected: boolean;
  messages: number;
  lastMessageAt: number | null;
  staleness: number | null;
  reconnects: number;
  error: string | null;
  markets: number;
}

export interface EnginePoint {
  ts: number;
  bestNetEdge: number;
  count: number;
  totalProfit: number;
}

export interface EngineConfig {
  feedMode: string;
  minNetEdge: number;
  maxPositionSize: number;
  maxBookAge: number;
  bankroll: number;
  kellyMultiplier: number;
  maxFractionPerTrade: number;
  lossFraction: number;
  slippage: {
    latencyMs: number;
    decayPer100ms: number;
    adverseTick: number;
    displayedSizeCredibility: number;
  };
  fees: Record<string, Record<string, unknown>>;
  cacheBackend: string;
}

export interface Snapshot {
  type: string;
  ts: number;
  opportunities: Opportunity[];
  divergence: DivergenceRow[];
  books: BookSummary[];
  feeds: FeedStatus[];
  stats: {
    startedAt: number;
    uptime: number;
    scans: number;
    bookUpdates: number;
    opportunitiesSeen: number;
    cumulativeScreenedProfit: number;
    lastScanMs: number;
  };
  edgeHistory: EnginePoint[];
  config: EngineConfig;
}

export interface DepthRow {
  price: number;
  size: number;
  cumulative: number;
}

export interface BookDetail {
  venue: Venue;
  marketId: string;
  eventKey: string;
  title: string;
  ts: number;
  age: number;
  yes: {
    bids: DepthRow[];
    asks: DepthRow[];
    bestBid: number | null;
    bestAsk: number | null;
    mid: number | null;
    spread: number | null;
  };
  no: {
    bids: DepthRow[];
    asks: DepthRow[];
    bestBid: number | null;
    bestAsk: number | null;
    mid: number | null;
    spread: number | null;
  };
  costCurve: {
    yesBuy: { size: number; avgPrice: number; slippage: number; slippageBps: number }[];
    noBuy: { size: number; avgPrice: number; slippage: number; slippageBps: number }[];
  };
}

export interface HistoryPoint {
  ts: number;
  divergence: number;
  [venue: string]: number;
}

export interface Fill {
  venue: Venue;
  marketId: string;
  side: "yes" | "no";
  action: "buy" | "sell";
  requestedSize: number;
  filledSize: number;
  avgPrice: number;
  fee: number;
  cashOut: number;
  complete: boolean;
}

export interface SimulatedTrade {
  opportunityId: string;
  arbType: ArbType;
  fills: Fill[];
  requestedSize: number;
  capitalDeployed: number;
  pnlIfYes: number;
  pnlIfNo: number;
  hedged: boolean;
  worstCase: number;
  realizedEdge: number;
  notes: string[];
}

export interface MonteCarloResult {
  params: Record<string, number>;
  sizing: {
    fullKellyFraction: number;
    appliedFraction: number;
    winPayoff: number;
    expectedLogGrowth: number;
  };
  curves: Record<string, number[]>;
  stats: {
    medianTerminal: number;
    meanTerminal: number;
    p5Terminal: number;
    p95Terminal: number;
    medianReturn: number;
    medianMaxDrawdown: number;
    worstMaxDrawdown: number;
    probHalved: number;
    sharpe: number;
  };
}
