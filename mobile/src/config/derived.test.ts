import { AUTO_KEYS, applyDerived, forgetTyped } from "./derived";

/**
 * The rule that decides whether a lookup may change a box.
 *
 * This used to be "only if the box is empty", which is where a real bug came
 * from: the stock transfer rate is the price effective on the row's date, and
 * once the first lookup filled the box every later one backed off — so moving
 * a row to a date with a different price left the old figure sitting there,
 * looking entered.
 */
describe("applyDerived", () => {
  it("fills a box nobody has touched", () => {
    const next = applyDerived({ item: "14" }, { rate: "42.00" })!;
    expect(next.rate).toBe("42.00");
  });

  it("refreshes a value it filled in before", () => {
    const first = applyDerived({ item: "14" }, { rate: "42.00" })!;
    const second = applyDerived(first, { rate: "38.00" })!;
    expect(second.rate).toBe("38.00");
  });

  it("leaves a figure the person typed", () => {
    // The whole point: a rate someone entered on purpose is not a guess to
    // be replaced when the date moves.
    const typed = { item: "14", rate: "50" };
    expect(applyDerived(typed, { rate: "42.00" })).toBeNull();
  });

  it("stops touching a value once it is edited by hand", () => {
    const auto = applyDerived({ item: "14" }, { rate: "42.00" })!;
    const edited = { ...auto, rate: "50", [AUTO_KEYS]: forgetTyped(auto, ["rate"]) };
    expect(applyDerived(edited, { rate: "38.00" })).toBeNull();
  });

  it("clears a box it owns when the answer comes back empty", () => {
    // No price effective on this date. Leaving the previous date's figure
    // there would be worse than an empty box, which at least shows itself.
    const auto = applyDerived({ item: "14" }, { rate: "42.00" })!;
    const cleared = applyDerived(auto, { rate: "" })!;
    expect(cleared.rate).toBe("");
  });

  it("fills a box again after clearing it", () => {
    const auto = applyDerived({ item: "14" }, { rate: "42.00" })!;
    const cleared = applyDerived(auto, { rate: "" })!;
    expect(applyDerived(cleared, { rate: "39.00" })!.rate).toBe("39.00");
  });

  it("does not claim a typed value by clearing around it", () => {
    const typed = { item: "14", rate: "50" };
    expect(applyDerived(typed, { rate: "" })).toBeNull();
  });

  it("says nothing changed rather than churning the row", () => {
    expect(applyDerived({ item: "14", rate: "50" }, { rate: "42.00" })).toBeNull();
  });

  it("keeps its bookkeeping out of the payload's way", () => {
    // build() names the fields it sends, so this key only has to stay
    // recognisable — never a field name a document might use.
    const next = applyDerived({ item: "14" }, { rate: "42.00" })!;
    expect(next[AUTO_KEYS]).toBe("rate");
    expect(AUTO_KEYS.startsWith("_")).toBe(true);
  });
});
