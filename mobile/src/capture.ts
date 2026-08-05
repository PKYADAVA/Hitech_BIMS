import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import * as Location from "expo-location";
import { Platform } from "react-native";

import { withPrivilegedUI } from "@/lockSuppress";

/**
 * Field capture for the Daily Entry form — photo evidence and a GPS stamp,
 * filling the `mort_image` / `cull_image` / `feed_image` and
 * `entry_latitude` / `entry_longitude` columns the backend already exposes.
 *
 * Every function resolves to null rather than throwing when permission is
 * denied or the device can't oblige: capture is optional on the model, so a
 * refused prompt must leave the rest of the entry saveable.
 */

/** A picked image, in the shape multipart upload needs. */
export interface CapturedImage {
  uri: string;
  name: string;
  mimeType: string;
}

const FALLBACK_MIME = "image/jpeg";

/** Thrown when the OS permission for the camera / photo library is refused, so
 *  the caller can prompt the user to enable it (rather than silently no-op). */
export class CapturePermissionError extends Error {
  constructor(public kind: "camera" | "library") {
    super(`${kind} permission denied`);
    this.name = "CapturePermissionError";
  }
}

/**
 * Why a location could not be read.
 *
 * `captureLocation` collapses every failure into null, which is right where a
 * pin is a bonus. Where it is *required* — a trip that cannot be started
 * without one — the caller has to tell "switch your GPS on" from "this app
 * needs permission", because they are fixed in different places.
 */
export type LocationProblem = "services-off" | "denied" | "no-fix";

export class LocationUnavailableError extends Error {
  constructor(public reason: LocationProblem) {
    super(`location unavailable: ${reason}`);
    this.name = "LocationUnavailableError";
  }
}

/** Current position, or a typed error saying what to fix. */
export async function requireLocation(): Promise<CapturedPoint> {
  return withPrivilegedUI(async () => {
    if (!(await Location.hasServicesEnabledAsync())) {
      throw new LocationUnavailableError("services-off");
    }
    const perm = await Location.requestForegroundPermissionsAsync();
    if (!perm.granted) throw new LocationUnavailableError("denied");
    try {
      const pos = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      return {
        latitude: String(pos.coords.latitude),
        longitude: String(pos.coords.longitude),
      };
    } catch {
      throw new LocationUnavailableError("no-fix");
    }
  });
}

/** Open the place the user has to go to fix it: the device's location
 *  settings on Android, this app's settings elsewhere. */
export async function openLocationSettings(): Promise<void> {
  if (Platform.OS === "android") {
    const IntentLauncher = await import("expo-intent-launcher");
    await IntentLauncher.startActivityAsync(
      IntentLauncher.ActivityAction.LOCATION_SOURCE_SETTINGS);
    return;
  }
  const { Linking } = await import("react-native");
  await Linking.openSettings();
}

function toCaptured(asset: ImagePicker.ImagePickerAsset): CapturedImage {
  // Derive a filename the backend can store; ImagePicker omits it on some
  // Android providers, and Django needs *some* name to write the file.
  const fromUri = asset.uri.split("/").pop() || "";
  const name = asset.fileName || fromUri || `capture-${Date.now()}.jpg`;
  return { uri: asset.uri, name, mimeType: asset.mimeType || FALLBACK_MIME };
}

/** Open the camera. Null if the user backs out; throws if permission is refused.
 *  Wrapped in `withPrivilegedUI` so the permission dialog + camera backgrounding
 *  the app doesn't trip biometric App Lock. */
export async function capturePhoto(): Promise<CapturedImage | null> {
  return withPrivilegedUI(async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) throw new CapturePermissionError("camera");

    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ["images"],
      quality: 0.6, // field photos travel over rural mobile data
      exif: false,
    });
    if (result.canceled || !result.assets?.length) return null;
    return toCaptured(result.assets[0]);
  });
}

/** Pick from the gallery — the fallback when a photo was taken earlier. */
export async function pickPhoto(): Promise<CapturedImage | null> {
  return withPrivilegedUI(async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) throw new CapturePermissionError("library");

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ["images"],
      quality: 0.6,
      exif: false,
    });
    if (result.canceled || !result.assets?.length) return null;
    return toCaptured(result.assets[0]);
  });
}

export interface CapturedPoint {
  latitude: string;
  longitude: string;
}

/**
 * Current GPS position, as strings ready for the form's string-valued state.
 * Null when permission is refused or no fix is available.
 */
export async function captureLocation(): Promise<CapturedPoint | null> {
  try {
    return await withPrivilegedUI(async () => {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (!perm.granted) return null;

      const pos = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });
      return {
        latitude: String(pos.coords.latitude),
        longitude: String(pos.coords.longitude),
      };
    });
  } catch {
    // No fix, location services off, or (on web) a blocked geolocation prompt.
    return null;
  }
}

/**
 * A file from the device's storage — a PDF scan, a photographed cheque already
 * saved, anything the farmer has on their phone rather than in front of them.
 *
 * Deliberately unfiltered by type: the ERP's capture slots accept whatever the
 * branch has on file, and refusing a format here would mean the visit cannot
 * record something the desk can.
 */
export async function pickDocument(): Promise<CapturedImage | null> {
  const result = await DocumentPicker.getDocumentAsync({
    type: "*/*",
    copyToCacheDirectory: true,
  });
  if (result.canceled || !result.assets?.length) return null;
  const asset = result.assets[0];
  return {
    uri: asset.uri,
    name: asset.name || "document",
    mimeType: asset.mimeType || mimeFromName(asset.name || ""),
  };
}

/**
 * The content type a filename implies.
 *
 * Uploads used to be posted as image/jpeg whatever they were, which is a lie
 * as soon as the slot holds a PDF — the stored file is fine, but anything that
 * trusts the declared type (a preview, a virus scan, a strict validator) is
 * reading the wrong thing.
 */
export function mimeFromName(name: string): string {
  const ext = name.toLowerCase().split(".").pop() || "";
  return {
    pdf: "application/pdf",
    png: "image/png",
    gif: "image/gif",
    webp: "image/webp",
    heic: "image/heic",
    doc: "application/msword",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  }[ext] ?? FALLBACK_MIME;
}

/** True when the value is a freshly captured local file rather than a stored URL. */
export function isLocalCapture(value: string): boolean {
  return (
    !!value &&
    !value.startsWith("http://") &&
    !value.startsWith("https://") &&
    (value.startsWith("file:") || value.startsWith("data:") || value.startsWith("blob:"))
  );
}

/**
 * Append a captured image to a FormData body.
 *
 * React Native's FormData takes a {uri, name, type} object and streams the file
 * itself; on web the URI has to be fetched back into a Blob first, since the
 * browser has no equivalent shorthand.
 */
export async function appendImage(
  form: FormData,
  field: string,
  value: string
): Promise<void> {
  const name = value.split("/").pop() || `${field}.jpg`;
  if (Platform.OS === "web") {
    const blob = await (await fetch(value)).blob();
    form.append(field, blob, name);
    return;
  }
  form.append(field, {
    uri: value,
    name,
    type: mimeFromName(name),
  } as unknown as Blob);
}
