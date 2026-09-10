import { RESOURCES } from "./catalog";

/**
 * What a Stock Transfer row says on the list, and over what span.
 *
 * The card subtitle is one line and clipped. The DC number was last on it,
 * behind an item label long enough to fill the card on its own ("ITM-0001 -
 * Pre-Starter Feed"), so the number a delivery is actually looked up by never
 * reached the screen. Order is the fix, which makes it a property worth
 * pinning: date and DC are short and fixed-width, the item label is the part
 * that can be sacrificed to the clip.
 */
const config = RESOURCES["inventory-stock-transfers"];

const row = {
  id: 36,
  trnum: "ST-2627-0009",
  date: "2026-07-09",
  dc_no: "DC-LFS-SEED",
  item_label: "ITM-0001 - Pre-Starter Feed",
  quantity: "1000.00",
};

describe("the Stock Transfer card", () => {
  it("shows the DC number", () => {
    expect(config.card(row).subtitle).toContain("DC-LFS-SEED");
  });

  it("says what the number is, rather than leaving it among other digits", () => {
    // Real values here are often bare digits — "2345" — which on a card
    // beside a quantity reads as anything but a delivery challan.
    expect(config.card({ ...row, dc_no: "2345" }).subtitle).toContain("DC 2345");
  });

  it("puts the DC ahead of the item label, which is what gets clipped", () => {
    const subtitle = config.card(row).subtitle!;
    expect(subtitle.indexOf("DC-LFS-SEED")).toBeLessThan(
      subtitle.indexOf("Pre-Starter Feed"));
  });

  it("leads with the date", () => {
    expect(config.card(row).subtitle!.startsWith("09 Jul 2026")).toBe(true);
  });

  it("leaves no dangling label when there is no DC number", () => {
    for (const missing of ["", null, undefined]) {
      const subtitle = config.card({ ...row, dc_no: missing }).subtitle!;
      expect(subtitle).not.toContain("DC");
      expect(subtitle).not.toMatch(/·\s*·/);
    }
  });

  it("still leads with the transfer number as the title", () => {
    expect(config.card(row).title).toBe("ST-2627-0009");
  });

  it("still shows the quantity", () => {
    expect(config.card(row).trailing).toEqual({ value: "1,000", caption: "qty" });
  });
});

describe("the Stock Transfer date range", () => {
  it("is looked up by date, which is what gives it the From/To and its default", () => {
    // One flag drives both: the range controls above the search, and the
    // seven-day window the screen opens on.
    expect(config.dateField).toBe("date");
  });

  it("names a field the rows actually carry", () => {
    // A dateField naming an absent field filters every row out, and the list
    // reads as an empty register rather than a bad filter.
    expect(row).toHaveProperty(config.dateField!);
  });

  it("can still be searched by the DC number", () => {
    expect(config.searchKeys).toContain("dc_no");
  });
});
