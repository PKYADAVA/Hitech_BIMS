/**
 * The Daily Entry rules the grid depends on but cannot show you it got right.
 *
 * The screen derives each row's date instead of asking for one, and shows the
 * feed left on the farm after the row. Both are arithmetic that is wrong in
 * ways nobody notices on a phone — a day off by one, a balance that ignores
 * the row above — so they live here as pure functions and are checked here.
 */
import { addDays, farmFeedBalance, todayISO, type FeedRow } from "./dailyEntry";

describe("addDays", () => {
  it("advances a day", () => {
    expect(addDays("2026-08-01", 1)).toBe("2026-08-02");
  });

  it("crosses a month end", () => {
    expect(addDays("2026-08-31", 1)).toBe("2026-09-01");
  });

  it("crosses a year end", () => {
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });

  it("handles a leap day", () => {
    expect(addDays("2028-02-28", 1)).toBe("2028-02-29");
    expect(addDays("2027-02-28", 1)).toBe("2027-03-01");
  });

  it("advances by more than one, which is how a second row on the same farm is dated", () => {
    expect(addDays("2026-08-01", 3)).toBe("2026-08-04");
  });

  it("returns the same day for zero", () => {
    expect(addDays("2026-08-01", 0)).toBe("2026-08-01");
  });

  it("does not shift the day under a timezone", () => {
    // Parsing "2026-08-01" as a timestamp and formatting it locally is what
    // turns it into 31 July west of UTC. The parts are used instead.
    expect(addDays("2026-08-01", 1)).toBe("2026-08-02");
    expect(addDays("2026-01-01", 1)).toBe("2026-01-02");
  });
});

describe("todayISO", () => {
  it("is a plain ISO date", () => {
    expect(todayISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("is the device's day, not UTC's", () => {
    const now = new Date();
    const expected = [
      String(now.getFullYear()),
      String(now.getMonth() + 1).padStart(2, "0"),
      String(now.getDate()).padStart(2, "0"),
    ].join("-");
    expect(todayISO()).toBe(expected);
  });
});

describe("farmFeedBalance", () => {
  const row = (over: Partial<FeedRow> = {}): FeedRow => ({ farm: "1", ...over });

  it("is the opening balance less this row's kgs", () => {
    expect(farmFeedBalance(100, "7", [], 20)).toBe(80);
  });

  it("subtracts an earlier row feeding the same item", () => {
    const above = [row({ feed_1: "7", feed_1_qty: "30" })];
    expect(farmFeedBalance(100, "7", above, 20)).toBe(50);
  });

  it("ignores earlier rows feeding a different item", () => {
    const above = [row({ feed_1: "9", feed_1_qty: "30" })];
    expect(farmFeedBalance(100, "7", above, 20)).toBe(80);
  });

  it("counts the item in either slot — one store, two boxes", () => {
    const above = [
      row({ feed_1: "7", feed_1_qty: "10" }),
      row({ feed_2: "7", feed_2_qty: "15" }),
    ];
    expect(farmFeedBalance(100, "7", above, 5)).toBe(70);
  });

  it("counts both slots of a single row using the same item twice", () => {
    const above = [row({ feed_1: "7", feed_1_qty: "10", feed_2: "7", feed_2_qty: "10" })];
    expect(farmFeedBalance(100, "7", above, 0)).toBe(80);
  });

  it("goes negative rather than clamping, so shortage is visible", () => {
    expect(farmFeedBalance(10, "7", [], 25)).toBe(-15);
  });

  it("treats a blank or missing quantity as nothing fed", () => {
    const above = [row({ feed_1: "7", feed_1_qty: "" }), row({ feed_1: "7" })];
    expect(farmFeedBalance(100, "7", above, 0)).toBe(100);
  });

  it("ignores a quantity that is not a number", () => {
    const above = [row({ feed_1: "7", feed_1_qty: "abc" })];
    expect(farmFeedBalance(100, "7", above, 0)).toBe(100);
  });

  it("handles fractional kgs", () => {
    expect(farmFeedBalance(100, "7", [row({ feed_1: "7", feed_1_qty: "12.5" })], 7.25))
      .toBeCloseTo(80.25);
  });
});
