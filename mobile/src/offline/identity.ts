import AsyncStorage from "@react-native-async-storage/async-storage";

import { database } from "./db";

/**
 * The two identities an offline entry carries, and the one the device does.
 *
 * `local_id` is a UUID: it is the idempotency key, so it has to be unique
 * across every handset in the company without any of them being able to ask.
 *
 * `offline_no` is for people. OFF-20260808-000124 is what a supervisor reads
 * out on the phone when the office asks which entry they mean, and what the
 * office finds in the ERP afterwards — the pair is kept for the life of the
 * record so an audit can follow a figure from the shed to the ledger.
 */

/** A v4 UUID, from the platform's own randomness. */
export async function newLocalId(): Promise<string> {
  try {
    const Crypto = await import("expo-crypto");
    return Crypto.randomUUID();
  } catch {
    // Only reached if the native module is missing — a JS build of the app, or
    // a test. Math.random is not good enough to be the sole guarantee, which
    // is why the server treats a key as unique *per user* rather than globally.
    const hex = () => Math.floor(Math.random() * 16).toString(16);
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) =>
      c === "x" ? hex() : ((Math.floor(Math.random() * 4) + 8).toString(16)));
  }
}

/**
 * The next OFF- number for today.
 *
 * The counter lives in the database beside the queue rather than in memory, so
 * it keeps going across a restart instead of handing out 000001 again after a
 * crash — two entries sharing a number would defeat the point of having one a
 * person can quote.
 */
export async function nextOfflineNumber(on = new Date()): Promise<string> {
  const day = on.toISOString().slice(0, 10).replace(/-/g, "");
  const db = await database();
  const key = `offline_no_${day}`;
  const row = await db.first<{ value: string }>(
    "SELECT value FROM sync_meta WHERE key = ?", [key]);
  const next = Number(row?.value ?? 0) + 1;
  await db.run("INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)",
               [key, String(next)]);
  return `OFF-${day}-${String(next).padStart(6, "0")}`;
}

const DEVICE_KEY = "bims_device_id";
let deviceId: string | null = null;

/**
 * A stable name for this handset.
 *
 * The administrator's monitor lists devices, not just people: "Rahul's phone
 * has seven entries stuck" is only actionable if the phone can be told apart
 * from the one he used last month. Generated once and kept.
 */
export async function currentDeviceId(): Promise<string> {
  if (deviceId) return deviceId;
  const stored = await AsyncStorage.getItem(DEVICE_KEY).catch(() => null);
  if (stored) {
    deviceId = stored;
    return stored;
  }
  const fresh = await describeDevice();
  await AsyncStorage.setItem(DEVICE_KEY, fresh).catch(() => undefined);
  deviceId = fresh;
  return fresh;
}

async function describeDevice(): Promise<string> {
  const id = (await newLocalId()).slice(0, 8);
  try {
    const Device = await import("expo-device");
    const name = [Device.manufacturer, Device.modelName].filter(Boolean).join(" ");
    return name ? `${name} (${id})` : id;
  } catch {
    return id;
  }
}
