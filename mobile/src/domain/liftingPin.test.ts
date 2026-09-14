import { needsPin } from "./liftingPin";

describe("needsPin", () => {
  it("says yes when a lifting has no coordinates at all", () => {
    // The desk-raised sale: a slip carried back, typed up, never on a map.
    expect(needsPin({})).toBe(true);
    expect(needsPin({ lift_latitude: null, lift_longitude: null })).toBe(true);
    expect(needsPin({ lift_latitude: "", lift_longitude: "" })).toBe(true);
    expect(needsPin({ lift_latitude: "   ", lift_longitude: "  " })).toBe(true);
  });

  it("says no when the lifting is already on the map", () => {
    // The rule that protects the record. Photographs are often added later and
    // somewhere else; re-stamping would move the lifting to the office.
    expect(needsPin({ lift_latitude: "26.85", lift_longitude: "80.95" })).toBe(false);
  });

  it("accepts coordinates however the row happens to carry them", () => {
    // The API sends strings; a local draft may hold numbers.
    expect(needsPin({ lift_latitude: 26.85, lift_longitude: 80.95 })).toBe(false);
  });

  it("treats a zero coordinate as a real one", () => {
    // 0° is a place. Reading it as "missing" would re-stamp a record that is
    // already true, which is the one thing this must not do.
    expect(needsPin({ lift_latitude: 0, lift_longitude: 0 })).toBe(false);
    expect(needsPin({ lift_latitude: "0", lift_longitude: "0" })).toBe(false);
  });

  it("says yes when only one of the pair is there", () => {
    // Half a pin cannot be put on a map, so it counts as missing.
    expect(needsPin({ lift_latitude: "26.85" })).toBe(true);
    expect(needsPin({ lift_longitude: "80.95" })).toBe(true);
    expect(needsPin({ lift_latitude: "26.85", lift_longitude: "" })).toBe(true);
  });
});
