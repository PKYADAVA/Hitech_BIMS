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

  it("refuses a register that only takes deletion requests", () => {
    // Daily Entry is a day in a chain of days: a correction replayed on its
    // own would land outside the running figures it was built from, so the
    // web offers deletion and nothing else.
    expect(CHANGE_REQUEST_MODULE["broiler-daily-entries"]).toBe("daily_entry");
    expect(REQUEST_EDIT_MODULES.has("daily_entry")).toBe(false);
    expect(editRequestModule("broiler-daily-entries")).toBeUndefined();
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

  it("offers strictly fewer edit requests than deletion requests", () => {
    // Not an arbitrary count — it records that the two are deliberately
    // different sets. If they ever coincide, the narrowing has been lost.
    expect(REQUEST_EDIT_MODULES.size)
      .toBeLessThan(Object.keys(CHANGE_REQUEST_MODULE).length);
  });
});
