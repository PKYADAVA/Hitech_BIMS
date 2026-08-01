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
  ManageAccess: undefined;
  /** Bespoke Bird Sale form (sale-type toggle, farm-derived batch/farmer). */
  BirdSaleForm: { mode: "create" | "edit"; row?: Row };
  /** Bespoke Bird Sale Receipt form (customer/farmer toggle). */
  BirdSaleReceiptForm: { mode: "create" | "edit"; row?: Row };
  /** Multi-farm Daily Entry — one date, several farms, one save (web grid form). */
  DailyEntryGrid: undefined;
  /** Transaction document form (header + line items) — inventory/purchase/sales. */
  DocumentForm: { resourceKey: string; mode: "create" | "edit"; row?: Row };
};

export type TabParams = {
  Home: undefined;
  Broiler: NavigatorScreenParams<ModuleStackParams>;
  Hatchery: NavigatorScreenParams<ModuleStackParams>;
  SMS: NavigatorScreenParams<ModuleStackParams>;
  Profile: undefined;
};

export type ModuleTab = Extract<keyof TabParams, ModuleKey>;
