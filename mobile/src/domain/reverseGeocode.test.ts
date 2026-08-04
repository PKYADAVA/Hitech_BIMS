import { placeFromReply } from "./reverseGeocode";

/**
 * The key precedence is the whole risk here: a wrong pick is not a blank
 * field, it is a plausible-looking wrong one. These pin the same order the
 * ERP's window.reverseGeocode uses, so a capture reads the same on both.
 */
describe("a Nominatim reply as a Place", () => {
  it("takes state_district ahead of county for the district", () => {
    const place = placeFromReply({
      display_name: "Lacchipur, Gorakhpur, Uttar Pradesh",
      address: { state: "Uttar Pradesh", state_district: "Gorakhpur", county: "Sadar" },
    });
    expect(place?.district).toBe("Gorakhpur");
    expect(place?.state).toBe("Uttar Pradesh");
  });

  it("falls back through county and district when state_district is absent", () => {
    expect(placeFromReply({ display_name: "x", address: { county: "Sadar" } })?.district)
      .toBe("Sadar");
    expect(placeFromReply({ display_name: "x", address: { district: "Sadar" } })?.district)
      .toBe("Sadar");
  });

  it("takes the most local name available for the area", () => {
    const rural = placeFromReply({
      display_name: "x", address: { village: "Lacchipur", city: "Gorakhpur" },
    });
    expect(rural?.area).toBe("Lacchipur");
    const urban = placeFromReply({ display_name: "x", address: { city: "Gorakhpur" } });
    expect(urban?.area).toBe("Gorakhpur");
  });

  it("is null when there is no address to offer", () => {
    expect(placeFromReply(null)).toBeNull();
    expect(placeFromReply({})).toBeNull();
    expect(placeFromReply({ address: { state: "Uttar Pradesh" } })).toBeNull();
  });

  it("leaves a part blank rather than guessing when no key answers", () => {
    const place = placeFromReply({ display_name: "Somewhere", address: {} });
    expect(place).toEqual({ display: "Somewhere", state: "", district: "", area: "" });
  });
});
