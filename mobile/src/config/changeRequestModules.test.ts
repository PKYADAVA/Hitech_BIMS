import {
  CHANGE_REQUEST_MODULE,
  REQUEST_EDIT_MODULES,
  editRequestModule,
} from "./changeRequestModules";

/**
 * Which register offers which approval-queue fallback.
 *
 * The two maps are held against the backend by the Django side
 * (user/tests/test_mobile_change_requests.py), which is where staleness gets
 * caught. What is checked here is the rule that reads them: a module can be
 * reachable for a deletion request and still not take an edit one, and that
 * distinction is the whole reason the second set exists.
 */
describe("editRequestModule", () => {
  it("names the module for a register that takes edit requests", () => {
    expect(editRequestModule("sales-invoices")).toBe("sales_invoice");
  });

  it("takes an edit request on Daily Entry, as the web register does", () => {
    // This test used to assert the opposite, on the reasoning that a Daily
    // Entry is a day in a chain of days and a correction replayed on its own
    // would land outside the running figures it was built from. Sound
    // reasoning, but not the web's: daily_entry_list.html draws the same
    // Request modification button as every other register. The judgement is
    // the web's to make and the phone's to mirror, and the phone was
    // withholding a route the ERP offers.
    expect(CHANGE_REQUEST_MODULE["broiler-daily-entries"]).toBe("daily_entry");
    expect(editRequestModule("broiler-daily-entries")).toBe("daily_entry");
  });

  it("refuses a register with no change-request handler at all", () => {
    expect(editRequestModule("broiler-farms")).toBeUndefined();
  });

  it("refuses a resource key that does not exist", () => {
    expect(editRequestModule("not-a-resource")).toBeUndefined();
  });

  it("only ever names a module that can also be reached for deletion", () => {
    // The edit set narrows the module map rather than standing beside it; a
    // member of one and not the other would be unreachable and read as
    // supported.
    const reachable = new Set(Object.values(CHANGE_REQUEST_MODULE));
    for (const module of REQUEST_EDIT_MODULES) {
      expect(reachable.has(module)).toBe(true);
    }
  });

  it("never offers an edit request the deletion map cannot route", () => {
    // The narrowing that matters is direction, not size. This once asserted
    // the edit set was strictly the smaller of the two, which was a count
    // dressed up as a rule: every module the phone can reach turns out to
    // accept a correction, so the sets coincide, and the old assertion
    // failed on a map that had finally caught up with the web.
    const reachable = new Set(Object.values(CHANGE_REQUEST_MODULE));
    const strays = [...REQUEST_EDIT_MODULES].filter((m) => !reachable.has(m));
    expect(strays).toEqual([]);
  });
});
