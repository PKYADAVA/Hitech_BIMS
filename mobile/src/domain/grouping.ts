/**
 * Folding a flat record feed into groups, for lists where one row is a day of
 * a longer thing — a flock's daily entries rather than separate events.
 *
 * The ordering is the part worth stating, because it is the part that reads
 * wrong when it drifts: groups come back with the most recently worked one
 * first, and each group's own rows run oldest to newest so a flock reads top
 * to bottom. That is what the web list does, and the two should agree.
 */
import { Row } from "@/api/types";

export interface GroupSpec {
  key: (row: Row) => string;
  title: (row: Row) => string;
  subtitle?: (rows: Row[]) => string;
}

export interface GroupItem {
  key: string;
  title: string;
  subtitle?: string;
  rows: Row[];
}

/** Ties broken by id so equal dates keep a stable, insertion-like order. */
const byDateThenId = (a: Row, b: Row): number =>
  a.date === b.date
    ? Number(a.id) - Number(b.id)
    : String(a.date) < String(b.date)
      ? -1
      : 1;

export function buildGroups(rows: Row[], spec: GroupSpec): GroupItem[] {
  const byKey = new Map<string, GroupItem>();
  for (const row of rows) {
    const key = spec.key(row);
    // The title comes from the first row seen for a key — every row in a group
    // describes the same flock, so any of them answers.
    if (!byKey.has(key)) byKey.set(key, { key, title: spec.title(row), rows: [] });
    byKey.get(key)!.rows.push(row);
  }

  const groups = [...byKey.values()];
  for (const group of groups) {
    group.rows.sort(byDateThenId);
    group.subtitle = spec.subtitle ? spec.subtitle(group.rows) : undefined;
  }

  // Newest last-entry first: the flock worked most recently is the one being
  // looked for, and a flock finished months ago sinks.
  groups.sort((a, b) => {
    const al = a.rows[a.rows.length - 1];
    const bl = b.rows[b.rows.length - 1];
    return al.date === bl.date
      ? Number(bl.id) - Number(al.id)
      : String(al.date) < String(bl.date)
        ? 1
        : -1;
  });
  return groups;
}
