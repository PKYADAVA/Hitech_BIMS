import { Platform } from "react-native";

/**
 * Whether the phone is running out of room, and what to say about it.
 *
 * This matters here and almost nowhere else in the app. A queued round is
 * photographs as much as figures, and a handset that has filled up cannot
 * write the next one — the save fails at the moment the supervisor is standing
 * in the shed, which is the worst possible moment to discover it.
 *
 * The one rule this module exists to protect: **nothing pending is ever
 * deleted to make room.** Not the oldest entry, not the largest photo, not
 * automatically and not silently. An unsent entry exists nowhere else, so
 * freeing space by discarding one trades a storage problem for a lost record.
 * Synced entries are pruned (see queue.pruneSynced) because the ERP already
 * holds them; that is the only automatic deletion in the system.
 */

/** Below this, a round of photos may not fit. */
const LOW_BYTES = 250 * 1024 * 1024;
/** Below this, the next save is genuinely at risk. */
const CRITICAL_BYTES = 60 * 1024 * 1024;

export type StorageLevel = "ok" | "low" | "critical" | "unknown";

export interface StorageState {
  level: StorageLevel;
  freeBytes: number | null;
  message: string | null;
}

/** "1.2 GB" / "180 MB" — a number somebody can act on. */
function readable(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

/**
 * What a given amount of free space means, and whether to say anything.
 *
 * Split from the reading itself so the thresholds and the wording — the part
 * with judgement in it — can be exercised directly, without a test having to
 * impersonate the file system to find out what happens at 20 MB.
 *
 * Unknown is not treated as a problem. The reading is unavailable on web and
 * on some Android providers, and warning about storage that may be perfectly
 * fine trains people to dismiss the warning that matters.
 */
export function describeStorage(free: number | null): StorageState {
  if (free === null) return { level: "unknown", freeBytes: null, message: null };

  if (free <= CRITICAL_BYTES) {
    return {
      level: "critical",
      freeBytes: free,
      message: `This phone has only ${readable(free)} left. Sync now, and free `
        + "up space before the next round — nothing already saved will be lost, "
        + "but new entries may not fit.",
    };
  }
  if (free <= LOW_BYTES) {
    return {
      level: "low",
      freeBytes: free,
      message: `Device storage is running low (${readable(free)} left). `
        + "Synchronising now is recommended.",
    };
  }
  return { level: "ok", freeBytes: free, message: null };
}

/** The reading, and what it means. */
export async function checkStorage(): Promise<StorageState> {
  return describeStorage(await freeBytes());
}

/** How much room the platform says is left, or null when it will not say. */
export async function freeBytes(): Promise<number | null> {
  if (Platform.OS === "web") return null;
  try {
    const { Paths } = await import("expo-file-system");
    const available = (Paths as unknown as { availableDiskSpace?: number })
      .availableDiskSpace;
    return typeof available === "number" ? available : null;
  } catch {
    return null;
  }
}
