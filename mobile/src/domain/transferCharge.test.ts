import {
  EMPTY_STRIP,
  isoDate,
  lastThirtyDays,
  lineIsBlank,
  openingStrip,
  chargeIcon,
  transferChargeQuery,
  transferChargeTileStrip,
} from "./transferCharge";

const TODAY = new Date(2026, 8, 27); // 27 Sep 2026, local

describe("the window the register opens on", () => {
  it("is the last thirty days, today included", () => {
    expect(lastThirtyDays(TODAY)).toEqual({ from: "2026-08-29", to: "2026-09-27" });
  });

  it("is what the strip starts as, and nothing else is set", () => {
    expect(openingStrip(TODAY)).toEqual({
      ...EMPTY_STRIP,
      from: "2026-08-29",
      to: "2026-09-27",
    });
  });

  it("stays on the local day either side of UTC", () => {
    expect(isoDate(new Date(2026, 8, 27, 23, 45))).toBe("2026-09-27");
  });
});

describe("what pressing a figure does to the strip", () => {
  const open = openingStrip(TODAY);

  it("takes This Month to the first of the month, not thirty days back", () => {
    expect(transferChargeTileStrip(open, "", "month", TODAY)).toEqual({
      ...EMPTY_STRIP,
      from: "2026-09-01",
      to: "2026-09-27",
      status: "Posted",
    });
  });

  it("leaves Drafts without dates, because a draft can be any age", () => {
    expect(transferChargeTileStrip(open, "", "drafts", TODAY)).toEqual({
      ...EMPTY_STRIP,
      status: "Draft",
    });
  });

  it("leaves Pending Approval without dates, for the same reason", () => {
    expect(transferChargeTileStrip(open, "", "pending", TODAY)).toEqual({
      ...EMPTY_STRIP,
      status: "Pending Approval",
    });
  });

  it("pressing the same figure again puts the register back to its opening window", () => {
    expect(transferChargeTileStrip(open, "month", "month", TODAY)).toEqual(open);
  });
});

describe("the strip as a query", () => {
  it("leaves blanks out", () => {
    expect(transferChargeQuery(EMPTY_STRIP)).toEqual({});
  });

  it("sends every filled field under the register's own param names", () => {
    const strip = {
      ...EMPTY_STRIP,
      from: "2026-09-01",
      to: "2026-09-27",
      status: "Draft",
      chargeType: "3",
      chargeScope: "Common",
      farm: "7",
      branch: "2",
      dcNo: "DC-100",
      vehicle: "UP32",
    };
    expect(transferChargeQuery(strip)).toEqual({
      from_date: "2026-09-01",
      to_date: "2026-09-27",
      status: "Draft",
      charge_type: "3",
      charge_scope: "Common",
      farm: "7",
      branch: "2",
      dc_no: "DC-100",
      vehicle: "UP32",
    });
  });

  it("a typed search overrides the DC No. filter", () => {
    expect(transferChargeQuery({ ...EMPTY_STRIP, dcNo: "DC-1" }, "DC-2")).toEqual({
      dc_no: "DC-2",
    });
  });
});

describe("reading a charge type into an icon", () => {
  it("knows the common fixed vocabulary", () => {
    expect(chargeIcon("Transport")).toBe("truck");
    expect(chargeIcon("Loading")).toBe("package-variant");
    expect(chargeIcon("Unloading")).toBe("dolly");
    expect(chargeIcon("Toll")).toBe("road-variant");
    expect(chargeIcon("Weighment")).toBe("scale-balance");
  });

  it("falls back to a receipt for anything unrecognised", () => {
    expect(chargeIcon("Miscellaneous")).toBe("receipt");
    expect(chargeIcon(undefined)).toBe("receipt");
  });
});

describe("a line nobody has filled in yet", () => {
  it("is blank with neither a charge type nor an amount", () => {
    expect(lineIsBlank({ charge_type: "", total_amount: "" })).toBe(true);
  });

  it("is not blank once either is set", () => {
    expect(lineIsBlank({ charge_type: "3", total_amount: "" })).toBe(false);
    expect(lineIsBlank({ charge_type: "", total_amount: "500" })).toBe(false);
  });
});
