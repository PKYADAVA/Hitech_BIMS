import {
  EMPTY_STRIP,
  isoDate,
  lastSevenDays,
  lineAmount,
  openingStrip,
  pettyIcon,
  pettyMoney,
  pettyQuery,
  pettyTileStrip,
} from "./pettyExpense";

const TODAY = new Date(2026, 8, 27); // 27 Sep 2026, local

describe("the window the register opens on", () => {
  it("is the last seven days, today included", () => {
    expect(lastSevenDays(TODAY)).toEqual({ from: "2026-09-21", to: "2026-09-27" });
  });

  it("is what the strip starts as, and nothing else is set", () => {
    expect(openingStrip(TODAY)).toEqual({
      ...EMPTY_STRIP,
      from: "2026-09-21",
      to: "2026-09-27",
    });
  });

  it("stays on the local day either side of UTC", () => {
    // Late evening in +05:30 is already tomorrow in UTC; toISOString() would
    // have dated the register's window a day forward.
    expect(isoDate(new Date(2026, 8, 27, 23, 45))).toBe("2026-09-27");
  });
});

describe("what pressing a figure does to the strip", () => {
  const open = openingStrip(TODAY);

  it("takes Today to one day of posted rows, as the ERP does", () => {
    expect(pettyTileStrip(open, "", "today", TODAY)).toEqual({
      ...EMPTY_STRIP,
      from: "2026-09-27",
      to: "2026-09-27",
      status: "Posted",
    });
  });

  it("takes This Month to the first of the month, not thirty days back", () => {
    expect(pettyTileStrip(open, "", "month", TODAY)).toEqual({
      ...EMPTY_STRIP,
      from: "2026-09-01",
      to: "2026-09-27",
      status: "Posted",
    });
  });

  it("leaves Drafts without dates, because a draft can be any age", () => {
    expect(pettyTileStrip(open, "", "drafts", TODAY)).toEqual({
      ...EMPTY_STRIP,
      status: "Draft",
    });
  });

  it("takes a cash box to its own rows, whatever their status", () => {
    expect(pettyTileStrip(open, "", "box:2", TODAY)).toEqual({
      ...EMPTY_STRIP,
      paid_from: "2",
    });
  });

  it("puts the register back to its opening window when let go", () => {
    const pressed = pettyTileStrip(open, "", "today", TODAY);
    expect(pettyTileStrip(pressed, "today", "today", TODAY)).toEqual(open);
  });

  it("keeps the answers a figure does not speak for", () => {
    // Branch and sub category are not what a figure is counting, so pressing
    // one must not quietly widen the list back to every branch.
    const narrowed = { ...open, branch: "3", account: "610003" };
    expect(pettyTileStrip(narrowed, "", "drafts", TODAY)).toEqual({
      ...EMPTY_STRIP,
      branch: "3",
      account: "610003",
      status: "Draft",
    });
  });
});

describe("the strip as a query", () => {
  it("sends only what was answered", () => {
    expect(pettyQuery({ ...EMPTY_STRIP, from: "2026-09-01", status: "Draft" })).toEqual({
      from: "2026-09-01",
      status: "Draft",
    });
  });

  it("carries the search term under the name the register uses", () => {
    expect(pettyQuery(EMPTY_STRIP, "  tea  ")).toEqual({ q: "tea" });
  });

  it("treats a box of spaces as unanswered", () => {
    expect(pettyQuery({ ...EMPTY_STRIP, paid_to: "   " }, "   ")).toEqual({});
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
