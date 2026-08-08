/**
 * Signing out has to take the cached data with it.
 *
 * The persister keeps registers on disk so they open offline. Left there, the
 * next person to sign in on a shared handset opens a register and reads the
 * previous one's farms — rows their own data scope may never have allowed.
 */
jest.mock("@react-native-async-storage/async-storage", () => ({
  __esModule: true,
  default: {
    removeItem: jest.fn().mockResolvedValue(undefined),
    getItem: jest.fn().mockResolvedValue(null),
    setItem: jest.fn().mockResolvedValue(undefined),
  },
}));

import AsyncStorage from "@react-native-async-storage/async-storage";

import { queryClient } from "@/query/queryClient";
import { clearCachedData } from "./cache";

const removeItem = AsyncStorage.removeItem as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  queryClient.setQueryData(["resource", "/broiler/farms/"], [{ id: 1 }]);
});

describe("clearCachedData", () => {
  it("empties what is in memory", async () => {
    await clearCachedData();
    expect(queryClient.getQueryData(["resource", "/broiler/farms/"])).toBeUndefined();
  });

  it("removes the copy on disk as well", async () => {
    // Clearing only memory leaves the persisted copy to be rehydrated on the
    // next launch, which is the case that actually matters.
    await clearCachedData();
    expect(removeItem).toHaveBeenCalledWith("REACT_QUERY_OFFLINE_CACHE");
  });

  it("still finishes when the store refuses", async () => {
    // Signing out must complete. The in-memory clear has already taken the
    // data off the screen by then.
    removeItem.mockRejectedValueOnce(new Error("storage full"));
    await expect(clearCachedData()).resolves.toBeUndefined();
    expect(queryClient.getQueryData(["resource", "/broiler/farms/"])).toBeUndefined();
  });
});
