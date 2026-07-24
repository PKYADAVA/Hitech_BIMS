import React from "react";

import { Row } from "@/api/types";
import { ResourceList } from "@/components/ResourceList";
import { Screen } from "@/components/ui";
import { pick } from "@/utils/row";

/** Broiler daily entries — a cursor-paginated transaction feed. */
export function DailyEntriesScreen() {
  return (
    <Screen>
      <ResourceList
        path="/broiler/daily-entries/"
        emptyMessage="No daily entries yet."
        renderTitle={(r: Row) => pick(r, ["entry_no", "entry_number"], `Entry #${r.id}`)}
        renderSubtitle={(r: Row) =>
          [pick(r, ["date"]), pick(r, ["batch_name", "batch"])].filter(Boolean).join("  ·  ")
        }
      />
    </Screen>
  );
}
