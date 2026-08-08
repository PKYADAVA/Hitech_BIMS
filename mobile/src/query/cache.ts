import AsyncStorage from "@react-native-async-storage/async-storage";

import { queryClient } from "@/query/queryClient";

/** The key the persister writes under (see App.tsx). */
const PERSIST_KEY = "REACT_QUERY_OFFLINE_CACHE";

/**
 * Forget everything fetched for the session that is ending.
 *
 * Two places hold it: the in-memory cache, and the copy the persister keeps on
 * disk so registers open offline. Clearing only the first leaves the second to
 * be rehydrated on the next launch, which is the case that matters — the next
 * person to sign in on a shared handset would open a register and read the
 * previous one's farms.
 */
export async function clearCachedData(): Promise<void> {
  queryClient.clear();
  try {
    await AsyncStorage.removeItem(PERSIST_KEY);
  } catch {
    // Signing out must finish even if the store refuses; the in-memory clear
    // above has already taken the data off the screen.
  }
}
