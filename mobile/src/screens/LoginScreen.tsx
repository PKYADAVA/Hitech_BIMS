import { StatusBar } from "expo-status-bar";
import React, { useState } from "react";
import {
  ActivityIndicator,
  Image,
  ImageBackground,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { AppIcon } from "@/components/AppIcon";
import { API_BASE_URL } from "@/config";
import { makeStyles, radius, shadow, spacing, type, useTheme } from "@/theme";
import { useAuthStore } from "@/store/authStore";

/**
 * Sign-in, deliberately built to the same design as the web ERP's login page
 * (`user/templates/login.html` + `static/css/login.css`).
 *
 * The two are the product's only front doors, and a supervisor who uses the
 * phone in the shed and the browser in the office should not have to work out
 * that they are the same system. Same photograph, same green, same lockup, same
 * "Welcome Back!" card and the same reassurance under it — the layout differs
 * only where a phone forces it to.
 */

// The same two files the web login uses, bundled so the screen renders with no
// network at all — a supervisor at a farm gate may have nothing to fetch with.
const HERO = require("../../assets/login-hero.jpg");
const MARK = require("../../assets/hitech-mark.png");

export function LoginScreen() {
  const { colors } = useTheme();
  const styles = useStyles();
  const login = useAuthStore((s) => s.login);
  const error = useAuthStore((s) => s.error);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const disabled = !username.trim() || !password;

  const onSubmit = async () => {
    if (disabled) return;
    setSubmitting(true);
    try {
      await login(username.trim(), password);
    } catch {
      // error text surfaced from the store below
    } finally {
      setSubmitting(false);
    }
  };

  /**
   * Password reset lives on the web ERP, so send them there rather than show a
   * link that goes nowhere. Derived from the API base URL, so a build pointed
   * at the LAN server opens the LAN server's page and not production's.
   */
  const forgotPassword = () => {
    const origin = API_BASE_URL.replace(/\/api\/v1\/?$/, "");
    Linking.openURL(`${origin}/forgot-password/`).catch(() => {});
  };

  return (
    <View style={styles.root}>
      <StatusBar style="light" />
      <SafeAreaView style={styles.safe} edges={["bottom"]}>
        <KeyboardAvoidingView
          style={styles.flex}
          behavior={Platform.OS === "ios" ? "padding" : undefined}
        >
          <ScrollView
            contentContainerStyle={styles.scroll}
            keyboardShouldPersistTaps="handled"
            keyboardDismissMode="interactive"
            automaticallyAdjustKeyboardInsets
            showsVerticalScrollIndicator={false}
          >
            {/* The web page's hero panel, here as the screen's header. It has
                no height of its own — see `hero` in the styles: it takes
                whatever the card leaves, so the page fills any screen without
                the photo growing into a backdrop behind the card. */}
            <ImageBackground source={HERO} style={styles.hero} resizeMode="cover">
              <View style={styles.heroVeil} />
              <SafeAreaView edges={["top"]}>
                <View style={styles.brandRow}>
                  <View style={styles.markBadge}>
                    <Image source={MARK} style={styles.mark} resizeMode="contain" />
                  </View>
                  <View>
                    <Text style={styles.brandName}>Hi Tech Farms</Text>
                    <Text style={styles.brandSub}>POULTRY ERP</Text>
                  </View>
                </View>
              </SafeAreaView>
              <View style={styles.heroCopy}>
                <Text style={styles.heroPitch}>
                  Smart Poultry Management{"\n"}
                  {/* "App" here, "ERP" on the web page this mirrors: the same
                      system, named for the door the user is standing at. */}
                  <Text style={styles.heroPitchAccent}>All in One App</Text>
                </Text>
              </View>
            </ImageBackground>

            <View style={[styles.card, shadow(2)]}>
              <View style={styles.lock}>
                <AppIcon name="lock-outline" size={26} color={colors.success} />
              </View>
              <Text style={styles.title}>Welcome Back!</Text>
              <Text style={styles.lead}>Login to access your ERP account</Text>

              {error ? (
                <View style={styles.errorBox}>
                  <AppIcon name="alert-circle-outline" size={16} color={colors.danger} />
                  <Text style={styles.errorText}>{error}</Text>
                </View>
              ) : null}

              <Text style={styles.label}>Username / Employee ID</Text>
              <View style={styles.control}>
                <AppIcon name="account-outline" size={18} color={colors.success} />
                <TextInput
                  style={styles.input}
                  value={username}
                  onChangeText={setUsername}
                  placeholder="Enter Employee ID or Username"
                  placeholderTextColor={colors.textFaint}
                  autoCapitalize="none"
                  autoCorrect={false}
                  returnKeyType="next"
                />
              </View>

              <Text style={styles.label}>Password</Text>
              <View style={styles.control}>
                <AppIcon name="lock-outline" size={18} color={colors.success} />
                <TextInput
                  style={styles.input}
                  value={password}
                  onChangeText={setPassword}
                  placeholder="Enter Password"
                  placeholderTextColor={colors.textFaint}
                  secureTextEntry={!reveal}
                  autoCapitalize="none"
                  autoCorrect={false}
                  returnKeyType="go"
                  onSubmitEditing={onSubmit}
                />
                <Pressable
                  onPress={() => setReveal((v) => !v)}
                  hitSlop={10}
                  accessibilityRole="button"
                  accessibilityLabel={reveal ? "Hide password" : "Show password"}
                >
                  <AppIcon
                    name={reveal ? "eye-off-outline" : "eye-outline"}
                    size={18}
                    color={colors.textFaint}
                  />
                </Pressable>
              </View>

              <Pressable onPress={forgotPassword} hitSlop={8} style={styles.forgotWrap}>
                <Text style={styles.forgot}>Forgot Password?</Text>
              </Pressable>

              {/* Brand green, not the app's slate `primary`. This is the one
                  screen whose job is to look like Hi Tech Farms, and the web
                  login's button is green — a slate one here breaks the match. */}
              <Pressable
                onPress={onSubmit}
                disabled={disabled || submitting}
                accessibilityRole="button"
                style={({ pressed }) => [
                  styles.submit,
                  disabled && styles.submitOff,
                  pressed && styles.submitPressed,
                ]}
              >
                {submitting ? (
                  <ActivityIndicator color={colors.onDark} />
                ) : (
                  <>
                    <AppIcon name="login" size={18} color={colors.onDark} />
                    <Text style={styles.submitText}>LOGIN</Text>
                  </>
                )}
              </Pressable>

              <View style={styles.assure}>
                <AppIcon name="shield-check-outline" size={18} color={colors.success} />
                <View style={styles.flex}>
                  <Text style={styles.assureTitle}>Secure Login</Text>
                  <Text style={styles.assureText}>
                    Your data is protected with enterprise grade security
                  </Text>
                </View>
              </View>
            </View>

            <Text style={styles.foot}>Powered by Hi Tech Farms</Text>
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

const useStyles = makeStyles((colors) => ({
  root: { flex: 1, backgroundColor: colors.bg },
  safe: { flex: 1 },
  flex: { flex: 1 },
  scroll: { flexGrow: 1, paddingBottom: spacing.md },

  /**
   * No fixed height. `flexGrow` on the scroll content plus `flex: 1` here means
   * the photo takes exactly the room the card does not want: it stretches on a
   * tall screen and gives way on a short one, so the card is never pushed off
   * the bottom and there is never a gap under it. `minHeight` keeps it a
   * photograph rather than a stripe when the keyboard squeezes everything.
   */
  hero: { flex: 1, minHeight: 200, justifyContent: "space-between" },
  // Same job as the web's .hero-veil: enough scrim for white text, not so much
  // that the sunset the photo is carrying goes flat.
  heroVeil: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(12,45,25,0.42)",
  },
  brandRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  /**
   * A white badge, not a bare image. The emblem is drawn on the logo card's
   * white, so dropped straight onto the photo it read as a stray white tile.
   * Rounded, padded and shadowed, that same white becomes the badge it is
   * standing on — deliberate rather than a cut-out that went wrong.
   */
  markBadge: {
    width: 46,
    height: 46,
    borderRadius: 14,
    backgroundColor: "#fff",
    padding: 4,
    alignItems: "center",
    justifyContent: "center",
    ...shadow(1),
  },
  mark: { width: "100%", height: "100%" },
  brandName: { ...type.h3, color: colors.onDark },
  brandSub: {
    ...type.caption,
    fontSize: 10,
    color: "rgba(255,255,255,0.85)",
    letterSpacing: 2,
    marginTop: 1,
  },
  // Clear of the card, which laps over the photo's bottom edge.
  heroCopy: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  heroPitch: {
    ...type.h2,
    color: colors.onDark,
    lineHeight: 28,
    textShadowColor: "rgba(0,0,0,0.4)",
    textShadowRadius: 8,
  },
  heroPitchAccent: { color: "#86efac" },

  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
    padding: spacing.xl,
    marginHorizontal: spacing.lg,
    // Pulled up over the photo, so the card and the hero read as one panel
    // rather than two stacked blocks.
    marginTop: -spacing.xl,
  },
  lock: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.successLight,
    alignItems: "center",
    justifyContent: "center",
    alignSelf: "center",
    marginBottom: spacing.md,
  },
  title: { ...type.h2, color: colors.text, textAlign: "center" },
  lead: {
    ...type.body,
    color: colors.textMuted,
    textAlign: "center",
    marginTop: 4,
    marginBottom: spacing.lg,
  },

  errorBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    backgroundColor: colors.dangerLight,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  errorText: { ...type.label, color: colors.danger, flex: 1 },

  label: { ...type.label, color: colors.text, marginBottom: spacing.xs },
  control: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: 52,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
    marginBottom: spacing.md,
  },
  input: { flex: 1, ...type.body, color: colors.text, paddingVertical: spacing.sm },

  forgotWrap: { alignSelf: "flex-end", marginBottom: spacing.lg },
  forgot: { ...type.label, color: colors.success },

  assure: {
    flexDirection: "row",
    gap: spacing.md,
    backgroundColor: colors.successLight,
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: spacing.lg,
  },
  assureTitle: { ...type.label, color: colors.success },
  assureText: { ...type.caption, color: colors.textMuted, marginTop: 2 },

  submit: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    minHeight: 52,
    borderRadius: radius.md,
    backgroundColor: colors.success,
  },
  submitOff: { opacity: 0.45 },
  submitPressed: { opacity: 0.85 },
  submitText: { ...type.title, color: colors.onDark, letterSpacing: 1 },

  foot: {
    ...type.caption,
    color: colors.textMuted,
    textAlign: "center",
    marginTop: spacing.md,
  },
}));
