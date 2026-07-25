import { useHeaderHeight } from "@react-navigation/elements";
import React from "react";
import { KeyboardAvoidingView, Platform, ScrollView, ScrollViewProps } from "react-native";

/**
 * The one scroll container every input-bearing screen should use, so the
 * keyboard can never hide a field or button anywhere in the app.
 *
 * Uses a `KeyboardAvoidingView` that's active on BOTH platforms — Expo SDK 54
 * forces edge-to-edge on Android, where `adjustResize` no longer shrinks the
 * window, so we can't rely on it (nor on iOS-only `automaticallyAdjustKeyboard-
 * Insets`). `keyboardVerticalOffset` is the real navigation-header height, so
 * the content lifts by exactly the keyboard's overlap and no more.
 *
 * Must be used inside a screen that has a navigation header (it reads the header
 * height). `keyboardShouldPersistTaps="handled"` keeps buttons/pickers tappable
 * while the keyboard is open; `keyboardDismissMode="interactive"` drags to close.
 */
export function KeyboardAwareScrollView({ children, style, ...rest }: ScrollViewProps) {
  const headerHeight = useHeaderHeight();
  return (
    <KeyboardAvoidingView
      style={style ?? { flex: 1 }}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
      keyboardVerticalOffset={headerHeight}
    >
      <ScrollView
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="interactive"
        showsVerticalScrollIndicator={false}
        {...rest}
      >
        {children}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
