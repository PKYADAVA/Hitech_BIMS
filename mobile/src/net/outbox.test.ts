/**
 * Saving on a farm with no signal, and what happens on the way back.
 *
 * The read cache already let a register open with no bars. Saving was the half
 * that still needed the network: the day's entry failed and the only record of
 * the round was on paper, or nowhere.
 */
const store: Record<string, string> = {};
jest.mock("@react-native-async-storage/async-storage", () => ({
  __esModule: true,
  default: {
    getItem: jest.fn(async (k: string) => store[k] ?? null),
    setItem: jest.fn(async (k: string, v: string) => { store[k] = v; }),
    removeItem: jest.fn(async (k: string) => { delete store[k]; }),
  },
}));

// The mocks are read back off the module rather than closed over: the import
// of writeThrough below is hoisted above these declarations, so a factory
// referring to an outer const would run against an uninitialised binding and
// leave http.post undefined — which reads, from writeThrough, as a network
// failure, and quietly queues every send the test means to go out.
jest.mock("@/api/client", () => ({
  http: { post: jest.fn(), patch: jest.fn(), delete: jest.fn(), put: jest.fn() },
}));

jest.mock("./outboxFiles", () => ({
  persistForOutbox: jest.fn(async (field: string, uri: string) => ({
    field, uri: `file:///documents/outbox/kept-${uri.split("/").pop()}`,
    name: "shot.jpg", type: "image/jpeg",
  })),
  discardOutboxFile: jest.fn(async () => undefined),
}));

import { onlineManager } from "@tanstack/react-query";

import { http } from "@/api/client";
import {
  clearOutbox, enqueue, flushOutbox, outboxState, pendingWrites,
  resolvePlaceholders, setOutboxUser,
} from "./outbox";
import { writeThrough } from "./writeThrough";

const mockPost = http.post as jest.Mock;

/** An error shaped the way ApiError is: a status, or none when nothing came back. */
const failure = (status?: number, code?: string) =>
  Object.assign(new Error(code ?? "failed"), { status, code });

beforeEach(async () => {
  jest.clearAllMocks();
  Object.keys(store).forEach((k) => delete store[k]);
  onlineManager.setOnline(true);
  setOutboxUser("7");
  await clearOutbox();
  mockPost.mockResolvedValue({ data: { data: { id: 42 } } });
});

describe("writeThrough", () => {
  it("sends straight out when there is a signal", async () => {
    const result = await writeThrough({
      label: "Day Record", method: "POST", path: "/broiler/daily-entries/",
      body: { fields: { mortality: 3 } },
    });
    expect(result).toEqual({ queued: false, data: { id: 42 } });
    expect(await pendingWrites()).toHaveLength(0);
  });

  it("holds the save when there is none", async () => {
    onlineManager.setOnline(false);
    const result = await writeThrough({
      label: "Day Record", method: "POST", path: "/broiler/daily-entries/",
      body: { fields: { mortality: 3 } },
    });
    expect(result.queued).toBe(true);
    expect(mockPost).not.toHaveBeenCalled();
    expect(await pendingWrites()).toHaveLength(1);
  });

  it("holds it when the signal dies mid-request", async () => {
    // The phone still believed it was online; the request is what found out.
    mockPost.mockRejectedValueOnce(failure());
    const result = await writeThrough({
      label: "Day Record", method: "POST", path: "/broiler/daily-entries/",
      body: { fields: { mortality: 3 } },
    });
    expect(result.queued).toBe(true);
    expect(await pendingWrites()).toHaveLength(1);
  });

  it("throws a rejected payload rather than queueing it", async () => {
    // The user is still looking at the form. Filing an invalid save for later
    // would tell them it worked and surface the failure hours afterwards.
    mockPost.mockRejectedValueOnce(failure(400));
    await expect(writeThrough({
      label: "Day Record", method: "POST", path: "/broiler/daily-entries/",
      body: { fields: { mortality: -1 } },
    })).rejects.toBeTruthy();
    expect(await pendingWrites()).toHaveLength(0);
  });

  it("stamps every send with a key so a lost answer cannot double-post", async () => {
    await writeThrough({
      label: "Day Record", method: "POST", path: "/broiler/daily-entries/",
      body: { fields: { mortality: 3 } },
    });
    const [, , config] = mockPost.mock.calls[0];
    expect(config.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("copies a photo out of the camera cache before queueing it", async () => {
    // Android empties the cache directory whenever it wants storage back, and
    // the queued write would then point at nothing.
    onlineManager.setOnline(false);
    await writeThrough({
      label: "Day Record", method: "POST", path: "/broiler/daily-entries/",
      body: { fields: { kind: "mort" }, files: [{ field: "image", uri: "file:///cache/a.jpg" }] },
    });
    const [entry] = await pendingWrites();
    expect(entry.files?.[0].uri).toBe("file:///documents/outbox/kept-a.jpg");
  });
});

describe("flushOutbox", () => {
  const queueEntry = (over: Partial<Parameters<typeof enqueue>[0]> = {}) =>
    enqueue({
      id: over.id ?? "w-1", label: "Day Record", method: "POST",
      path: "/broiler/daily-entries/", body: { mortality: 3 }, ...over,
    });

  it("sends what was waiting and empties the queue", async () => {
    await queueEntry();
    const result = await flushOutbox();
    expect(result.sent).toBe(1);
    expect(await pendingWrites()).toHaveLength(0);
  });

  it("reuses the entry's own key as the idempotency key", async () => {
    await queueEntry({ id: "w-stable" });
    await flushOutbox();
    expect(mockPost.mock.calls[0][2].headers["Idempotency-Key"]).toBe("w-stable");
  });

  it("stops at the first write that cannot go", async () => {
    // A day's photos reference the entry they hang off. Skipping past a failed
    // entry to send them would post against an id that does not exist.
    await queueEntry({ id: "w-1" });
    await queueEntry({ id: "w-2" });
    mockPost.mockRejectedValueOnce(failure());
    const result = await flushOutbox();
    expect(result.sent).toBe(0);
    expect(await pendingWrites()).toHaveLength(2);
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it("puts the entry's real id into the photo that followed it", async () => {
    await queueEntry({ id: "w-entry", produces: "tmp:w-entry" });
    await queueEntry({
      id: "w-photo", label: "Day Record photo", path: "/broiler/daily-entry-photos/",
      body: { entry: "tmp:w-entry", kind: "mort" },
      files: [{ field: "image", uri: "file:///documents/outbox/a.jpg",
                name: "a.jpg", type: "image/jpeg" }],
    });
    await flushOutbox();
    const form = mockPost.mock.calls[1][1] as FormData;
    expect(form.get("entry")).toBe("42");
  });

  it("steps over a write the server refuses, and keeps it", async () => {
    // A rejected save the user never hears about is a lost record.
    await queueEntry({ id: "w-bad" });
    await queueEntry({ id: "w-good" });
    mockPost.mockRejectedValueOnce(failure(400));
    const result = await flushOutbox();
    expect(result).toEqual({ sent: 1, failed: 1 });
    const left = await pendingWrites();
    expect(left).toHaveLength(1);
    expect(left[0].rejected).toBe(true);
    expect(outboxState()).toMatchObject({ pending: 0, rejected: 1 });
  });

  it("comes back to a server that is still busy with the same key", async () => {
    // 409 idempotency_in_progress means the first attempt is still running —
    // the write is landing, not failing.
    await queueEntry();
    mockPost.mockRejectedValueOnce(failure(409, "idempotency_in_progress"));
    await flushOutbox();
    const [entry] = await pendingWrites();
    expect(entry.rejected).toBeFalsy();
  });

  it("leaves another user's queued round alone", async () => {
    // Ending a shift before reaching signal must not lose the round, and it
    // must not file it under whoever signs in next either.
    await queueEntry({ id: "w-theirs" });
    setOutboxUser("9");
    const result = await flushOutbox();
    expect(result.sent).toBe(0);
    expect(mockPost).not.toHaveBeenCalled();
    expect(outboxState().pending).toBe(0);

    setOutboxUser("7");
    expect(outboxState().pending).toBe(1);
  });

  it("survives a restart", async () => {
    // The queue is on disk precisely because the app gets killed on the walk
    // back to signal. A fresh module registry is that restart.
    await queueEntry({ id: "w-persisted" });
    let fresh!: typeof import("./outbox");
    jest.isolateModules(() => {
      fresh = require("./outbox") as typeof import("./outbox");
    });
    fresh.setOutboxUser("7");
    const survivors = await fresh.pendingWrites();
    expect(survivors).toHaveLength(1);
    expect(survivors[0].id).toBe("w-persisted");
  });
});

describe("resolvePlaceholders", () => {
  it("reaches into nested values", () => {
    const ids = new Map([["tmp:a", "42"]]);
    expect(resolvePlaceholders({ e: "tmp:a", rows: [{ e: "tmp:a" }] }, ids))
      .toEqual({ e: "42", rows: [{ e: "42" }] });
  });

  it("leaves anything it has no id for", () => {
    expect(resolvePlaceholders({ e: "tmp:unknown", n: 3 }, new Map()))
      .toEqual({ e: "tmp:unknown", n: 3 });
  });
});
