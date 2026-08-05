import { useQuery } from "@tanstack/react-query";

import { http } from "./client";
import { Envelope } from "./types";

export interface TrendPoint {
  label: string;
  value: number;
}

export interface Overview {
  date: string;
  broiler: {
    entries_today: number;
    mortality_today: number;
    active_batches: number;
    farms: number;
    mortality_7d: TrendPoint[];
    /* Today's Overview. Optional so an older server still parses. */
    birds_placed_today?: number;
    feed_kg_today?: number;
    /** A share of the birds alive, not a raw count. */
    mortality_pct_today?: number;
    /** Live indicator: feed eaten against live weight, across open batches. */
    fcr?: number;
    live_birds?: number;
  };
  hatchery: {
    egg_purchases_today: number;
    hatch_entries_today: number;
    chicks_today: number;
  };
  sms: { total_today: number; sent_today: number; failed_today: number };
  // Optional: only present once the extended /stats/overview backend is deployed.
  inventory?: { items: number; transfers_today: number };
  account?: { vouchers_today: number; accounts: number };
  /** Today's farm visits — the count, how many are finished, and the first few. */
  visits?: {
    today: number;
    completed: number;
    rows: { farm: string; purpose: string; at: string; done: boolean }[];
  };
  /** Unread alerts: the totals for the KPI tiles and the newest few to list. */
  alerts?: {
    pending: number;
    high: number;
    rows: { title: string; severity: string; at: string }[];
  };
  /** The System Summary strip. */
  system?: {
    users: number;
    farms: number;
    stores: number;
    items: number;
    batches: number;
  };
}

export async function fetchOverview(): Promise<Overview> {
  const resp = await http.get<Envelope<Overview>>("/stats/overview");
  return resp.data.data;
}

/** Cached dashboard KPIs for the Home screen. */
export function useOverview() {
  return useQuery({
    queryKey: ["stats-overview"],
    queryFn: fetchOverview,
    staleTime: 60_000,
  });
}
