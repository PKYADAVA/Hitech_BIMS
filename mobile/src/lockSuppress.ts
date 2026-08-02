/**
 * A tiny cross-module flag so App Lock doesn't fire when the app briefly
 * backgrounds to show an OS UI *it* launched — the camera, the photo picker, a
 * location prompt. Without this, taking a Daily Entry photo backgrounds the app
 * and LockGate would re-prompt for biometrics on return.
 *
 * `active` counts in-flight privileged calls; `until` keeps suppression alive a
 * moment longer, because AppState's background/foreground events can arrive a
 * beat after the picker returns on some Android devices.
 */
let active = 0;
let until = 0;

const GRACE_MS = 1500;

export function beginPrivilegedUI(): void {
  active += 1;
}

export function endPrivilegedUI(): void {
  active = Math.max(0, active - 1);
  until = Date.now() + GRACE_MS;
}

/** True while (or just after) an app-launched OS UI is on screen. */
export function isPrivilegedUIActive(): boolean {
  return active > 0 || Date.now() < until;
}

/** Run a privileged, app-launched OS interaction with lock suppression around it. */
export async function withPrivilegedUI<T>(fn: () => Promise<T>): Promise<T> {
  beginPrivilegedUI();
  try {
    return await fn();
  } finally {
    endPrivilegedUI();
  }
}
