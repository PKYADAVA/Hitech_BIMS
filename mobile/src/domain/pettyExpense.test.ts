import {
  isoDate,
  lineAmount,
  pettyIcon,
  pettyMoney,
  pettyRangeFilters,
  pettyTileFilters,
} from "./pettyExpense";

const TODAY = new Date(2026, 8, 27); // 27 Sep 2026, local

describe("what a pressed figure asks for", () => {
  it("takes Today to one day", () => {
    expect(pettyTileFilters("today", TODAY)).toEqual({
      from: "2026-09-27",
      to: "2026-09-27",
    });
  });

  it("takes This Month to the first of the month, not thirty days back", () => {
    expect(pettyTileFilters("month", TODAY)).toEqual({
      from: "2026-09-01",
      to: "2026-09-27",
    });
  });

  it("leaves Drafts without dates, because a draft can be any age", () => {
    // A figure counting every unposted expense must not narrow the list to
    // this month, or it shows fewer rows than the number above it.
    expect(pettyTileFilters("drafts", TODAY)).toEqual({ status: "Draft" });
  });

  it("takes a cash box to its own rows", () => {
    expect(pettyTileFilters("box:2", TODAY)).toEqual({ paid_from: "2" });
  });

  it("asks for nothing when no figure is pressed", () => {
    expect(pettyTileFilters("", TODAY)).toEqual({});
  });
});

describe("the filter strip's window", () => {
  it("counts the last seven days inclusive", () => {
    expect(pettyRangeFilters("week", TODAY)).toEqual({
      from: "2026-09-21",
      to: "2026-09-27",
    });
  });

  it("opens the month at its first day", () => {
    expect(pettyRangeFilters("month", TODAY)).toEqual({
      from: "2026-09-01",
      to: "2026-09-27",
    });
  });

  it("bounds nothing when the range is All", () => {
    expect(pettyRangeFilters("all", TODAY)).toEqual({});
  });

  it("stays on the local day either side of UTC", () => {
    // Late evening in +05:30 is already tomorrow in UTC; toISOString() would
    // have dated the register's window a day forward.
    expect(isoDate(new Date(2026, 8, 27, 23, 45))).toBe("2026-09-27");
  });
});

describe("the icon a spend wears", () => {
  it("reads what it was for, not which code it hit", () => {
    expect(pettyIcon("Farm Expenses", "Diesel", "20 litres")).toBe("fuel");
    expect(pettyIcon("Administrative Expenses", "Printing & Stationery")).toBe(
      "file-document-outline"
    );
    expect(pettyIcon("Farm Expenses", "Vaccination")).toBe("pill");
    expect(pettyIcon("Labour charges")).toBe("account-group");
  });

  it("falls back to a receipt rather than guessing", () => {
    expect(pettyIcon("", undefined)).toBe("receipt");
    expect(pettyIcon("Something nobody has named before")).toBe("receipt");
  });
});

describe("the figures on a line", () => {
  it("multiplies qty by rate", () => {
    expect(lineAmount({ quantity: "20", rate: "92" })).toBe(1840);
  });

  it("treats a half-typed line as zero rather than NaN", () => {
    expect(lineAmount({ quantity: "", rate: "92" })).toBe(0);
    expect(lineAmount({ quantity: "2", rate: undefined })).toBe(0);
  });

  it("writes rupees the way the register does", () => {
    expect(pettyMoney(1840)).toBe("₹ 1,840.00");
    expect(pettyMoney(null)).toBe("₹ 0.00");
  });
});
