/**
 * Theme entry point. Everything imports from `@/theme`:
 *   - static, theme-independent tokens: `spacing`, `radius`, `type`, `shadow`, `withAlpha`
 *   - palettes: `lightColors`, `darkColors`, and the `Palette` type
 *   - runtime theming: `ThemeProvider`, `useTheme`, `makeStyles`
 *   - `colors` — the LIGHT palette, for static/config contexts that never
 *     re-render (e.g. catalog module accents). Inside components, prefer
 *     `useTheme().colors` (or `makeStyles`) so dark mode applies.
 */
export {
  darkColors,
  lightColors,
  radius,
  shadow,
  spacing,
  type,
  withAlpha,
  type Palette,
} from "./tokens";
export {
  makeStyles,
  ThemeProvider,
  useTheme,
  type Scheme,
  type ThemePreference,
} from "./ThemeProvider";

import { lightColors } from "./tokens";

/** Light palette, for static config data (module accents are theme-independent). */
export const colors = lightColors;
