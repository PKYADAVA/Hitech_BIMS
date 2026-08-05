/**
 * Design tokens for a modern, business-oriented BIMS.
 *
 * A deep navy-indigo brand carries the chrome — headers, primary buttons,
 * full-bleed auth screens — and the per-module accents supply the life. Both
 * come from the ERP dashboard reference, so a module reads the same colour on
 * the phone as it does there. Everything non-color
 * (spacing, radius, type scale, elevation) is theme-independent and lives here;
 * colors come in a light and a dark palette with identical keys so any screen
 * can switch by reading the active one from `useTheme()`.
 */
import { Platform, ViewStyle } from "react-native";

/** Add an alpha channel to a #rrggbb hex color → #rrggbbaa. */
export function withAlpha(hex: string, alpha: number): string {
  const a = Math.round(Math.max(0, Math.min(1, alpha)) * 255)
    .toString(16)
    .padStart(2, "0");
  return `${hex}${a}`;
}

// Module + semantic accents are vivid enough to read on either background, so
// they're shared. Only their pale *Light tints and the neutrals differ per theme.
const ACCENTS = {
  broiler: "#ea580c", // orange — Broiler Production
  hatchery: "#4338ca", // indigo — Hatchery Management
  sms: "#2563eb", // blue — messaging
  account: "#1d4ed8", // blue — Finance & Accounts
  inventory: "#0891b2", // cyan — Inventory & Stock
  sales: "#16a34a", // green — Sales & Dispatch
  purchase: "#f59e0b", // amber — Purchase Management
  hr: "#0d9488", // teal — HR & Attendance
  user: "#4f46e5", // indigo — User & Role
  // Approvals are cross-cutting rather than one module's colour, so slate.
  change_requests: "#64748b",
  accent: "#f59e0b", // amber-500 — warm highlight pop
  danger: "#dc2626",
  success: "#0f9d58", // matches --ds-success in the ERP design system
  warning: "#d97706", // --ds-warning (amber-600) in the ERP design system
  info: "#0ea5e9", // --ds-info; distinct from the blue used for actions
};

export const lightColors = {
  // Brand — charcoal slate (monochrome premium)
  primary: "#1e2a5a", // deep navy indigo — the reference's sidebar/chrome
  primaryDark: "#141c3d", // deeper still: auth backdrops, pressed states
  primaryLight: "#e0e7ff", // indigo-100 — subtle tints
  // Interactive FOREGROUND brand color (links, active tab, accent text/icons).
  // Kept dark in light mode, but bright in dark mode so it stays legible.
  // Actions — buttons, links, active states — are the ERP's --ds-primary
  // blue. Chrome stays charcoal (see `primary`), which the ERP navbar
  // already uses, so the two products share both: charcoal frame, blue
  // action. Picking one for each is what stops them reading as two apps.
  tint: "#2563eb",

  ...ACCENTS,

  // Per-module pale tints
  broilerLight: "#ffedd5",
  hatcheryLight: "#e0e7ff",
  smsLight: "#dbeafe",
  accountLight: "#dbeafe",
  inventoryLight: "#cffafe",
  salesLight: "#dcfce7",
  purchaseLight: "#fef3c7",
  hrLight: "#ccfbf1",
  userLight: "#e0e7ff",
  change_requestsLight: "#e2e8f0",

  // Surfaces / neutrals (slate)
  bg: "#f8fafc",
  surface: "#ffffff",
  surfaceAlt: "#f1f5f9",
  border: "#e2e8f0",
  borderStrong: "#cbd5e1",

  // Text
  text: "#0f172a",
  textMuted: "#64748b",
  textFaint: "#94a3b8",
  onDark: "#ffffff",

  // Semantic pale tints
  dangerLight: "#fee2e2",
  successLight: "#dcfce7",
  warningLight: "#fef3c7",
  infoLight: "#dbeafe",

  // Ink used for elevation shadows.
  shadowInk: "#0f172a",
};

export type Palette = typeof lightColors;

export const darkColors: Palette = {
  // Brand — lift the charcoal so it stays visible (and white-text-safe) on dark.
  primary: "#2c3a6e", // the navy lifted so white text still reads on dark
  primaryDark: "#141c3d",
  primaryLight: withAlpha("#a5b4fc", 0.16),
  // Bright foreground brand color so links / active tab / accent text read on dark.
  tint: "#60a5fa", // blue-400 — the action blue, lifted for dark surfaces

  ...ACCENTS,

  // On dark, pale tints become translucent washes of their accent.
  broilerLight: withAlpha(ACCENTS.broiler, 0.22),
  hatcheryLight: withAlpha(ACCENTS.hatchery, 0.22),
  smsLight: withAlpha(ACCENTS.sms, 0.22),
  accountLight: withAlpha(ACCENTS.account, 0.22),
  inventoryLight: withAlpha(ACCENTS.inventory, 0.22),
  salesLight: withAlpha(ACCENTS.sales, 0.22),
  purchaseLight: withAlpha(ACCENTS.purchase, 0.22),
  hrLight: withAlpha(ACCENTS.hr, 0.22),
  userLight: withAlpha(ACCENTS.user, 0.22),
  change_requestsLight: withAlpha(ACCENTS.change_requests, 0.22),

  // Surfaces / neutrals — deep slate stack
  bg: "#0b1120",
  surface: "#151d2e",
  surfaceAlt: "#1e293b",
  border: "#2b3852",
  borderStrong: "#3b4a63",

  // Text — kept bright for legibility on the deep-slate surfaces
  text: "#f1f5f9",
  textMuted: "#aeb9cc",
  textFaint: "#8996ab",
  onDark: "#ffffff",

  // Semantic tints
  dangerLight: withAlpha(ACCENTS.danger, 0.22),
  successLight: withAlpha(ACCENTS.success, 0.22),
  warningLight: withAlpha(ACCENTS.warning, 0.22),
  infoLight: withAlpha(ACCENTS.info, 0.22),

  shadowInk: "#000000",
};

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };

export const radius = { sm: 8, md: 12, lg: 16, xl: 24, pill: 999 };

export const type = {
  h1: { fontSize: 26, fontWeight: "800" as const, letterSpacing: -0.5 },
  h2: { fontSize: 20, fontWeight: "800" as const, letterSpacing: -0.3 },
  h3: { fontSize: 17, fontWeight: "700" as const },
  title: { fontSize: 15, fontWeight: "700" as const },
  body: { fontSize: 15, fontWeight: "400" as const },
  label: { fontSize: 13, fontWeight: "600" as const },
  caption: { fontSize: 12, fontWeight: "500" as const },
  mono: { fontSize: 13, fontWeight: "600" as const },
};

/** Consistent, subtle elevation across iOS + Android. Pass the active palette's
 *  `shadowInk` so shadows deepen appropriately in dark mode. */
export function shadow(level: 1 | 2 | 3 = 1, ink = lightColors.shadowInk): ViewStyle {
  const map = {
    1: { radius: 6, opacity: 0.06, y: 2, elevation: 2 },
    2: { radius: 14, opacity: 0.1, y: 6, elevation: 5 },
    3: { radius: 24, opacity: 0.16, y: 12, elevation: 10 },
  } as const;
  const s = map[level];
  return Platform.select({
    ios: {
      shadowColor: ink,
      shadowOffset: { width: 0, height: s.y },
      shadowOpacity: s.opacity,
      shadowRadius: s.radius,
    },
    android: { elevation: s.elevation },
    default: {},
  }) as ViewStyle;
}
