import type { BookDetail, HistoryPoint, MonteCarloResult, SimulatedTrade } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const WS_URL = API_BASE.replace(/^http/, "ws") + "/ws/stream";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${detail.slice(0, 200)}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  book: (venue: string, marketId: string) =>
    request<BookDetail>(`/api/markets/${venue}/${encodeURIComponent(marketId)}/book`),

  history: (eventKey: string) =>
    request<{ eventKey: string; points: HistoryPoint[] }>(
      `/api/events/${encodeURIComponent(eventKey)}/history`,
    ),

  execute: (opportunityId: string, size: number, dropLegs: number[] = []) =>
    request<{ trade: SimulatedTrade }>("/api/simulate/execute", {
      method: "POST",
      body: JSON.stringify({ opportunityId, size, dropLegs, persist: false }),
    }),

  monteCarlo: (params: Record<string, number>) =>
    request<MonteCarloResult>("/api/simulate/montecarlo", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  patchConfig: (updates: Record<string, number>) =>
    request<{ applied: Record<string, number> }>("/api/config", {
      method: "PATCH",
      body: JSON.stringify(updates),
    }),
};
