/**
 * Grouping order, which is the part that reads wrong when it drifts.
 *
 * A flock should read top to bottom in date order, and the flock worked most
 * recently should be the one in reach. Neither is obvious from looking at a
 * phone screen with three groups on it, so both are pinned here.
 */
import { Row } from "@/api/types";

import { buildGroups, type GroupSpec } from "./grouping";

const spec: GroupSpec = {
  key: (r) => (r.batch ? `batch-${r.batch}` : `farm-${r.farm}`),
  title: (r) => String(r.batch_label ?? r.farm_label ?? "?"),
};

const row = (over: Partial<Row>): Row => ({ id: 1, date: "2026-08-01", ...over }) as Row;

describe("buildGroups", () => {
  it("puts rows sharing a batch together", () => {
    const groups = buildGroups(
      [
        row({ id: 1, batch: 7, date: "2026-08-01" }),
        row({ id: 2, batch: 7, date: "2026-08-02" }),
        row({ id: 3, batch: 9, date: "2026-08-02" }),
      ],
      spec
    );
    expect(groups).toHaveLength(2);
    expect(groups.map((g) => g.rows.length).sort()).toEqual([1, 2]);
  });

  it("falls back to the farm when a row has no batch", () => {
    const groups = buildGroups(
      [row({ id: 1, farm: 3 }), row({ id: 2, farm: 3 }), row({ id: 3, farm: 4 })],
      spec
    );
    expect(groups.map((g) => g.key).sort()).toEqual(["farm-3", "farm-4"]);
  });

  it("does not merge a batch group with a farm group", () => {
    const groups = buildGroups(
      [row({ id: 1, batch: 7, farm: 3 }), row({ id: 2, farm: 3 })],
      spec
    );
    expect(groups).toHaveLength(2);
  });

  it("runs a group's own days oldest first", () => {
    const groups = buildGroups(
      [
        row({ id: 3, batch: 7, date: "2026-08-03" }),
        row({ id: 1, batch: 7, date: "2026-08-01" }),
        row({ id: 2, batch: 7, date: "2026-08-02" }),
      ],
      spec
    );
    expect(groups[0].rows.map((r) => r.date)).toEqual([
      "2026-08-01", "2026-08-02", "2026-08-03",
    ]);
  });

  it("breaks a date tie by id rather than leaving it to chance", () => {
    const groups = buildGroups(
      [
        row({ id: 9, batch: 7, date: "2026-08-01" }),
        row({ id: 4, batch: 7, date: "2026-08-01" }),
      ],
      spec
    );
    expect(groups[0].rows.map((r) => r.id)).toEqual([4, 9]);
  });

  it("puts the most recently worked group first", () => {
    const groups = buildGroups(
      [
        row({ id: 1, batch: 7, date: "2026-07-01" }),
        row({ id: 2, batch: 9, date: "2026-08-05" }),
        row({ id: 3, batch: 8, date: "2026-08-01" }),
      ],
      spec
    );
    expect(groups.map((g) => g.key)).toEqual(["batch-9", "batch-8", "batch-7"]);
  });

  it("ranks a group by its newest day, not its oldest", () => {
    // The long-running flock started first but was worked last; it leads.
    const groups = buildGroups(
      [
        row({ id: 1, batch: 7, date: "2026-01-01" }),
        row({ id: 2, batch: 7, date: "2026-08-09" }),
        row({ id: 3, batch: 9, date: "2026-08-02" }),
      ],
      spec
    );
    expect(groups[0].key).toBe("batch-7");
  });

  it("takes its title from the group's rows", () => {
    const groups = buildGroups(
      [row({ id: 1, batch: 7, batch_label: "FARMDE2-1" })],
      spec
    );
    expect(groups[0].title).toBe("FARMDE2-1");
  });

  it("builds the subtitle from the sorted rows, not the input order", () => {
    const groups = buildGroups(
      [
        row({ id: 2, batch: 7, date: "2026-08-05" }),
        row({ id: 1, batch: 7, date: "2026-08-01" }),
      ],
      { ...spec, subtitle: (rows) => `last ${rows[rows.length - 1].date}` }
    );
    expect(groups[0].subtitle).toBe("last 2026-08-05");
  });

  it("returns nothing for an empty feed", () => {
    expect(buildGroups([], spec)).toEqual([]);
  });

  it("leaves the subtitle unset when the spec has none", () => {
    const groups = buildGroups([row({ id: 1, batch: 7 })], spec);
    expect(groups[0].subtitle).toBeUndefined();
  });
});
