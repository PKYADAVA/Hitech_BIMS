import { MaterialCommunityIcons } from "@expo/vector-icons";

import { extraRowActions, RowActionNavigate } from "./rowActions";
import { Row } from "@/api/types";

/**
 * The register's extra actions are the ones nothing else can reach: a trip is
 * only ended from its row, and a lifting's photographs are only added from
 * theirs. Both are one string away from being silently absent — a resource key
 * that no longer matches returns an empty list and the button simply is not
 * there, which reads as "this record has no such action".
 */

const nav: RowActionNavigate = () => {};
const all = { add: true, edit: true, delete: true };
const readOnly = { add: false, edit: false, delete: false };

const sale = { id: 7, sale_no: "BS-0007" } as unknown as Row;

describe("extraRowActions", () => {
  it("offers Upload on a bird sale row", () => {
    const actions = extraRowActions("broiler-bird-sales", sale, nav, all);
    expect(actions.map((a) => a.key)).toEqual(["upload"]);
    expect(actions[0].label).toBe("Upload");
  });

  it("withholds Upload from someone who may only look", () => {
    expect(extraRowActions("broiler-bird-sales", sale, nav, readOnly)).toEqual([]);
  });

  it("offers Upload to someone who may add but not edit", () => {
    const addOnly = { add: true, edit: false, delete: false };
    const actions = extraRowActions("broiler-bird-sales", sale, nav, addOnly);
    expect(actions.map((a) => a.key)).toEqual(["upload"]);
  });

  it("opens the photo screen with the sale it was pressed on", () => {
    const seen: { screen: string; row: Row }[] = [];
    const spy: RowActionNavigate = (screen, params) =>
      seen.push({ screen, row: params.row });
    extraRowActions("broiler-bird-sales", sale, spy, all)[0].onPress();
    expect(seen).toEqual([{ screen: "BirdSalePhotos", row: sale }]);
  });

  it("leaves a resource with no extra actions alone", () => {
    expect(extraRowActions("broiler-daily-entry", sale, nav, all)).toEqual([]);
  });

  it("asks only for icons the set actually has", () => {
    const keys = ["hr-supervisor-trips", "broiler-bird-sales",
                  "broiler-farm-location-capture"];
    const missing = keys
      .flatMap((k) => extraRowActions(k, sale, nav, all,
                                      { clearLocation: () => {} }))
      .filter((a) => a.icon && !(a.icon in MaterialCommunityIcons.glyphMap))
      .map((a) => `${a.key}: ${a.icon}`);
    expect(missing).toEqual([]);
  });
});
