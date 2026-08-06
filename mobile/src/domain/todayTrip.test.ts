import { Row } from "@/api/types";
import { describeTodayTrip } from "./todayTrip";
import { todayISO } from "@/api/trips";

const trip = (over: Partial<Row> = {}): Row =>
  ({ id: 1, trip_no: "TRP-2026-0007", status: "In Progress", ...over } as Row);

describe("describeTodayTrip", () => {
  it("offers Start when nothing is logged", () => {
    const v = describeTodayTrip(null);
    expect(v.state).toBe("none");
    expect(v.action).toBe("start");
    expect(v.badge).toBeUndefined();
    expect(v.detail).toMatch(/nothing logged/i);
    // Not "Today's Trip" — the section above the card already says that, and
    // a card echoing its own heading tells the reader nothing.
    expect(v.title).toBe("Not started");
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
    expect(v.badge).toEqual({ label: "in progress", tone: "neutral" });
    expect(v.detail).toContain("UP53 XX 9876");
    expect(v.detail).toMatch(/^Started \d{1,2}:\d{2}/);
  });

  it("does not show a running distance on an open trip", () => {
    // 0 km against a trip still being driven reads as a fault, not a fact.
    expect(describeTodayTrip(trip({ distance_km: 0 })).detail).not.toContain("km");
  });

  it("still says something when the trip has no start stamp", () => {
    // Recorded from the back office: no photograph, so nothing to stamp.
    expect(describeTodayTrip(trip()).detail).toBe("In progress");
  });

  it("offers no action once the trip is settled, and shows the distance", () => {
    const v = describeTodayTrip(trip({
      status: "Completed", end_photo_at: "2026-08-06T18:02:00Z", distance_km: 68,
    }));
    expect(v.state).toBe("closed");
    expect(v.action).toBeUndefined();
    expect(v.badge).toEqual({ label: "completed", tone: "success" });
    expect(v.detail).toContain("68 km");
  });

  it("survives a timestamp it cannot parse", () => {
    const v = describeTodayTrip(trip({ start_photo_at: "not a date" }));
    expect(v.detail).toBe("In progress");
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
