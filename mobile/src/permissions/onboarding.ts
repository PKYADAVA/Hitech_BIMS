import * as Device from "expo-device";
import * as ImagePicker from "expo-image-picker";
import * as Location from "expo-location";
import * as Notifications from "expo-notifications";

import { withPrivilegedUI } from "@/lockSuppress";

/**
 * Ask once, up front, for every OS permission the app uses anywhere —
 * notifications, location, camera — rather than letting each feature prompt
 * the first time someone happens to use it.
 *
 * Every screen that actually needs one of these (capture.ts, push.ts)
 * already asks for it lazily and copes with a refusal, so this is not load
 * bearing: it only means a supervisor sees the OS dialogs together, on
 * first sign-in, instead of scattered across their first week of use.
 * `getPermissionsAsync` is checked before `request...Async` so a permission
 * already decided (granted *or* denied) is never re-prompted here — the OS
 * itself refuses to ask twice on some platforms, but checking first also
 * means a previously-granted permission costs no dialog at all.
 */
export async function requestOnboardingPermissions(): Promise<void> {
  // Simulators and Expo Go can't take a push token; asking would just throw.
  if (Device.isDevice) {
    await ensure(Notifications.getPermissionsAsync, Notifications.requestPermissionsAsync);
  }
  await ensure(Location.getForegroundPermissionsAsync, Location.requestForegroundPermissionsAsync);
  await ensure(ImagePicker.getCameraPermissionsAsync, ImagePicker.requestCameraPermissionsAsync);
  // Covers "pick from gallery" (the fallback when a photo was taken earlier)
  // — the other half of "camera for upload".
  await ensure(ImagePicker.getMediaLibraryPermissionsAsync, ImagePicker.requestMediaLibraryPermissionsAsync);
}

type PermissionResponse = { status: string; granted?: boolean };

async function ensure(
  check: () => Promise<PermissionResponse>,
  request: () => Promise<PermissionResponse>
): Promise<void> {
  try {
    const current = await check();
    if (current.status !== "undetermined") return; // already granted or already refused
    await withPrivilegedUI(request);
  } catch {
    // A platform that doesn't support one of these (e.g. location on web
    // without a secure context) must not stop the others from being asked.
  }
}
