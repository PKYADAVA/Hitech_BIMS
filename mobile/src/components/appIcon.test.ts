// AppIcon reaches the theme, which persists the light/dark choice — native
// storage no test process has. The library ships a mock for exactly this.
jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"));

import { MaterialCommunityIcons } from "@expo/vector-icons";

import { iconFor } from "./AppIcon";
import { RESOURCES } from "@/config/catalog";

/**
 * An icon this set does not have renders as a neutral ring, not as an error —
 * so a typo, or an emoji nobody added to the map, looks like a design choice
 * and can sit there for months. (It did: the Daily Trip shortcut shipped as a
 * hollow circle because "🚗" was never mapped.) These assertions are the only
 * thing that tells the difference.
 */
describe("iconFor", () => {
  it("maps the car to a real glyph rather than the fallback", () => {
    expect(iconFor("🚗")).toBe("car-side");
    expect("car-side" in MaterialCommunityIcons.glyphMap).toBe(true);
  });

  it("passes a valid glyph name straight through", () => {
    expect(iconFor("car-side")).toBe("car-side");
  });

  it("falls back only for something it genuinely cannot resolve", () => {
    expect(iconFor("🫠")).toBe("circle-outline");
  });

  /**
   * The chrome asks for these by name and nothing else asserts them, so a
   * rename in the icon set would turn the Menu tab into a blank ring exactly
   * the way the Daily Trip shortcut did. "☰" is in the list as a counter-
   * example: it is the obvious thing to reach for and it does not resolve,
   * which is how the Menu tab was nearly shipped hollow.
   */
  it("resolves the icons the app chrome asks for", () => {
    for (const name of ["menu", "chevron-down", "chevron-right", "paperclip"]) {
      expect(iconFor(name)).toBe(name);
      expect(name in MaterialCommunityIcons.glyphMap).toBe(true);
    }
    expect(iconFor("☰")).toBe("circle-outline");
  });

  it("resolves every icon the register screens ask for", () => {
    const blank = Object.values(RESOURCES)
      .filter((r) => r.icon !== "circle-outline" && iconFor(r.icon) === "circle-outline")
      .map((r) => `${r.key}: ${r.icon}`);
    expect(blank).toEqual([]);
  });
});
