/**
 * Jest setup for the mobile app.
 *
 * The permission store is pure logic, but it reaches the API module, which
 * reaches the HTTP client, which reaches secure storage — all native. Stubbing
 * the client here keeps the tests about the gating rules rather than about
 * Expo's module registry.
 */
jest.mock("@/api/client", () => ({
  http: {
    get: jest.fn(),
    post: jest.fn(),
    patch: jest.fn(),
    delete: jest.fn(),
  },
}));

// Anything that imports the catalog reaches the theme, which remembers the
// light/dark choice in AsyncStorage — native, and so unavailable here. The
// package ships its own mock for exactly this.
jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"));

jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async () => null),
  setItemAsync: jest.fn(async () => undefined),
  deleteItemAsync: jest.fn(async () => undefined),
}));
