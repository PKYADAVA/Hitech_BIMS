import * as ImagePicker from "expo-image-picker";
import * as Location from "expo-location";
import { Platform } from "react-native";

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

function toCaptured(asset: ImagePicker.ImagePickerAsset): CapturedImage {
  // Derive a filename the backend can store; ImagePicker omits it on some
  // Android providers, and Django needs *some* name to write the file.
  const fromUri = asset.uri.split("/").pop() || "";
  const name = asset.fileName || fromUri || `capture-${Date.now()}.jpg`;
  return { uri: asset.uri, name, mimeType: asset.mimeType || FALLBACK_MIME };
}

/** Open the camera. Null if permission is refused or the user backs out. */
export async function capturePhoto(): Promise<CapturedImage | null> {
  const perm = await ImagePicker.requestCameraPermissionsAsync();
  if (!perm.granted) return null;

  const result = await ImagePicker.launchCameraAsync({
    mediaTypes: ["images"],
    quality: 0.6, // field photos travel over rural mobile data
    exif: false,
  });
  if (result.canceled || !result.assets?.length) return null;
  return toCaptured(result.assets[0]);
}

/** Pick from the gallery — the fallback when a photo was taken earlier. */
export async function pickPhoto(): Promise<CapturedImage | null> {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!perm.granted) return null;

  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    quality: 0.6,
    exif: false,
  });
  if (result.canceled || !result.assets?.length) return null;
  return toCaptured(result.assets[0]);
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
    const perm = await Location.requestForegroundPermissionsAsync();
    if (!perm.granted) return null;

    const pos = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.Balanced,
    });
    return {
      latitude: String(pos.coords.latitude),
      longitude: String(pos.coords.longitude),
    };
  } catch {
    // No fix, location services off, or (on web) a blocked geolocation prompt.
    return null;
  }
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
    type: FALLBACK_MIME,
  } as unknown as Blob);
}
