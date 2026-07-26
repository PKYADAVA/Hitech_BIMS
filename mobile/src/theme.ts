/**
 * Design tokens for a modern, business-oriented BIMS.
 *
 * A vibrant indigo brand (fintech/SaaS language) with per-module accents so
 * each domain keeps its own identity while the app reads as one system. Note
 * the brand owns the indigo/violet lane, so `account` and `purchase` are tuned
 * to teal/purple to stay distinct from it. Everything else — spacing, radius,
 * type scale, elevation — is centralized here so components never hard-code a
 * value.
 */
import { Platform, ViewStyle } from "react-native";

export const colors = {
  // Brand — modern indigo
  primary: "#4f46e5", // indigo-600
  primaryDark: "#4338ca", // indigo-700 — full-bleed backdrops, pressed states
  primaryLight: "#e0e7ff", // indigo-100 — subtle tints
  accent: "#f59e0b", // amber-500 — warm CTA/highlight pop

  // Per-module identity
  broiler: "#ea580c", // orange-600
  broilerLight: "#ffedd5",
  hatchery: "#d97706", // amber-600
  hatcheryLight: "#fef3c7",
  sms: "#2563eb", // blue-600
  smsLight: "#dbeafe",
  account: "#0d9488", // teal-600 — off the brand's indigo lane
  accountLight: "#ccfbf1",
  inventory: "#0891b2", // cyan-600
  inventoryLight: "#cffafe",
  sales: "#e11d48", // rose-600
  salesLight: "#ffe4e6",
  purchase: "#9333ea", // purple-600 — clearly not the brand indigo
  purchaseLight: "#f3e8ff",
  hr: "#db2777", // pink-600
  hrLight: "#fce7f3",
  user: "#475569", // slate-600
  userLight: "#e2e8f0",

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

  // Semantic
  danger: "#dc2626",
  dangerLight: "#fee2e2",
  success: "#16a34a",
  successLight: "#dcfce7",
  warning: "#f59e0b",
  warningLight: "#fef3c7",
  info: "#2563eb",
  infoLight: "#dbeafe",
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

/** Consistent, subtle elevation across iOS + Android. */
export function shadow(level: 1 | 2 | 3 = 1): ViewStyle {
  const map = {
    1: { radius: 6, opacity: 0.06, y: 2, elevation: 2 },
    2: { radius: 14, opacity: 0.1, y: 6, elevation: 5 },
    3: { radius: 24, opacity: 0.16, y: 12, elevation: 10 },
  } as const;
  const s = map[level];
  return Platform.select({
    ios: {
      shadowColor: "#1e1b4b", // indigo-950 ink — subtle brand-tinted depth
      shadowOffset: { width: 0, height: s.y },
      shadowOpacity: s.opacity,
      shadowRadius: s.radius,
    },
    android: { elevation: s.elevation },
    default: {},
  }) as ViewStyle;
}
