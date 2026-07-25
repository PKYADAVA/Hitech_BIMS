import { NavigatorScreenParams } from "@react-navigation/native";

import { Row } from "@/api/types";
import { ModuleKey } from "@/config/catalog";

/** Screens inside a single module's stack (Broiler / Hatchery share this shape). */
export type ModuleStackParams = {
  Hub: undefined;
  List: { resourceKey: string };
  Detail: { resourceKey: string; row: Row };
  Form: { resourceKey: string; mode: "create" | "edit"; row?: Row };
  SmsSend: { row: Row };
};

export type TabParams = {
  Home: undefined;
  Broiler: NavigatorScreenParams<ModuleStackParams>;
  Hatchery: NavigatorScreenParams<ModuleStackParams>;
  SMS: NavigatorScreenParams<ModuleStackParams>;
  Profile: undefined;
};

export type ModuleTab = Extract<keyof TabParams, ModuleKey>;
