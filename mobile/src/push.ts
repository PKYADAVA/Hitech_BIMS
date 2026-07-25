import Constants from "expo-constants";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { http } from "@/api/client";
import { Envelope } from "@/api/types";

// How notifications appear while the app is foregrounded.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

/**
 * Ask permission, get the Expo push token, and register it with the backend.
 * Safe on simulators / Expo Go (returns null instead of throwing) — real push
 * requires the standalone build.
 */
export async function registerForPush(): Promise<string | null> {
  try {
    if (!Device.isDevice) return null;

    if (Platform.OS === "android") {
      await Notifications.setNotificationChannelAsync("default", {
        name: "Default",
        importance: Notifications.AndroidImportance.DEFAULT,
      });
    }

    let status = (await Notifications.getPermissionsAsync()).status;
    if (status !== "granted") {
      status = (await Notifications.requestPermissionsAsync()).status;
    }
    if (status !== "granted") return null;

    const projectId =
      (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas
        ?.projectId;
    const tokenResp = await Notifications.getExpoPushTokenAsync(
      projectId ? { projectId } : undefined
    );
    const token = tokenResp.data;
    await http.post("/devices/register", { token, platform: Platform.OS });
    return token;
  } catch {
    return null;
  }
}

export interface PushTestResult {
  sent: number;
  status?: number;
  error?: string;
}

/** Trigger a test push to the current user's devices. */
export async function sendTestPush(): Promise<PushTestResult> {
  const resp = await http.post<Envelope<PushTestResult>>("/devices/test", {});
  return resp.data.data;
}
