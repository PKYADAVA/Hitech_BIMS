import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { http } from "./client";
import { Envelope } from "./types";

/** One call on the round, as the server describes it. */
export interface RouteStop {
  sequence: number;
  kind: "start" | "farm" | "end";
  farm_id: number | null;
  farm_code: string;
  label: string;
  latitude: number | null;
  longitude: number | null;
  leg_distance_km: number;
  leg_minutes: number;
  cumulative_distance_km: number;
  priority: string;
  visited_at: string | null;
  /**
   * What the button says. Decided on the server rather than inferred here, so
   * the phone and the trip register cannot come to different views about
   * whether a call is still open.
   */
  state: "pending" | "here" | "done";
}

export interface FarmRoute {
  id: number;
  route_no: string;
  date: string;
  status: string;
  supervisor: string;
  branch: string;
  start_label: string;
  start_latitude: number | null;
  start_longitude: number | null;
  farm_count: number;
  distance_km: number;
  minutes: number;
  duration_label: string;
  /** True when the kilometres are straight-line estimates, not road distances. */
  estimated: boolean;
  trip_id: number | null;
  trip_no: string;
  stops: RouteStop[];
}

export interface MyRouteResponse {
  route: FarmRoute | null;
  message?: string;
}

const KEY = ["my-route"];

/** The round this supervisor is driving today. */
export function useMyRoute(enabled = true) {
  return useQuery({
    queryKey: KEY,
    enabled,
    queryFn: async (): Promise<MyRouteResponse> => {
      const resp = await http.get<Envelope<MyRouteResponse>>("/broiler/my-route");
      return resp.data.data;
    },
  });
}

/**
 * The three things a supervisor does to a round from the road.
 *
 * Each returns the refreshed route, so the list redraws from the server's own
 * answer rather than from a guess made here about what the write did.
 */
export function useRouteActions() {
  const client = useQueryClient();

  const apply = (data: { route?: FarmRoute }) => {
    if (data.route) {
      client.setQueryData(KEY, (old: MyRouteResponse | undefined) => ({
        ...(old ?? {}),
        route: data.route!,
      }));
    } else {
      void client.invalidateQueries({ queryKey: KEY });
    }
  };

  const startTrip = useMutation({
    mutationFn: async (routeId: number) => {
      const resp = await http.post<Envelope<{ trip_no: string; route: FarmRoute }>>(
        `/broiler/routes/${routeId}/start-trip`
      );
      return resp.data.data;
    },
    onSuccess: apply,
  });

  const checkIn = useMutation({
    mutationFn: async (args: {
      routeId: number;
      farmId: number;
      latitude?: number | null;
      longitude?: number | null;
    }) => {
      const resp = await http.post<Envelope<{ route: FarmRoute }>>(
        `/broiler/routes/${args.routeId}/check-in`,
        { farm_id: args.farmId, latitude: args.latitude, longitude: args.longitude }
      );
      return resp.data.data;
    },
    onSuccess: apply,
  });

  const checkOut = useMutation({
    mutationFn: async (args: {
      routeId: number;
      farmId: number;
      latitude?: number | null;
      longitude?: number | null;
    }) => {
      const resp = await http.post<Envelope<{ route: FarmRoute }>>(
        `/broiler/routes/${args.routeId}/check-out`,
        { farm_id: args.farmId, latitude: args.latitude, longitude: args.longitude }
      );
      return resp.data.data;
    },
    onSuccess: apply,
  });

  return { startTrip, checkIn, checkOut };
}

/** "6h 42m" — the way a travel time is written across this module. */
export function durationLabel(minutes: number): string {
  const total = Math.round(minutes || 0);
  const hours = Math.floor(total / 60);
  const rest = total % 60;
  if (hours && rest) return `${hours}h ${String(rest).padStart(2, "0")}m`;
  return hours ? `${hours}h` : `${rest}m`;
}
