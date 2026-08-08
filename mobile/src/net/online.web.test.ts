/**
 * @jest-environment jsdom
 *
 * The browser reports connectivity on the window, not through NetInfo.
 *
 * NetInfo's web build subscribes to `navigator.connection` when the browser
 * offers one, and Chrome does. It never raises `change` for a dropped
 * connection, so this went in reporting online with the network pulled.
 */
jest.mock("react-native", () => ({ Platform: { OS: "web" } }));

const mockNetInfoListen = jest.fn(() => () => undefined);
jest.mock("@react-native-community/netinfo", () => ({
  __esModule: true,
  default: { addEventListener: mockNetInfoListen },
}));

import { onlineManager } from "@tanstack/react-query";

import { startOnlineWatch } from "./online";

/** Take the browser off the network the way the browser itself would. */
const setBrowserOnline = (online: boolean) => {
  Object.defineProperty(window.navigator, "onLine", {
    value: online,
    configurable: true,
  });
  window.dispatchEvent(new Event(online ? "online" : "offline"));
};

beforeEach(() => {
  mockNetInfoListen.mockClear();
  setBrowserOnline(true);
  startOnlineWatch();
});

describe("startOnlineWatch on web", () => {
  it("follows the window when the connection drops", () => {
    setBrowserOnline(false);
    expect(onlineManager.isOnline()).toBe(false);
  });

  it("follows it back when the connection returns", () => {
    setBrowserOnline(false);
    setBrowserOnline(true);
    expect(onlineManager.isOnline()).toBe(true);
  });

  it("seeds from the browser rather than assuming online", () => {
    // Subscribing does not itself produce an event, so a page opened with no
    // connection would otherwise sit there claiming to be online.
    onlineManager.setOnline(true);
    Object.defineProperty(window.navigator, "onLine", {
      value: false,
      configurable: true,
    });
    startOnlineWatch();
    expect(onlineManager.isOnline()).toBe(false);
  });

  it("leaves NetInfo alone", () => {
    expect(mockNetInfoListen).not.toHaveBeenCalled();
  });
});
