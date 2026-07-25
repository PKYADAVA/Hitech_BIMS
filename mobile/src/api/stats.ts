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
  };
  hatchery: {
    egg_purchases_today: number;
    hatch_entries_today: number;
    chicks_today: number;
  };
  sms: { total_today: number; sent_today: number; failed_today: number };
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
