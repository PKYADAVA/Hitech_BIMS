/**
 * What the Stock Transfer row fills in for itself.
 *
 * The form declared a UOM box and an Available Stock box and never filled
 * either: both sat on their "auto" placeholder however the row was completed,
 * so the one figure that decides whether a transfer can be made — what is
 * actually at the source — was never on screen. Medicine Transfer has had this
 * since it was written; Stock Transfer simply never got it.
 */
jest.mock("@/api/lookups", () => ({
  stockTransferItem: jest.fn(),
  stockTransferStock: jest.fn(),
  farmBatches: jest.fn(),
}));

import { stockTransferItem, stockTransferStock } from "@/api/lookups";
import { DOCUMENTS } from "@/config/documents";

const doc = DOCUMENTS["inventory-stock-transfers"];
const item = stockTransferItem as jest.Mock;
const stock = stockTransferStock as jest.Mock;

const ROW = {
  item: "14", date: "2026-08-01", from_type: "warehouse", from_id: "1",
};

beforeEach(() => {
  jest.clearAllMocks();
  item.mockResolvedValue({ unit: "Bag", rate: "42.00", price_missing: false, message: "" });
  stock.mockResolvedValue("1122.39");
});

describe("stock transfer row", () => {
  it("fills the unit and the stock at the source", async () => {
    const out = await doc.derive!.run(ROW, {});
    expect(out.uom_label).toBe("Bag");
    expect(out.stock_label).toBe("1122.39");
  });

  it("asks the source for its own kind of location", async () => {
    // A transfer can start at a farm as well as a warehouse. Assuming a
    // warehouse would read the balance of whichever warehouse shares that id.
    await doc.derive!.run({ ...ROW, from_type: "farm", from_id: "1" }, {});
    expect(stock).toHaveBeenCalledWith("farm", "1", "14", "2026-08-01");
  });

  it("re-runs when the item, the source or the date moves", () => {
    expect(doc.derive!.on).toEqual(
      expect.arrayContaining(["item", "from_type", "from_id", "date"]));
  });

  it("suggests the price master rate, and leaves a typed one alone", async () => {
    expect((await doc.derive!.run(ROW, {})).rate).toBe("42.00");
    const typed = await doc.derive!.run({ ...ROW, rate: "50" }, {});
    expect(typed.rate).toBeUndefined();
  });

  it("says nothing rather than failing when a lookup is down", async () => {
    // Advisory: a missing price or an unreachable balance must not stop
    // someone recording a movement that has already happened.
    item.mockRejectedValue(new Error("offline"));
    stock.mockRejectedValue(new Error("offline"));
    await expect(doc.derive!.run(ROW, {})).resolves.toEqual({});
  });

  it("does nothing at all until an item is chosen", async () => {
    expect(await doc.derive!.run({ ...ROW, item: "" }, {})).toEqual({});
    expect(stock).not.toHaveBeenCalled();
  });

  it("holds off on the stock until the source is known", async () => {
    const out = await doc.derive!.run({ item: "14", date: "2026-08-01" }, {});
    expect(out.uom_label).toBe("Bag");
    expect(out.stock_label).toBeUndefined();
    expect(stock).not.toHaveBeenCalled();
  });
});

describe("the batch box on a farm location", () => {
  it("asks for one farm's flocks, not the whole batch master", async () => {
    // It used to load the batch master, so a transfer to one farm listed every
    // other farm's batches beside its own — and picking one attached the
    // movement to a flock somewhere else entirely.
    const { farmBatches } = require("@/api/lookups");
    const fs = require("fs");
    const src = fs.readFileSync(
      require("path").join(__dirname, "..", "screens", "DocumentFormScreen.tsx"),
      "utf8");
    expect(src).toContain("farmBatches(farmId)");
    expect(src).not.toContain("optionsPath: BATCH_OPTIONS_PATH");
    expect(typeof farmBatches).toBe("function");
  });
});
