import { Row } from "@/api/types";

/**
 * What state today's trip is in, and so what the card offers.
 *
 * `unlinked` is not a state of the trip but of the login: a trip is filed
 * against an employee, so a login with no employee record has no day of its
 * own to show. It gets a state rather than a hidden card because a card that
 * simply is not there is indistinguishable from one that failed — which is
 * exactly what happened: no employee in the database had a login attached, so
 * the card was invisible to every user and looked broken.
 */
export type TripState = "unlinked" | "none" | "open" | "closed";

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
export function describeTodayTrip(
  trip: Row | null | undefined,
  /** Whether the login maps to an employee. Trips are filed against one. */
  linked = true,
): TodayTripView {
  if (!linked) {
    // No Start button: the server refuses the same request with the same
    // reason, and a button that cannot work is worse than no button.
    return {
      state: "unlinked",
      title: "Not set up yet",
      // Short enough to fit the card's two lines beside the badge — the longer
      // version truncated mid-sentence, which is worse than not explaining.
      detail: "Your login is not linked to an employee record. Ask HR.",
      badge: { label: "not linked", tone: "warning" },
    };
  }
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
