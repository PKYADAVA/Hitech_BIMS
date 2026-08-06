import { Row } from "@/api/types";
import { describeTodayTrip } from "./todayTrip";
import { todayISO } from "@/api/trips";

const trip = (over: Partial<Row> = {}): Row =>
  ({ id: 1, trip_no: "TRP-2026-0007", status: "In Progress", ...over } as Row);

describe("describeTodayTrip", () => {
  it("says not started, and offers Start, when nothing is logged", () => {
    const v = describeTodayTrip(null);
    expect(v.state).toBe("none");
    expect(v.action).toBe("start");
    expect(v.badge).toEqual({ label: "not started", tone: "warning" });
    expect(v.detail).toMatch(/nothing logged/i);
    // Not "Today's Trip" — the section above the card already says that, and
    // a card echoing its own heading tells the reader nothing.
    expect(v.title).toBe("No trip yet");
  });

  it("explains itself when the login maps to no employee", () => {
    // The condition that made the card invisible to everyone. It is a setup
    // step, not a fault, and it has to read as one.
    const v = describeTodayTrip(null, false);
    expect(v.state).toBe("unlinked");
    expect(v.badge).toEqual({ label: "not linked", tone: "warning" });
    expect(v.detail).toMatch(/not linked to an employee/i);
    // No Start button: the server refuses it for the same reason.
    expect(v.action).toBeUndefined();
  });

  it("treats a login as linked unless told otherwise", () => {
    expect(describeTodayTrip(null).state).toBe("none");
  });

  it("names the state in every one of them", () => {
    // The badge is what the driver reads first, so it is never absent: a card
    // with no status looks the same as one that failed to load.
    const labels = [
      describeTodayTrip(null),
      describeTodayTrip(trip()),
      describeTodayTrip(trip({ status: "Completed" })),
    ].map((v) => v.badge.label);
    expect(labels).toEqual(["not started", "started", "ended"]);
  });

  it("treats a missing answer the same as no trip, not as an error", () => {
    expect(describeTodayTrip(undefined).action).toBe("start");
  });

  it("offers End while the trip is open, and leads with the start time", () => {
    const v = describeTodayTrip(trip({
      start_photo_at: "2026-08-06T08:14:00Z", registration: "UP53 XX 9876",
    }));
    expect(v.state).toBe("open");
    expect(v.action).toBe("end");
    expect(v.title).toBe("TRP-2026-0007");
    expect(v.badge).toEqual({ label: "started", tone: "neutral" });
    expect(v.detail).toContain("UP53 XX 9876");
    expect(v.detail).toMatch(/^Started \d{1,2}:\d{2}/);
  });

  it("does not show a running distance on an open trip", () => {
    // 0 km against a trip still being driven reads as a fault, not a fact.
    expect(describeTodayTrip(trip({ distance_km: 0 })).detail).not.toContain("km");
  });

  it("still says something when the trip has no start stamp", () => {
    // Recorded from the back office: no photograph, so nothing to stamp.
    expect(describeTodayTrip(trip()).detail).toBe("On the road");
  });

  it("offers no action once the trip is settled, and shows the distance", () => {
    const v = describeTodayTrip(trip({
      status: "Completed", end_photo_at: "2026-08-06T18:02:00Z", distance_km: 68,
    }));
    expect(v.state).toBe("closed");
    expect(v.action).toBeUndefined();
    expect(v.badge).toEqual({ label: "ended", tone: "success" });
    expect(v.detail).toContain("68 km");
  });

  it("survives a timestamp it cannot parse", () => {
    const v = describeTodayTrip(trip({ start_photo_at: "not a date" }));
    expect(v.detail).toBe("On the road");
  });
});

describe("todayISO", () => {
  it("uses the local date, not UTC — the day belongs to the driver", () => {
    // 00:30 local on the 6th is still the 5th in UTC for +05:30.
    expect(todayISO(new Date(2026, 7, 6, 0, 30))).toBe("2026-08-06");
  });

  it("pads month and day", () => {
    expect(todayISO(new Date(2026, 0, 9))).toBe("2026-01-09");
  });
});
