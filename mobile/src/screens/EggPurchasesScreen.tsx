import React from "react";

import { Row } from "@/api/types";
import { ResourceList } from "@/components/ResourceList";
import { Screen } from "@/components/ui";
import { pick } from "@/utils/row";

/** Hatchery egg purchases — a cursor-paginated transaction feed. */
export function EggPurchasesScreen() {
  return (
    <Screen>
      <ResourceList
        path="/hatchery/egg-purchases/"
        emptyMessage="No egg purchases yet."
        renderTitle={(r: Row) => pick(r, ["transaction_no", "bill_no", "reference_no"], `Purchase #${r.id}`)}
        renderSubtitle={(r: Row) =>
          [pick(r, ["date", "purchase_date"]), pick(r, ["supplier_name", "supplier"])]
            .filter(Boolean)
            .join("  ·  ")
        }
      />
    </Screen>
  );
}
