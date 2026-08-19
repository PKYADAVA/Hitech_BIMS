import { NavigatorScreenParams } from "@react-navigation/native";

import { Row } from "@/api/types";
import { ModuleKey } from "@/config/catalog";

/** Screens inside a single module's stack (Broiler / Hatchery share this shape). */
export type ModuleStackParams = {
  Hub: undefined;
  List: { resourceKey: string };
  Detail: { resourceKey: string; row: Row };
  Form: {
    resourceKey: string;
    mode: "create" | "edit";
    row?: Row;
    /** Values merged into the payload (e.g. a parent FK for line items). */
    preset?: Record<string, string>;
    /** Return to the previous screen after save/delete instead of the List. */
    onDoneGoBack?: boolean;
  };
  SmsSend: { row: Row };
  Report: { title: string; path: string };
  /** The same report's full web page, opened in-app — see ReportWebViewScreen. */
  ReportWebView: { title: string; webReportName: string };
  ManageAccess: undefined;
  /** Bespoke Bird Sale form (sale-type toggle, farm-derived batch/farmer). */
  BirdSaleForm: { mode: "create" | "edit"; row?: Row };
  /** Add photo evidence to a lifting that is already filed — adds only. */
  BirdSalePhotos: { row: Row };
  /** Bespoke Bird Receipt form (customer/farmer toggle). */
  BirdSaleReceiptForm: { mode: "create" | "edit"; row?: Row };
  /**
   * Daily Entry. Without params it is the multi-farm round — several farms,
   * one save (web grid form). With `row` it edits that one saved entry, on the
   * same layout so a correction is judged against the same standards the
   * original was.
   */
  DailyEntryGrid: { row?: Row } | undefined;
  MedicineEntryForm: undefined;
  /** Batch Creation. `row` corrects a saved batch; the farm is fixed then. */
  BatchForm: { row?: Row } | undefined;
  FarmCaptureForm: { row?: Row } | undefined;
  /** Fill only what a capture is still missing — the register's "+". */
  FarmCaptureFill: { row: Row };
  /** `row` reopens a saved request — a draft stays editable, anything past
   *  it (pending/approved/rejected) opens read-only with its review note. */
  FarmerFarmSetupRequestForm: { row?: Row } | undefined;
  /** `ending` opens the trip at the closing evidence it still needs. */
  SupervisorTripForm: { row?: Row; ending?: boolean } | undefined;
  /** `row` corrects a saved egg purchase, loaded fresh (its list row is only
   *  a summary — item_names, not the full item rows this form edits). */
  EggPurchaseForm: { row?: Row } | undefined;
  /** `row` corrects a saved general purchase, loaded fresh — same reason as
   *  EggPurchaseForm, plus the destination toggle and TDS/bag fields the
   *  list's summary row doesn't carry. */
  GeneralPurchaseForm: { row?: Row } | undefined;
  /** Transaction document form (header + line items) — inventory/purchase/sales. */
  DocumentForm: { resourceKey: string; mode: "create" | "edit"; row?: Row };
};

export type TabParams = {
  Home: undefined;
  Broiler: NavigatorScreenParams<ModuleStackParams>;
  Hatchery: NavigatorScreenParams<ModuleStackParams>;
  Inventory: NavigatorScreenParams<ModuleStackParams>;
  /**
   * Opens the side navigation rather than showing a screen — the tab press is
   * intercepted, so nothing is ever rendered here. It is a tab because that is
   * where a thumb already is, which is what let the header hamburger go.
   */
  Menu: undefined;
};

export type ModuleTab = Extract<keyof TabParams, ModuleKey>;
