import { MaterialCommunityIcons } from "@expo/vector-icons";
import React from "react";
import { StyleProp, TextStyle } from "react-native";

import { useTheme } from "@/theme";

/**
 * Single icon system for the app — MaterialCommunityIcons (bundled with Expo,
 * font-based, no native svg needed).
 *
 * The rest of the codebase still describes icons with emoji (in `catalog.ts`,
 * screens, nav), so this component maps each emoji to a real MCI glyph. That
 * keeps hundreds of `icon:` fields untouched while giving one consistent,
 * tintable, sized icon set everywhere. Pass `name` to use an MCI glyph
 * directly, or `emoji` to have it resolved through the map.
 */
export type IconName = keyof typeof MaterialCommunityIcons.glyphMap;

/** Emoji → MaterialCommunityIcons glyph. Every value verified against the
 *  installed glyphmap; unknown emoji fall back to a neutral marker. */
const EMOJI_TO_ICON: Record<string, IconName> = {
  "⏰": "alarm",
  "♨️": "water-boiler",
  "⚙️": "cog-outline",
  "✉️": "email-outline",
  "🌡️": "thermometer",
  "🌴": "palm-tree",
  "🌾": "grain",
  "🎖️": "medal-outline",
  "🎚️": "tune-vertical",
  "🏘️": "home-group",
  "🏛️": "bank-outline",
  "🏠": "home-outline",
  "🏢": "office-building-outline",
  "🏦": "bank-outline",
  "🏬": "storefront-outline",
  "🏭": "factory",
  "🏷️": "tag-outline",
  "🐔": "food-drumstick-outline",
  "🐣": "egg-easter",
  "🐥": "bird",
  "👤": "account-outline",
  "👥": "account-group-outline",
  "👨‍🌾": "account-cowboy-hat-outline",
  "💉": "needle",
  "💬": "message-text-outline",
  "💰": "cash-multiple",
  "💵": "cash",
  "💸": "cash-minus",
  "📁": "folder-outline",
  "📄": "file-document-outline",
  "📅": "calendar-outline",
  "📆": "calendar-month-outline",
  "📈": "chart-line",
  "📉": "trending-down",
  "📊": "chart-bar",
  "📋": "clipboard-text-outline",
  "📍": "map-marker-outline",
  "📏": "ruler",
  "📒": "notebook-outline",
  "📝": "note-edit-outline",
  "📤": "tray-arrow-up",
  "📥": "tray-arrow-down",
  "📦": "package-variant-closed",
  "🔁": "swap-horizontal",
  "🔐": "lock-outline",
  "🔒": "lock-outline",
  "🔑": "key-outline",
  "🚪": "logout",
  "💼": "briefcase-outline",
  "🔬": "microscope",
  "🔍": "magnify",
  "🕒": "clock-outline",
  "🗂️": "folder-multiple-outline",
  "🗺️": "map-outline",
  "🚚": "truck-outline",
  "🛒": "cart-outline",
  "🛡️": "shield-outline",
  "🥚": "egg-outline",
  "🦠": "bacteria-outline",
  "🧑‍💼": "account-tie-outline",
  "🧭": "compass-outline",
  "🧺": "basket-outline",
  "🧾": "receipt",
  "🪪": "card-account-details-outline",
  "👋": "hand-wave-outline",
  "⚠️": "alert-outline",
};

const FALLBACK: IconName = "circle-outline";

/** Resolve an emoji (or already-valid MCI name) to a glyph name. */
export function iconFor(icon: string): IconName {
  if (icon in EMOJI_TO_ICON) return EMOJI_TO_ICON[icon];
  if (icon in MaterialCommunityIcons.glyphMap) return icon as IconName;
  return FALLBACK;
}

export function AppIcon({
  name,
  emoji,
  size = 20,
  color,
  style,
}: {
  /** MCI glyph name (takes precedence over `emoji`). */
  name?: IconName;
  /** Emoji to resolve through the map. */
  emoji?: string;
  size?: number;
  color?: string;
  style?: StyleProp<TextStyle>;
}) {
  const { colors } = useTheme();
  const resolved = name ?? (emoji ? iconFor(emoji) : FALLBACK);
  return <MaterialCommunityIcons name={resolved} size={size} color={color ?? colors.text} style={style} />;
}
