import { Row } from "@/api/types";

/**
 * Since domain endpoints use `__all__` serializers, screens don't have precise
 * per-model types yet. `pick` reads the first present, non-empty candidate key
 * as a display string, with a fallback — so a screen renders sensibly even
 * before typed models exist for a resource.
 */
export function pick(row: Row, keys: string[], fallback = ""): string {
  for (const key of keys) {
    const value = row[key];
    if (value !== null && value !== undefined && value !== "") return String(value);
  }
  return fallback;
}
