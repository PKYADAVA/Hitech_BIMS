import { ageAt } from "./flockAge";

/**
 * The web form recomputes Age from the entry date on every date change
 * (`recomputeAge` in broiler/templates/medicine_entry_form.html). These pin
 * the phone to the same arithmetic — a record back-dated on the phone has to
 * carry the age the flock actually was, or it disagrees with the register.
 */
describe("age at the entry date", () => {
  it("counts placement day as age 0", () => {
    expect(ageAt("2026-07-21", "2026-07-21")).toBe("0");
  });

  it("follows the entry date, not today", () => {
    expect(ageAt("2026-07-21", "2026-08-04")).toBe("14");
    expect(ageAt("2026-07-21", "2026-08-01")).toBe("11");
  });

  it("clamps a date before placement to 0 rather than going negative", () => {
    expect(ageAt("2026-07-21", "2026-07-01")).toBe("0");
  });

  it("is blank until both the batch and the date are known", () => {
    expect(ageAt("", "2026-08-04")).toBe("");
    expect(ageAt("2026-07-21", "")).toBe("");
  });
});
