import { Platform } from "react-native";

import { mimeFromName } from "@/capture";
import { OfflineFile } from "@/offline/types";

/**
 * Keeping a captured photo alive until it can be sent.
 *
 * The camera hands back a uri in the app's *cache* directory. That is fine for
 * a photo posted seconds later, and no use at all for one that has to survive
 * a supervisor finishing a round, the app being killed, and the phone reaching
 * signal an hour on: Android empties that directory whenever it wants storage
 * back, and the queued write would then have a path pointing at nothing.
 *
 * So a photo bound for the queue is copied into the document directory, which
 * is backed up and not reclaimed, and deleted once the write lands.
 *
 * On web there is no document directory. A blob: uri dies with the page, so
 * the bytes themselves are carried as a data: uri — heavier, but it is the
 * only form that survives a reload, and the web build is a desk browser rather
 * than the phone in the shed.
 */

const DIR = "outbox";

/** The directory queued files live in, created on first use. */
async function outboxDirectory() {
  const { Directory, Paths } = await import("expo-file-system");
  const dir = new Directory(Paths.document, DIR);
  if (!dir.exists) dir.create({ intermediates: true });
  return dir;
}

/**
 * Copy a just-captured file somewhere it will still be when the signal returns.
 *
 * Returns the part to store in the queue entry. Throws if the copy fails —
 * queueing a path that is already broken would only produce a write that can
 * never succeed, and the caller should hear about it while the user is still
 * looking at the photo.
 */
export async function persistForOffline(
  field: string,
  uri: string
): Promise<OfflineFile> {
  const name = uri.split("/").pop()?.split("?")[0] || `${field}.jpg`;
  const type = mimeFromName(name);

  if (Platform.OS === "web") {
    const blob = await (await fetch(uri)).blob();
    return { field, uri: await toDataUrl(blob), name, type };
  }

  const { File } = await import("expo-file-system");
  const dir = await outboxDirectory();
  // Prefixed with the clock so two photos of the same name from two rows
  // cannot land on each other.
  const target = new File(dir, `${Date.now()}-${Math.random().toString(36).slice(2, 8)}-${name}`);
  new File(uri).copy(target);
  return { field, uri: target.uri, name, type };
}

/** Read a blob back as a data: uri, the only durable form the browser has. */
function toDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => resolve(String(reader.result));
    reader.readAsDataURL(blob);
  });
}

/**
 * Drop a queued file once its write has landed.
 *
 * Never throws: the write is already filed by the time this runs, and failing
 * the flush over a file that could not be tidied would send it a second time.
 */
export async function discardOfflineFile(file: OfflineFile): Promise<void> {
  if (Platform.OS === "web" || !file.uri.startsWith("file:")) return;
  try {
    const { File } = await import("expo-file-system");
    const stored = new File(file.uri);
    if (stored.exists) stored.delete();
  } catch {
    // Storage is transient here; a stray file is not worth a failed send.
  }
}
