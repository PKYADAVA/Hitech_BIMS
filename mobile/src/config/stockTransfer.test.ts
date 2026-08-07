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

/**
 * A row as the screen actually holds one.
 *
 * Deliberately carries no date: this form keeps one Date in its header, and an
 * earlier version of this test put it on the row instead. That fixture passed
 * against a `derive` that read `row.date`, which on the real screen is always
 * undefined — so the stock was never fetched and the box kept its placeholder,
 * with a green test beside it.
 */
const ROW = { item: "14", from_type: "warehouse", from_id: "1" };
const HEADER = { date: "2026-08-01" };

beforeEach(() => {
  jest.clearAllMocks();
  item.mockResolvedValue({ unit: "Bag", rate: "42.00", price_missing: false, message: "" });
  stock.mockResolvedValue("1122.39");
});

describe("stock transfer row", () => {
  it("fills the unit and the stock at the source", async () => {
    const out = await doc.derive!.run(ROW, HEADER);
    expect(out.uom_label).toBe("Bag");
    expect(out.stock_label).toBe("1122.39");
  });

  it("asks the source for its own kind of location", async () => {
    // A transfer can start at a farm as well as a warehouse. Assuming a
    // warehouse would read the balance of whichever warehouse shares that id.
    await doc.derive!.run({ ...ROW, from_type: "farm", from_id: "1" }, HEADER);
    expect(stock).toHaveBeenCalledWith("farm", "1", "14", "2026-08-01");
  });

  it("re-runs when the item or the source moves", () => {
    expect(doc.derive!.on).toEqual(
      expect.arrayContaining(["item", "from_type", "from_id"]));
  });

  it("takes the date from the header, where this form keeps it", async () => {
    // The row has none. Reading row.date meant the balance was never asked
    // for at all, and the box sat on "auto" however the row was filled in.
    await doc.derive!.run(ROW, HEADER);
    expect(stock).toHaveBeenCalledWith("warehouse", "1", "14", "2026-08-01");
  });

  it("waits for a date rather than asking for a balance without one", async () => {
    const out = await doc.derive!.run(ROW, {});
    expect(out.stock_label).toBeUndefined();
    expect(stock).not.toHaveBeenCalled();
  });

  it("suggests the price master rate, and leaves a typed one alone", async () => {
    expect((await doc.derive!.run(ROW, HEADER)).rate).toBe("42.00");
    const typed = await doc.derive!.run({ ...ROW, rate: "50" }, HEADER);
    expect(typed.rate).toBeUndefined();
  });

  it("says nothing rather than failing when a lookup is down", async () => {
    // Advisory: a missing price or an unreachable balance must not stop
    // someone recording a movement that has already happened.
    item.mockRejectedValue(new Error("offline"));
    stock.mockRejectedValue(new Error("offline"));
    await expect(doc.derive!.run(ROW, HEADER)).resolves.toEqual({});
  });

  it("does nothing at all until an item is chosen", async () => {
    expect(await doc.derive!.run({ ...ROW, item: "" }, HEADER)).toEqual({});
    expect(stock).not.toHaveBeenCalled();
  });

  it("holds off on the stock until the source is known", async () => {
    const out = await doc.derive!.run({ item: "14" }, HEADER);
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
