/**
 * The Daily Entry rules the screen depends on but cannot show you it got right.
 *
 * The screen derives each row's date instead of asking for one, shows the feed
 * left on the farm after the row, and heads the card with the flock's mortality
 * and today's feed against the breed standard. All of it is arithmetic that is
 * wrong in ways nobody notices on a phone — a day off by one, a balance that
 * ignores the row above, a percentage of the wrong base — so it lives here as
 * pure functions and is checked here.
 */
import {
  addDays, adviseDailyEntry, ageOnDate, farmFeedBalance, feedPerBirdG, feedPlanLines,
  feedStandard, feedTone, lastWeightNote, typedFeed,
  flockSummary, interpCurve, priorListFeed, todayISO, type DailyEntryLookup, type FeedRow,
} from "./dailyEntry";

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
  /** The row being drawn, as the screen passes it: its own slots and kgs. */
  const own = (qty1: string, qty2?: string, item = "7"): FeedRow =>
    row({ feed_1: item, feed_1_qty: qty1,
          ...(qty2 == null ? {} : { feed_2: item, feed_2_qty: qty2 }) });
  const none = row();

  it("is the opening balance less this row's kgs", () => {
    expect(farmFeedBalance(100, "7", [], own("20"))).toBe(80);
  });

  it("subtracts an earlier row feeding the same item", () => {
    const above = [row({ feed_1: "7", feed_1_qty: "30" })];
    expect(farmFeedBalance(100, "7", above, own("20"))).toBe(50);
  });

  it("ignores earlier rows feeding a different item", () => {
    const above = [row({ feed_1: "9", feed_1_qty: "30" })];
    expect(farmFeedBalance(100, "7", above, own("20"))).toBe(80);
  });

  it("counts the item in either slot — one store, two boxes", () => {
    const above = [
      row({ feed_1: "7", feed_1_qty: "10" }),
      row({ feed_2: "7", feed_2_qty: "15" }),
    ];
    expect(farmFeedBalance(100, "7", above, own("5"))).toBe(70);
  });

  it("counts both slots of a single row using the same item twice", () => {
    const above = [row({ feed_1: "7", feed_1_qty: "10", feed_2: "7", feed_2_qty: "10" })];
    expect(farmFeedBalance(100, "7", above, none)).toBe(80);
  });

  it("counts both slots of the row being drawn, not just the one asked about", () => {
    // One pile, two boxes: 60 through each of a 100 kg store is 20 short, and
    // charging the row for one box reported 40 left in both of them.
    expect(farmFeedBalance(100, "7", [], own("60", "60"))).toBe(-20);
  });

  it("goes negative rather than clamping, so shortage is visible", () => {
    expect(farmFeedBalance(10, "7", [], own("25"))).toBe(-15);
  });

  it("treats a blank or missing quantity as nothing fed", () => {
    const above = [row({ feed_1: "7", feed_1_qty: "" }), row({ feed_1: "7" })];
    expect(farmFeedBalance(100, "7", above, none)).toBe(100);
  });

  it("ignores a quantity that is not a number", () => {
    const above = [row({ feed_1: "7", feed_1_qty: "abc" })];
    expect(farmFeedBalance(100, "7", above, none)).toBe(100);
  });

  it("handles fractional kgs", () => {
    expect(farmFeedBalance(100, "7", [row({ feed_1: "7", feed_1_qty: "12.5" })], own("7.25")))
      .toBeCloseTo(80.25);
  });
});

describe("ageOnDate", () => {
  it("counts placement day as Age 0", () => {
    expect(ageOnDate("2026-07-22", "2026-07-22")).toBe(0);
  });

  it("makes the first entry day Age 1, as the server does", () => {
    expect(ageOnDate("2026-07-22", "2026-07-23")).toBe(1);
  });

  it("crosses a month end", () => {
    expect(ageOnDate("2026-07-22", "2026-08-04")).toBe(13);
  });

  it("never goes negative for a day before placement", () => {
    expect(ageOnDate("2026-07-22", "2026-07-20")).toBe(0);
  });

  it("is null when the placement is unknown", () => {
    expect(ageOnDate(null, "2026-08-04")).toBeNull();
    expect(ageOnDate(undefined, "2026-08-04")).toBeNull();
    expect(ageOnDate("2026-07-22", "")).toBeNull();
  });
});

describe("flockSummary", () => {
  const lookup = (over: Partial<DailyEntryLookup> = {}): DailyEntryLookup =>
    ({
      batch: 1,
      batch_name: "F-1",
      age_days: 10,
      start_date: "2026-07-22",
      next_date: "2026-08-01",
      feed_phase: null,
      std_feed_kg: null,
      std_weight_g: null,
      std_note: null,
      bs_curve: [],
      cum_feed_before_kg: null,
      consumed_by_item: [],
      consumed_total_kg: null,
      consumed_per_bird_actual_g: null,
      live_birds: 0,
      opening_birds: 5000,
      mortality_to_date: 0,
      culls_to_date: 0,
      sold_to_date: 0,
      ...over,
    }) as DailyEntryLookup;

  it("is all-live on a flock that has lost nothing", () => {
    const s = flockSummary(lookup(), { mortality: "0", culls: "0" })!;
    expect(s.live).toBe(5000);
    expect(s.livePct).toBeCloseTo(100);
    expect(s.mortalityPct).toBe(0);
  });

  it("adds what is being typed to the losses already booked", () => {
    const s = flockSummary(lookup({ mortality_to_date: 40, culls_to_date: 10 }), {
      mortality: "12",
      culls: "3",
    })!;
    expect(s.mortality).toBe(52);
    expect(s.culls).toBe(13);
    expect(s.live).toBe(5000 - 52 - 13);
  });

  it("counts birds already sold out of the live figure", () => {
    const s = flockSummary(lookup({ sold_to_date: 1000 }), {})!;
    expect(s.live).toBe(4000);
    expect(s.livePct).toBeCloseTo(80);
  });

  it("gives each loss as a share of the birds placed", () => {
    const s = flockSummary(lookup({ mortality_to_date: 50 }), {})!;
    expect(s.mortalityPct).toBeCloseTo(1);
  });

  it("never reports negative live birds", () => {
    const s = flockSummary(lookup({ mortality_to_date: 4990 }), { mortality: "100" })!;
    expect(s.live).toBe(0);
  });

  it("is null without an opening count, rather than dividing by zero", () => {
    expect(flockSummary(lookup({ opening_birds: 0 }), {})).toBeNull();
    expect(flockSummary(lookup({ opening_birds: undefined }), {})).toBeNull();
    expect(flockSummary(null, {})).toBeNull();
  });
});

describe("feedStandard", () => {
  const lookup = (over: Partial<DailyEntryLookup> = {}): DailyEntryLookup =>
    ({ live_birds: 5000, std_feed_kg: "0.013", ...over }) as DailyEntryLookup;

  it("scales the per-bird standard by the live birds", () => {
    const f = feedStandard(lookup(), { feed_1_qty: "35" })!;
    expect(f.stdKg).toBeCloseTo(65);
    expect(f.stdPerBirdG).toBeCloseTo(13);
  });

  it("adds both feed slots into the day's total", () => {
    const f = feedStandard(lookup(), { feed_1_qty: "35", feed_2_qty: "5" })!;
    expect(f.totalKg).toBe(40);
  });

  it("reports the entered feed as a percentage of standard", () => {
    const f = feedStandard(lookup({ std_feed_kg: "0.00596" }), { feed_1_qty: "35" })!;
    expect(f.stdKg).toBeCloseTo(29.8);
    expect(f.pct).toBeCloseTo(117.4, 1);
  });

  it("is null when the standard or the bird count is unknown", () => {
    expect(feedStandard(lookup({ std_feed_kg: null }), { feed_1_qty: "35" })).toBeNull();
    expect(feedStandard(lookup({ live_birds: 0 }), { feed_1_qty: "35" })).toBeNull();
    expect(feedStandard(null, { feed_1_qty: "35" })).toBeNull();
  });
});

describe("feedPerBirdG", () => {
  it("is grams per live bird", () => {
    expect(feedPerBirdG(35, 5000)).toBeCloseTo(7);
  });

  it("is null when the bird count is unknown, not Infinity", () => {
    expect(feedPerBirdG(35, 0)).toBeNull();
  });
});

describe("feedTone", () => {
  it("agrees with the written advisory at every threshold", () => {
    expect(feedTone(0)).toBe("info");     // nothing entered yet
    expect(feedTone(80)).toBe("ok");
    expect(feedTone(100)).toBe("ok");
    expect(feedTone(105)).toBe("warn");   // over, but inside tolerance
    expect(feedTone(110)).toBe("warn");
    expect(feedTone(118)).toBe("bad");    // past the 10% tolerance
    expect(feedTone(40)).toBe("bad");     // under half the standard
  });
});

describe("interpCurve", () => {
  // The real Cobb 430 head, as the lookup sends it: age 1 is already 42 g.
  const curve = [
    { a: 1, w: 42, cf: 13 },
    { a: 2, w: 56, cf: 29 },
    { a: 3, w: 74, cf: 49 },
    { a: 4, w: 94, cf: 73 },
  ];

  it("clamps below the curve instead of extrapolating to nonsense", () => {
    // A 30 g bird is lighter than the curve's first row; the answer is that
    // row's feed, not a negative one.
    expect(interpCurve(curve, "w", 30, "cf")).toBe(13);
  });

  it("clamps above the curve too", () => {
    expect(interpCurve(curve, "w", 5000, "cf")).toBe(73);
  });

  it("reads straight off a row that lands exactly on it", () => {
    expect(interpCurve(curve, "w", 56, "cf")).toBe(29);
  });

  it("interpolates between the two rows that bracket the target", () => {
    // 32.77 g/bird of feed sits between age 2 (29) and age 3 (49).
    expect(interpCurve(curve, "cf", 32.766, "w")).toBeCloseTo(59.4, 1);
  });

  it("is null with no curve or no target", () => {
    expect(interpCurve([], "w", 30, "cf")).toBeNull();
    expect(interpCurve(curve, "w", null, "cf")).toBeNull();
  });
});

describe("priorListFeed", () => {
  const lookup = {
    feed_phase: {
      phase_by_item: {
        "13": { name: "Pre-Starter Feed", ranges: [[1, 10]], max: 0.4 },
        "14": { name: "Starter Feed", ranges: [[11, 20]], max: 1.2 },
      },
    },
  } as unknown as DailyEntryLookup;

  it("totals the kilos on the rows above", () => {
    const prior = priorListFeed(lookup, [
      { farm: "1", feed_1: "13", feed_1_qty: "20" },
      { farm: "1", feed_1: "13", feed_1_qty: "25" },
    ]);
    expect(prior.total).toBe(45);
    expect(prior.byItem["Pre-Starter Feed"]).toBe(45);
  });

  it("keeps the items apart, since each has its own cap", () => {
    const prior = priorListFeed(lookup, [
      { farm: "1", feed_1: "13", feed_1_qty: "20", feed_2: "14", feed_2_qty: "5" },
    ]);
    expect(prior.byItem).toEqual({ "Pre-Starter Feed": 20, "Starter Feed": 5 });
  });

  it("ignores blank and zero quantities", () => {
    const prior = priorListFeed(lookup, [
      { farm: "1", feed_1: "13", feed_1_qty: "0" },
      { farm: "1", feed_1: "13" },
    ]);
    expect(prior).toEqual({ total: 0, byItem: {} });
  });

  it("files an item that is not in the program under a plain name", () => {
    const prior = priorListFeed(lookup, [{ farm: "1", feed_1: "99", feed_1_qty: "10" }]);
    expect(prior.byItem).toEqual({ Feed: 10 });
  });
});

/**
 * The whole notification strip, checked against a real row from the ERP:
 * Green Valley Farm, age 1, 2,289 live birds, 75 kg of Pre-Starter against a
 * 29.8 kg standard, 30 g average weight. Every figure below is the one the web
 * grid puts on screen for that row — this is what "the app shows what the ERP
 * shows" means, and it is checked rather than eyeballed.
 */
describe("adviseDailyEntry — the web grid's notification strip", () => {
  const BIRDS = 2289;
  const lookup = (over: Partial<DailyEntryLookup> = {}): DailyEntryLookup =>
    ({
      batch: 7,
      batch_name: "FARMDE2-1",
      age_days: 1,
      start_date: "2026-07-21",
      next_date: "2026-07-22",
      feed_phase: {
        program: "P",
        phase_name: "Pre-Starter Feed",
        phase_code: "PS",
        feed_item: 13,
        max_feed_qty: "0.400",
        next_name: "Starter Feed",
        next_feed_item: 14,
        phase_by_item: {
          "13": { name: "Pre-Starter Feed", ranges: [[1, 10]], max: 0.4 },
        },
      },
      std_feed_kg: "0.013",
      std_weight_g: "42.0",
      std_note: null,
      bs_curve: [
        { a: 1, w: 42, cf: 13 },
        { a: 2, w: 56, cf: 29 },
        { a: 3, w: 74, cf: 49 },
      ],
      cum_feed_before_kg: "0.00",
      consumed_by_item: [],
      consumed_total_kg: "0.00",
      consumed_per_bird_actual_g: "0.00",
      live_birds: BIRDS,
      ...over,
    }) as unknown as DailyEntryLookup;

  const values = { feed_1: "13", feed_1_qty: "75", avg_weight_gms: "30" };
  const text = (a: ReturnType<typeof adviseDailyEntry>) => a.notes.map((n) => n.text).join("\n");

  it("flags the day's feed against the standard, as the ERP does", () => {
    expect(text(adviseDailyEntry(lookup(), values)))
      .toContain("Total 75.0 kg exceeds Std 29.8 kg/day (252% of std)");
  });

  it("reads the standard feed off the curve at the weight entered", () => {
    expect(text(adviseDailyEntry(lookup(), values)))
      .toContain("Std feed @ this wt: 13 g/bird · 29.8 kg total");
  });

  it("reads the standard weight off the curve at the feed entered", () => {
    expect(text(adviseDailyEntry(lookup(), values))).toContain("Std wt @ this feed: 59 g");
  });

  it("shows the running total this entry rolls into", () => {
    expect(text(adviseDailyEntry(lookup(), values))).toContain(
      "Consumed to date: 0.0 kg · 0.0 g/bird  + this entry 75.0 kg · 32.8 g/bird" +
        " → New total 75.0 kg · 32.8 g/bird"
    );
  });

  it("shows feed per surviving bird, bird-day weighted", () => {
    expect(text(adviseDailyEntry(lookup(), values))).toContain(
      "Actual eaten / live bird: 0.0 g → 32.8 g with this entry" +
        " (bird-day weighted, excludes dead-bird feed)"
    );
  });

  it("gauges the feed against its changeover cap", () => {
    const cap = adviseDailyEntry(lookup(), values).cap!;
    expect(cap.name).toBe("Pre-Starter Feed");
    expect(cap.cum).toBeCloseTo(0.033, 3);
    expect(cap.cap).toBe(0.4);
    expect(Math.round(cap.pct)).toBe(8);
  });

  it("calls the row Needs Review, matching the ERP's pill", () => {
    expect(adviseDailyEntry(lookup(), values).statusLabel).toBe("Needs Review");
  });

  it("is Near Limit when feed is over standard but inside tolerance", () => {
    // 31 kg against a 29.8 kg standard — over, but not by 10%.
    const a = adviseDailyEntry(lookup(), { feed_1: "13", feed_1_qty: "31" });
    expect(a.issues).toEqual([]);
    expect(a.statusLabel).toBe("Near Limit");
  });

  it("is Within Standard on a clean row", () => {
    const a = adviseDailyEntry(lookup(), {
      feed_1: "13",
      feed_1_qty: "29",
      avg_weight_gms: "42",
    });
    expect(a.statusLabel).toBe("Within Standard");
  });

  it("counts feed typed on earlier rows of the same flock", () => {
    const prior = priorListFeed(lookup(), [{ farm: "1", feed_1: "13", feed_1_qty: "30" }]);
    const a = adviseDailyEntry(lookup(), values, undefined, prior);
    // 30 kg already typed above + 75 kg here = 105 kg on the flock.
    expect(text(a)).toContain("New total 105.0 kg");
    expect(a.cap!.cum).toBeCloseTo(105 / BIRDS, 4);
  });

  it("counts one item picked in both slots once against its cap", () => {
    const a = adviseDailyEntry(lookup(), {
      feed_1: "13", feed_1_qty: "40", feed_2: "13", feed_2_qty: "35",
    });
    expect(a.cap!.cum).toBeCloseTo(75 / BIRDS, 4);
  });

  it("says nothing at all without a batch", () => {
    const a = adviseDailyEntry(null, values);
    expect(a.notes).toEqual([]);
    expect(a.cap).toBeNull();
    expect(a.statusLabel).toBe("");
  });
});

describe("feedPlanLines", () => {
  const row = (over: Record<string, string | number> = {}) => ({
    item: 13, name: "Pre-Starter Feed", cap_per_bird_kg: "0.4",
    required_kg: "913.60", sent_kg: "1000.00", fed_kg: "25.00",
    balance_kg: "975.00", remaining_kg: "888.60", excess_kg: "86.40",
    ...over,
  }) as any;

  const one = (over = {}, typed = {}, birds = 2284) =>
    feedPlanLines([row(over)], typed, birds).lines[0];

  it("measures the requirement against the flock, not a stored figure", () => {
    // 0.4 kg/bird cap x 2,284 birds.
    expect(one().required).toBeCloseTo(913.6, 1);
    // Birds booked as lost today do not eat, so it falls with them.
    expect(one({}, {}, 2084).required).toBeCloseTo(833.6, 1);
  });

  it("counts what is being typed, so the balance is the one after this entry", () => {
    const r = one({}, { "13": 40 });
    expect(r.fed).toBeCloseTo(65, 1);
    expect(r.balance).toBeCloseTo(935, 1);
    expect(r.remaining).toBeCloseTo(848.6, 1);
  });

  it("flags feed sent beyond what the phase can use", () => {
    expect(one().flag).toBe("86 extra sent");
    expect(one().warn).toBe(false);
  });

  it("flags feed fed but never received, ahead of anything else", () => {
    const r = one({ sent_kg: "0.00" });
    expect(r.flag).toBe("25 unreceived");
    expect(r.warn).toBe(true);
  });

  it("flags a flock fed past its phase cap", () => {
    const r = one({ fed_kg: "1000.00" });
    expect(r.flag).toBe("86 over cap");
    expect(r.warn).toBe(true);
  });

  it("says nothing when the position is sound", () => {
    expect(one({ sent_kg: "913.60" }).flag).toBe("");
  });

  it("totals every feed, which is what an order is placed against", () => {
    const { total } = feedPlanLines(
      [row(), row({ item: 14, name: "Starter Feed", cap_per_bird_kg: "1.2",
                    sent_kg: "0.00", fed_kg: "0.00" })],
      {}, 1000);
    expect(total.required).toBeCloseTo(400 + 1200, 1);
    expect(total.fed).toBeCloseTo(25, 1);
  });

  it("returns nothing for an empty plan rather than failing", () => {
    const { lines, total } = feedPlanLines([], {}, 1000);
    expect(lines).toEqual([]);
    expect(total.required).toBe(0);
  });
});

describe("typedFeed", () => {
  it("counts both slots", () => {
    expect(typedFeed({ feed_1: "13", feed_1_qty: "40",
                       feed_2: "14", feed_2_qty: "10" }))
      .toEqual({ "13": 40, "14": 10 });
  });

  it("sums the two when both slots carry the same feed", () => {
    // The flock ate the total, not whichever slot was read last.
    expect(typedFeed({ feed_1: "13", feed_1_qty: "40",
                       feed_2: "13", feed_2_qty: "15" }))
      .toEqual({ "13": 55 });
  });

  it("ignores a slot with a feed but no quantity, and the reverse", () => {
    expect(typedFeed({ feed_1: "13", feed_1_qty: "0",
                       feed_2: "", feed_2_qty: "20" })).toEqual({});
  });

  it("is empty when nothing is entered", () => {
    expect(typedFeed({})).toEqual({});
  });
});

describe("feedPlanLines flag placement", () => {
  const row = (over: Record<string, string | number> = {}) => ({
    item: 13, name: "Pre-Starter Feed", cap_per_bird_kg: "0.4",
    required_kg: "400.00", sent_kg: "1000.00", fed_kg: "25.00",
    balance_kg: "975.00", remaining_kg: "375.00", excess_kg: null,
    ...over,
  }) as any;
  const one = (over = {}) => feedPlanLines([row(over)], {}, 1000).lines[0];

  it("puts an unreceived flag against the balance", () => {
    // The marker has to sit on the figure it explains, or the reader has to
    // guess which of five numbers is the problem.
    expect(one({ sent_kg: "0.00" }).flagOn).toBe("balance");
  });

  it("puts an over-cap flag against what is left to feed", () => {
    expect(one({ fed_kg: "500.00", sent_kg: "500.00" }).flagOn).toBe("remaining");
  });

  it("puts an extra-sent flag against what was sent", () => {
    expect(one().flagOn).toBe("sent");
  });

  it("marks nothing when the position is sound", () => {
    expect(one({ sent_kg: "400.00" }).flagOn).toBeNull();
  });
});

describe("negative stock is a blocker, not a warning", () => {
  const lookup = {
    batch: 1, batch_name: "B1", age_days: 5, start_date: "2026-07-18",
    next_date: "2026-07-23", feed_phase: null, std_feed_kg: null,
    std_weight_g: null, std_note: null, bs_curve: [], cum_feed_before_kg: null,
    consumed_by_item: [], consumed_total_kg: null,
    consumed_per_bird_actual_g: null, live_birds: 1000,
  } as any;

  const advise = (qty: string, opening: string) =>
    adviseDailyEntry(lookup, { feed_1: "13", feed_1_qty: qty } as any,
                     { feed_1: opening } as any);

  it("refuses feeding more than the farm holds", () => {
    const a = advise("150", "100");
    expect(a.blockers).toHaveLength(1);
    expect(a.blockers[0]).toContain("short by 50.00 kg");
    // And it is not merely a confirmable warning.
    expect(a.issues.join(" ")).not.toContain("short by");
  });

  it("allows feeding exactly what is there", () => {
    expect(advise("100", "100").blockers).toEqual([]);
  });

  it("weighs both slots together when they carry the same feed", () => {
    // One pile at the farm. Weighed apart, 60 + 60 out of 100 kg looked like
    // two comfortable rows, and DailyEntry.clean threw the save back.
    const a = adviseDailyEntry(lookup, {
      feed_1: "13", feed_1_qty: "60", feed_2: "13", feed_2_qty: "60",
    } as any, { feed_1: "100", feed_2: "100" } as any);
    expect(a.blockers).toHaveLength(1);
    expect(a.blockers[0]).toContain("short by 20.00 kg");
  });

  it("keeps two different feeds on their own balances", () => {
    const a = adviseDailyEntry(lookup, {
      feed_1: "13", feed_1_qty: "80", feed_2: "14", feed_2_qty: "80",
    } as any, { feed_1: "100", feed_2: "100" } as any);
    expect(a.blockers).toEqual([]);
  });

  it("allows feeding less than is there", () => {
    expect(advise("40", "100").blockers).toEqual([]);
  });

  it("has no blockers before a flock is known", () => {
    expect(adviseDailyEntry(null as any, {} as any).blockers).toEqual([]);
  });
});

describe("a weighing gone stale is a blocker too", () => {
  const lookup = (lastWeightDate: string | null) => ({
    batch: 1, batch_name: "B1", age_days: 20, start_date: "2026-07-01",
    next_date: "2026-07-23", feed_phase: null, std_feed_kg: null,
    std_weight_g: null, std_note: null, bs_curve: [], cum_feed_before_kg: null,
    consumed_by_item: [], consumed_total_kg: null,
    consumed_per_bird_actual_g: null, live_birds: 1000,
    last_weight_g: lastWeightDate ? "45.00" : null, last_weight_date: lastWeightDate,
  } as any);

  const advise = (lastWeightDate: string | null, today: string, values: Record<string, string> = {}) =>
    adviseDailyEntry(lookup(lastWeightDate), values, undefined, undefined, today);

  it("refuses to save with no weight entered three days after the last weighing", () => {
    const a = advise("2026-07-18", "2026-07-21");
    expect(a.blockers).toHaveLength(1);
    expect(a.blockers[0]).toContain("2 days");
  });

  it("is not merely a confirmable warning", () => {
    const a = advise("2026-07-18", "2026-07-21");
    expect(a.issues.join(" ")).not.toContain("Body weight");
  });

  it("is resolved the moment today's weight is entered", () => {
    const a = advise("2026-07-18", "2026-07-21", { avg_weight_gms: "620" });
    expect(a.blockers).toEqual([]);
  });

  it("does not block at a two-day gap, only three and beyond", () => {
    expect(advise("2026-07-19", "2026-07-21").blockers).toEqual([]);
  });

  it("does not block a flock that has never been weighed at all", () => {
    expect(advise(null, "2026-07-21").blockers).toEqual([]);
  });

  it("measures against the entry's own date, not whenever it happens to be saved", () => {
    // A supervisor backfilling a missed day is filing an entry dated
    // 2026-07-19 — two days after the last weighing, so no block — even
    // though this is actually being saved much later, on 2026-07-25.
    const a = advise("2026-07-18", "2026-07-19");
    expect(a.blockers).toEqual([]);
  });

  it("still blocks a backfilled day that was itself three days stale", () => {
    // The entry being filed is dated 2026-07-21 — three real days after the
    // last weighing on 2026-07-18 — regardless of when it is actually saved.
    const a = advise("2026-07-18", "2026-07-21");
    expect(a.blockers).toHaveLength(1);
  });
});

describe("lastWeightNote — the line under the weight box", () => {
  const note = (g: string | null, taken: string | null, on?: string) =>
    lastWeightNote({ last_weight_g: g, last_weight_date: taken }, on);

  it("names the weight and the day it was taken", () => {
    const n = note("38.50", "2026-07-19", "2026-07-21");
    expect(n!.text).toContain("38.5");
    expect(n!.text).toContain("Jul");
  });

  it("drops the trailing zeros a decimal field stores", () => {
    expect(note("40.00", "2026-07-22", "2026-07-23")!.text).toContain("40 g");
  });

  it("stays off when the flock has never been weighed", () => {
    expect(note(null, null, "2026-07-23")).toBeNull();
    expect(lastWeightNote(undefined)).toBeNull();
  });

  it("stays off when a server too old to send it answers", () => {
    expect(lastWeightNote({}, "2026-07-23")).toBeNull();
  });

  it("treats a zero weight as never weighed rather than showing 0 g", () => {
    expect(note("0", "2026-07-19", "2026-07-23")).toBeNull();
  });

  // ---- how long since ----------------------------------------------------

  it("counts the days between the weighing and the entry", () => {
    const n = note("40", "2026-07-19", "2026-07-23");
    expect(n!.days).toBe(4);
    expect(n!.text).toContain("4d ago");
  });

  it("reads naturally at nought and one day", () => {
    expect(note("40", "2026-07-23", "2026-07-23")!.text).toContain("today");
    expect(note("40", "2026-07-22", "2026-07-23")!.text).toContain("1d ago");
  });

  it("stays quiet at a day or less, which is the normal rhythm", () => {
    expect(note("40", "2026-07-23", "2026-07-23")!.tone).toBe("info");
    expect(note("40", "2026-07-22", "2026-07-23")!.tone).toBe("info");
  });

  it("turns amber at two days", () => {
    expect(note("40", "2026-07-21", "2026-07-23")!.tone).toBe("warn");
  });

  it("turns red at three days and beyond", () => {
    expect(note("40", "2026-07-20", "2026-07-23")!.tone).toBe("bad");
    expect(note("40", "2026-07-10", "2026-07-23")!.tone).toBe("bad");
  });

  it("crosses a month end without arithmetic trouble", () => {
    const n = note("40", "2026-06-29", "2026-07-02");
    expect(n!.days).toBe(3);
    expect(n!.tone).toBe("bad");
  });

  it("omits the gap, and the colour, without a day to measure against", () => {
    const n = note("40", "2026-07-19", undefined);
    expect(n!.days).toBeNull();
    expect(n!.tone).toBe("info");
    expect(n!.text.split("·")).toHaveLength(2);   // weight and date only
  });
});
