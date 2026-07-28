import AsyncStorage from "@react-native-async-storage/async-storage";
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { StyleSheet, useColorScheme } from "react-native";

import { darkColors, lightColors, Palette } from "./tokens";

export type ThemePreference = "light" | "dark" | "system";
export type Scheme = "light" | "dark";

interface ThemeContextValue {
  colors: Palette;
  scheme: Scheme;
  /** What the user picked (may be "system"). */
  preference: ThemePreference;
  setPreference: (p: ThemePreference) => void;
}

const STORAGE_KEY = "theme.preference";

const ThemeContext = createContext<ThemeContextValue>({
  colors: lightColors,
  scheme: "light",
  preference: "system",
  setPreference: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const system = useColorScheme(); // live OS setting ("light" | "dark" | null)
  const [preference, setPref] = useState<ThemePreference>("system");

  // Restore the saved preference once on mount.
  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY).then((v) => {
      if (v === "light" || v === "dark" || v === "system") setPref(v);
    });
  }, []);

  const setPreference = (p: ThemePreference) => {
    setPref(p);
    AsyncStorage.setItem(STORAGE_KEY, p).catch(() => {});
  };

  const scheme: Scheme = preference === "system" ? (system === "dark" ? "dark" : "light") : preference;

  const value = useMemo<ThemeContextValue>(
    () => ({
      colors: scheme === "dark" ? darkColors : lightColors,
      scheme,
      preference,
      setPreference,
    }),
    [scheme, preference]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}

/**
 * Build a `useStyles` hook from a factory that receives the *active* palette.
 * Name the factory param `colors` and existing `StyleSheet.create` bodies need
 * no inner changes — they just become theme-aware.
 *
 *   const useStyles = makeStyles((colors) => ({ box: { color: colors.text } }));
 *   function Comp() { const styles = useStyles(); ... }
 */
export function makeStyles<T extends StyleSheet.NamedStyles<T>>(factory: (colors: Palette) => T) {
  return function useStyles(): T {
    const { colors } = useTheme();
    return useMemo(() => StyleSheet.create(factory(colors)), [colors]);
  };
}
