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
  /** What was actually applied, echoed back. */
  filters?: { farm: string; period: string };
  /** The farm picker's options — the user's own farms. */
  farm_options?: { id: number; name: string }[];
  system?: {
    users: number;
    farms: number;
    stores: number;
    items: number;
    batches: number;
  };
}

/** The dashboard's filters: a farm (blank = all) and how wide a window. */
export interface OverviewFilters {
  farm?: string;
  period?: "today" | "week" | "month";
}

export async function fetchOverview(filters: OverviewFilters = {}): Promise<Overview> {
  const resp = await http.get<Envelope<Overview>>("/stats/overview", {
    params: {
      ...(filters.farm ? { farm: filters.farm } : {}),
      ...(filters.period && filters.period !== "today" ? { period: filters.period } : {}),
    },
  });
  return resp.data.data;
}

/** Cached dashboard KPIs for the Home screen. */
export function useOverview(filters: OverviewFilters = {}) {
  return useQuery({
    // The filters are part of the key, so switching farm or window fetches
    // rather than showing the previous selection's numbers.
    queryKey: ["stats-overview", filters.farm ?? "", filters.period ?? "today"],
    queryFn: () => fetchOverview(filters),
    staleTime: 60_000,
  });
}
