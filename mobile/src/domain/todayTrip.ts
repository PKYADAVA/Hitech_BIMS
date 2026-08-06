import { Row } from "@/api/types";

/** What state today's trip is in, and so what the card offers. */
export type TripState = "none" | "open" | "closed";

export interface TodayTripView {
  state: TripState;
  /** The trip number once there is one, else that there is not one. */
  title: string;
  /** The one line under it: when it started, or how it finished. */
  detail: string;
  /**
   * Where the day stands, always present.
   *
   * Named in the driver's words — not started, started, ended — rather than
   * the database's "In Progress"/"Completed", and never omitted: a card with
   * no badge leaves "no trip today" and "the card failed to load" looking
   * exactly alike.
   */
  badge: { label: string; tone: "neutral" | "success" | "warning" };
  /** The single action this state needs, or none once the day is settled. */
  action?: "start" | "end";
}

/** "08:14" from an ISO stamp; "" for nothing, or for something unparseable. */
export function clockOf(value: unknown): string {
  if (!value) return "";
  const at = new Date(String(value));
  return Number.isNaN(at.getTime())
    ? "" : at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/**
 * Today's trip as one card reads it.
 *
 * Distance is only real once the run is closed, so an open trip says when the
 * driver set off rather than showing a running 0 km that looks like a fault.
 * A trip with no start stamp — recorded from the back office, where there is
 * no photograph to stamp — still gets a line, because a card that says nothing
 * is indistinguishable from one that failed to load.
 */
export function describeTodayTrip(trip: Row | null | undefined): TodayTripView {
  if (!trip) {
    return {
      state: "none",
      title: "No trip yet",
      detail: "Nothing logged today.",
      badge: { label: "not started", tone: "warning" },
      action: "start",
    };
  }
  const title = String(trip.trip_no ?? "Today's Trip");
  if (trip.status === "Completed") {
    const ended = clockOf(trip.end_photo_at);
    return {
      state: "closed",
      title,
      detail: [ended && `Ended ${ended}`, `${trip.distance_km ?? 0} km`]
        .filter(Boolean).join(" · "),
      badge: { label: "ended", tone: "success" },
    };
  }
  const started = clockOf(trip.start_photo_at);
  return {
    state: "open",
    title,
    detail: [started && `Started ${started}`, trip.registration]
      .filter(Boolean).join(" · ") || "On the road",
    badge: { label: "started", tone: "neutral" },
    action: "end",
  };
}
